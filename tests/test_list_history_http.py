"""견적 리스트 히스토리(C1) — GET /lists/{id}/history 와 부품 교체 기록(item_replaced payload·seq).

일회용 DB 가 필요하다(tests/conftest.py 가 자동으로 만든다). 테스트 환경은 MOCK_MODE 라 요약은 규칙 문장이고,
LLM 경로는 call_llm 을 바꿔 끼워 검사한다."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"hist-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "히스토리", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _recommended_list(c) -> tuple[str, str, dict]:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "게임용 PC 맞추고 싶어요"})
    assert r.status_code == 200, r.text
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", 5_000_000), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    state = r.json()
    assert state["can_recommend"] is True, state
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return lid, state["revision_id"], data


def _swap_to_cheapest_other(c, lid: str, item_id: str) -> str:
    alts = c.get(f"/session/{lid}/items/{item_id}/alternatives").json()["items"]
    alt = next(a for a in alts if not a["current"])
    r = c.post(f"/session/{lid}/items/{item_id}/swap", json={"candidate_id": alt["candidate_id"]})
    assert r.status_code == 200, r.text
    return alt["product"]["name"]


def test_history_tells_the_journey_of_a_confirmed_list(raw_conn):
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    r = c.post(f"/session/{lid}/result-message", json={"text": "그래픽카드는 왜 이걸로 골랐어요?"})
    assert r.status_code == 200, r.text

    item = next(it for it in data["items"] if it["alternatives_count"] > 1)
    first_name = item["product"]["name"]
    second_name = _swap_to_cheapest_other(c, lid, item["item_id"])
    third_name = _swap_to_cheapest_other(c, lid, item["item_id"])   # 같은 품목을 두 번째로 바꾼다

    # 두 번째 교체도 남고(seq), 무엇→무엇이 payload 에 있다
    rows = raw_conn.execute(
        "SELECT payload FROM engine.feedback_event WHERE revision_id=%s AND event_type='item_replaced' ORDER BY occurred_at",
        (revision_id,),
    ).fetchall()
    assert len(rows) == 2
    assert all(p["item_id"] == item["item_id"] and p["from_variant_id"] and p["to_variant_id"] for (p,) in rows)
    assert rows[0][0]["to_variant_id"] == rows[1][0]["from_variant_id"]

    r = c.post(f"/lists/{lid}/confirm", json={"name": "히스토리 테스트"})
    assert r.status_code == 200, r.text

    r = c.get(f"/lists/{lid}/history")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = [e["kind"] for e in body["events"]]
    assert kinds[0] == "condition" and kinds[-1] == "confirm"
    assert kinds.index("recommend") < kinds.index("question") < kinds.index("swap")
    assert kinds.count("swap") == 2
    swaps = [e["text"] for e in body["events"] if e["kind"] == "swap"]
    assert first_name in swaps[0] and second_name in swaps[0]
    assert second_name in swaps[1] and third_name in swaps[1]
    assert body["events"][0]["text"] == "게임용 PC 맞추고 싶어요"

    summary = body["summary"]
    assert summary["status"] == "ready"
    assert "게임용 PC 맞추고 싶어요" in summary["text"] and "확정했어요" in summary["text"]


def test_history_is_only_for_the_owner_of_a_confirmed_list():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.get(f"/lists/{lid}/history").status_code == 404        # 아직 확정 전

    assert owner.post(f"/lists/{lid}/confirm", json={"name": "소유 확인"}).status_code == 200
    assert owner.get(f"/lists/{lid}/history").status_code == 200
    assert _signed_up().get(f"/lists/{lid}/history").status_code == 404  # 남의 목록
    assert TestClient(app).get(f"/lists/{lid}/history").status_code == 401  # 로그인 전


def _events() -> list[dict]:
    at = datetime(2026, 9, 30, tzinfo=timezone.utc)
    return [
        {"at": at, "kind": "condition", "text": "조용한 게임용 PC"},
        {"at": at, "kind": "recommend", "text": "추천 구성을 받았어요."},
        {"at": at, "kind": "swap", "text": "GPU를 RX 7600에서 RTX 3050으로 바꿨어요."},
        {"at": at, "kind": "confirm", "text": "1,480,000원으로 확정했어요."},
    ]


def test_particles_follow_how_the_last_letter_is_read():
    from src.services.list_history import _eul, _euro, _user_text

    assert [_eul(w) for w in ("CPU", "RAM", "메인보드", "저장장치", "케이스", "파워")] == \
        ["CPU를", "RAM을", "메인보드를", "저장장치를", "케이스를", "파워를"]
    assert [_euro(w) for w in ("RTX 3050", "RX 7600", "Ryzen 5 7600X", "RTX 4070 SUPER", "970 EVO Plus", "쿨러")] == \
        ["RTX 3050으로", "RX 7600으로", "Ryzen 5 7600X로", "RTX 4070 SUPER로", "970 EVO Plus로", "쿨러로"]
    assert _user_text("5000000") == "5,000,000원" and _user_text("게임") == "게임"


def test_llm_summary_is_used_only_when_it_invents_no_numbers(monkeypatch):
    from src.clients import llm_client
    from src.services import list_history

    reply = {"text": "조용한 게임용 PC를 찾다가 GPU를 RTX 3050으로 바꾸고 1,480,000원에 확정하셨어요."}
    monkeypatch.setattr(llm_client, "call_llm", lambda *a, **k: reply)
    assert list_history.llm_summary(_events()) == reply["text"]

    reply = {"text": "GPU를 바꿔 20만 원을 아끼고 1,480,000원에 확정하셨어요."}   # 20은 기록에 없다
    assert list_history.llm_summary(_events()) is None


def test_summary_falls_back_to_rules_when_llm_fails(monkeypatch):
    from src.clients import llm_client
    from src.services import list_history

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(list_history, "llm_available", lambda: True)
    monkeypatch.setattr(llm_client, "call_llm", boom)
    revision = {"confirmed_at": datetime(2026, 9, 30, tzinfo=timezone.utc)}
    text = list_history.summarize(uuid4(), revision, _events())
    assert "조용한 게임용 PC" in text and "RTX 3050" in text and "1,480,000원으로 확정했어요" in text
