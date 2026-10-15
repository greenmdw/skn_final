"""같은 목록의 조건 대화 턴은 한 번에 하나 — 10/15 QA #55 (연달아 보내면 답·칩이 옛 상태 기준).

앞 턴이 진행 중인 상황을 다른 연결이 같은 advisory 잠금을 쥐는 것으로 흉내 낸다. 일회용 테스트 DB 가 필요하다.
동시에 보낸 메시지가 모두 순서대로 처리되는지는 test_scenario_concurrency_security 의 연타 테스트가 본다."""
from __future__ import annotations

import os
import threading
import time

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app
    from src.auth import ratelimit
    from src.services import session_service


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch):
    from src.agent import conditions_agent
    monkeypatch.setattr(conditions_agent, "available", lambda: False)          # 규칙 경로 — 모델 없음
    ratelimit.reset_all()
    yield


def _session(c) -> str:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    return lid


def _hold(other, lid: str) -> None:
    other.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"condition-turn:{lid}",))


def test_a_turn_sent_while_another_is_running_waits_and_then_reads_the_newer_state():
    c = TestClient(app)
    lid = _session(c)
    c.post(f"/session/{lid}/answer", json={"question_id": "q_purpose", "selected": ["게임"]})
    out: dict = {}
    with psycopg.connect(DSN, autocommit=False) as other:                    # 앞 턴이 진행 중
        _hold(other, lid)
        t = threading.Thread(target=lambda: out.update(r=c.post(f"/session/{lid}/message", json={"text": "100"})))
        t.start()
        time.sleep(0.5)
        assert t.is_alive()                                                  # 앞 턴이 끝나길 기다린다
        other.rollback()
    t.join(timeout=30)
    assert out["r"].status_code == 200, out["r"].text
    fields = {f["key"]: f["value"] for f in out["r"].json()["fields"]}
    assert fields["budget_max"] == 1_000_000                                 # 예산 차례라는 걸 읽고 처리했다


def test_waiting_too_long_is_refused_and_leaves_the_conversation_unchanged(monkeypatch):
    monkeypatch.setattr(session_service, "_TURN_WAIT_SECONDS", 0.3)
    c = TestClient(app)
    lid = _session(c)
    before = c.get(f"/session/{lid}").json()["messages"]
    with psycopg.connect(DSN, autocommit=False) as other:
        _hold(other, lid)
        r = c.post(f"/session/{lid}/message", json={"text": "게임용 150만원"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "turn_in_progress", r.text
        r = c.post(f"/session/{lid}/answer", json={"question_id": "q_purpose", "selected": ["게임"]})
        assert r.status_code == 409, r.text
        other.rollback()
    assert c.get(f"/session/{lid}").json()["messages"] == before             # 거절한 말은 대화에 남지 않는다


def test_turns_on_different_lists_do_not_wait_for_each_other():
    c = TestClient(app)
    busy, free = _session(c), _session(c)
    with psycopg.connect(DSN, autocommit=False) as other:
        _hold(other, busy)
        assert c.post(f"/session/{free}/message", json={"text": "게임용 150만원"}).status_code == 200
        other.rollback()
