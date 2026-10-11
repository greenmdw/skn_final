"""결과 폴링(GET /result) 페이로드·쿼리 가벼움 (2026-10-10).

추천 한 건의 reasoning_log 는 약 236KB(리뷰 계산 snapshot 이 대부분)이고, 폴링마다 응답에 그대로 실려 나가고(약 820KB) DB 에서도 매번
읽혔다. AWS 단계 부하(동시 20~30명)에서 이 쿼리가 DB 부하 1위였다. 여기서는
  1) 응답에 snapshot 을 싣지 않고(프론트는 reasoning_log 를 안 쓴다) 다른 내용은 그대로인지,
  2) 폴링용 조회가 큰 열을 읽지 않는지,
  3) 완료된 실행의 snapshot 을 한 번만 읽고 캐시하는지
를 본다. LLM 은 부르지 않는다(모의 모드).
"""
from __future__ import annotations

import json
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.db import get_conn
    from src.repo.engine_repo import EngineRepo
    from src.services import recommendation_review_snapshot as snap
    from src.services.recommendation_review_snapshot import SNAPSHOT_STEP
    from tests.test_list_history_http import _recommended_list, _signed_up


@pytest.fixture(autouse=True)
def _fresh_cache():
    snap.clear_snapshot_cache()
    yield
    snap.clear_snapshot_cache()


def test_the_polling_response_does_not_carry_the_review_snapshot_and_stays_small():
    client = _signed_up()
    lid, _rev, _data = _recommended_list(client)
    response = client.get(f"/session/{lid}/result")
    body = response.json()
    assert body["status"] == "done"
    steps = [s.get("step") for s in body["reasoning_log"]]
    assert SNAPSHOT_STEP not in steps
    assert len(response.content) < 250_000, len(response.content)          # 예전에는 약 820KB
    assert all(i["review_detail"]["status"] in ("ready", "failed", "pending") for i in body["items"] if i["selected"])


def test_review_details_per_item_are_still_filled_from_the_cached_snapshot():
    client = _signed_up()
    lid, _rev, data = _recommended_list(client)
    again = client.get(f"/session/{lid}/result").json()
    for before, after in zip(data["items"], again["items"]):
        assert before["review_detail"] == after["review_detail"]          # 첫 조회(캐시 채움)와 다음 조회(캐시 사용)가 같다


def test_the_light_run_query_skips_the_heavy_columns():
    client = _signed_up()
    lid, rev, _data = _recommended_list(client)
    with get_conn() as conn:
        erepo = EngineRepo(conn)
        light = erepo.get_latest_run_light(rev)
        full = erepo.get_latest_run(rev)
    assert "reasoning_log" not in light and "input_snapshot" not in light
    assert light["id"] == full["id"] and light["status"] == full["status"] and light["explanation_status"] == full["explanation_status"]
    assert len(json.dumps(full["reasoning_log"], ensure_ascii=False)) > 10_000      # 큰 열은 실제로 크다


def test_snapshot_is_read_from_the_database_once_per_run(monkeypatch):
    client = _signed_up()
    lid, rev, _data = _recommended_list(client)
    snap.clear_snapshot_cache()
    calls = {"n": 0}
    original = EngineRepo.get_run_snapshot_steps

    def counting(self, run_id):
        calls["n"] += 1
        return original(self, run_id)

    monkeypatch.setattr(EngineRepo, "get_run_snapshot_steps", counting)
    for _ in range(5):
        assert client.get(f"/session/{lid}/result").status_code == 200
    assert calls["n"] == 1, calls


def test_the_trace_is_only_read_once_the_explanation_is_finished(monkeypatch):
    """설명 대기 중(pending) 폴링에서는 추적 기록을 읽지 않는다 — 읽어도 비어 있다."""
    client = _signed_up()
    lid, rev, _data = _recommended_list(client)
    calls = {"n": 0}
    original = EngineRepo.get_run_trace

    def counting(self, run_id):
        calls["n"] += 1
        return original(self, run_id)

    monkeypatch.setattr(EngineRepo, "get_run_trace", counting)
    body = client.get(f"/session/{lid}/result").json()
    assert body["explanation"]["status"] in ("ready", "failed")
    assert calls["n"] == 1
    assert any(step.get("step") == "기여도" or step.get("step") for step in body["reasoning_log"])
