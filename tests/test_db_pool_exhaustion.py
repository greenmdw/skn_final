"""DB 커넥션 풀 고갈 방지 (2026-10-08, 1단계-1).

동시 추천을 몇 건 돌리면 풀(최대 10)이 바닥나 다른 요청이 PoolTimeout → 500 으로 죽었다. 원인은 추천 설명(LLM, 20초 안팎)과
임베딩 검색을 DB 연결을 쥔 채 했던 것이다. 여기서는
  1) 설명 LLM 을 부르는 동안 풀에서 빌려 간 연결이 없는지,
  2) 풀이 바닥나면 500 이 아니라 503(+Retry-After)으로 답하는지,
  3) 풀 크기·대기 시간이 환경변수로 정해지는지
를 본다. LLM 은 부르지 않는다(모의 모드).
"""
from __future__ import annotations

import importlib
import os
from contextlib import contextmanager

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from psycopg_pool import PoolTimeout

    from src import config, db
    from src.engine import stage5_explain
    from tests.test_list_history_http import _recommended_list, _signed_up


def _in_use() -> int:
    stats = db.get_pool().get_stats()
    return stats["pool_size"] - stats["pool_available"]


def test_no_pooled_connection_is_held_while_the_explanation_llm_runs(monkeypatch):
    """추천 설명([5], LLM)을 만드는 동안 풀에서 빌려 간 연결이 0개여야 한다 — 그래야 동시 추천이 풀을 말리지 않는다."""
    seen: list[int] = []
    original = stage5_explain.run

    def watched(*args, **kwargs):
        seen.append(_in_use())
        return original(*args, **kwargs)

    monkeypatch.setattr(stage5_explain, "run", watched)
    client = _signed_up()
    _recommended_list(client)
    assert seen == [0], f"설명 LLM 을 부르는 동안 빌려 간 연결 수: {seen}"


def test_a_saturated_pool_answers_503_with_retry_after_not_500(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import app
    from src.routers import lists

    @contextmanager
    def exhausted():
        raise PoolTimeout("couldn't get a connection after 5.00 sec")
        yield  # pragma: no cover

    monkeypatch.setattr(lists, "get_conn", exhausted)
    response = TestClient(app).get("/lists")
    assert response.status_code == 503, response.text
    assert response.headers.get("retry-after") == "2"
    error = response.json()["error"]
    assert error["code"] == "service_busy" and "다시" in error["message"]


def test_pool_size_and_wait_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DB_POOL_MAX", "7")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "1.5")
    try:
        reloaded = importlib.reload(config)
        assert (reloaded.DB_POOL_MIN, reloaded.DB_POOL_MAX, reloaded.DB_POOL_TIMEOUT) == (2, 7, 1.5)
    finally:
        monkeypatch.delenv("DB_POOL_MAX")
        monkeypatch.delenv("DB_POOL_TIMEOUT")
        importlib.reload(config)
    assert config.DB_POOL_MAX == 20 and config.DB_POOL_TIMEOUT == 5.0
