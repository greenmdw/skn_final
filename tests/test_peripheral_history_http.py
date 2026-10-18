"""주변기기 채팅 기록 (`GET /session/{id}/peripherals/messages`, QA 10/15 #19·#30·#47, 10/16 #17).

채팅 한 턴과 추천을 그 목록의 대화에 남기고, 돌아왔을 때 채팅·마지막 조건·추천을 받았는지를 되살린다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import peripheral_intent_agent
    from src.api import app
    from src.services import peripheral_interpret_service


@pytest.fixture(autouse=True)
def _words_only(monkeypatch):
    """언어 모델 없이 단어 규칙으로 돈다(로컬 .env 에 키가 있어도 결과가 같게)."""
    monkeypatch.setattr(peripheral_intent_agent, "available", lambda: False)
    peripheral_interpret_service.clear_cache()


def _client() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"phist-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "기록", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _session(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _chat(c, lid, text, previous=None, kinds=None):
    r = c.post(f"/session/{lid}/peripherals/chat", json={"text": text, "previous": previous, "kinds": kinds})
    assert r.status_code == 200, r.text
    return r.json()


def _recommend(c, lid, interp, **override):
    body = {"kinds": interp["kinds"], "budget_max": interp["budget_total"], "purposes": interp["purposes"],
            "situations": interp["situations"], "stated": interp["stated"], "kind_budget": interp["budget"],
            "kind_budget_min": interp["budget_min"], "emphasis": interp["emphasis"], "brand_like": interp["brand_like"],
            "brand_avoid": interp["brand_avoid"], "exclude": interp["exclude"], "hand_size": interp["hand_size"], **override}
    r = c.post(f"/session/{lid}/peripherals/recommend", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _history(c, lid) -> dict:
    r = c.get(f"/session/{lid}/peripherals/messages")
    assert r.status_code == 200, r.text
    return r.json()


def test_turns_are_stored_in_order_with_the_last_interpretation():
    c = _client()
    lid = _session(c)
    assert _history(c, lid)["messages"] == []
    first = _chat(c, lid, "가벼운 무선 마우스 5만원")
    second = _chat(c, lid, "조용한 키보드도", previous=first["interpretation"])
    out = _history(c, lid)
    assert [(m["role"], m["text"]) for m in out["messages"]] == [
        ("user", "가벼운 무선 마우스 5만원"), ("assistant", first["turn"]["reply"]),
        ("user", "조용한 키보드도"), ("assistant", second["turn"]["reply"]),
    ]
    assert out["interpretation"] == second["interpretation"] and out["resolved"] == second["resolved"]
    assert out["showing_results"] is False


def test_question_only_turn_keeps_the_previous_interpretation():
    """화면과 같은 규칙 — 조건을 바꾸지 않은 질문의 해석은 받아들이지 않는다(질문이 품목을 줄이지 않게)."""
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "마우스랑 스피커 가벼운 무선으로")
    _chat(c, lid, "모니터는 어떤 조건으로 나눌 수 있어?", previous=first["interpretation"])
    out = _history(c, lid)
    assert len(out["messages"]) == 4 and out["interpretation"] == first["interpretation"]


def test_recommend_input_is_the_state_after_it_and_notices_are_said_once():
    """칩을 지우고 추천만 다시 받은 것(채팅 없음)도 돌아왔을 때의 조건이 된다."""
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "가벼운 무선 마우스랑 QHD 모니터")
    rec = _recommend(c, lid, first["interpretation"])
    _recommend(c, lid, first["interpretation"], stated={"monitor": first["interpretation"]["stated"]["monitor"]})
    out = _history(c, lid)
    assert out["showing_results"] is True
    assert "mouse" not in out["interpretation"]["stated"] and out["interpretation"]["stated"]["monitor"]
    assert out["interpretation"]["kinds"] == first["interpretation"]["kinds"]
    notices = [n["text"] for n in rec["notices"]]
    assert notices and out["notices"] == notices        # PC 견적 없이 고른 모니터 안내
    assert [m["text"] for m in out["messages"]].count(notices[0]) == 1


def test_reset_returns_to_the_first_screen():
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "무선 마우스 5만원")
    _recommend(c, lid, first["interpretation"])
    _chat(c, lid, "처음부터 다시", previous=first["interpretation"])
    out = _history(c, lid)
    assert out["showing_results"] is False and out["interpretation"]["stated"] == {} and out["interpretation"]["kinds"] == ["mouse"]


def test_lists_mark_peripheral_conversations_and_pc_messages_skip_the_record_rows():
    c = _client()
    pc_list, peripheral_list = _session(c), _session(c)
    first = _chat(c, peripheral_list, "무선 마우스")
    _recommend(c, peripheral_list, first["interpretation"])
    items = {item["list_id"]: item for item in c.get("/lists").json()["items"]}
    assert items[peripheral_list]["chat"] == "peripheral" and items[peripheral_list]["first_message"] == "무선 마우스"
    assert items[pc_list]["chat"] == "computer"
    state = c.get(f"/session/{peripheral_list}").json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]     # 추천 기록(빈 system 행)은 대화가 아니다


def test_someone_else_cannot_read_the_record():
    owner, other = _client(), _client()
    lid = _session(owner)
    _chat(owner, lid, "무선 마우스")
    assert other.get(f"/session/{lid}/peripherals/messages").status_code == 404


def test_confirmed_peripheral_report_history_does_not_read_the_peripheral_chat_as_pc_requests():
    """본체 여정(리포트 히스토리)은 본체 대화만 읽는다 — "다른 걸로 바꿔줘"가 "바뀐 것 없음" 요청으로 잡히지 않는다."""
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "무선 마우스")
    _chat(c, lid, "다른 걸로 바꿔줘", previous=first["interpretation"])
    rec = _recommend(c, lid, first["interpretation"])
    mouse = next(item for item in rec["items"] if item["kind"] == "mouse")
    r = c.post(f"/lists/{lid}/confirm", json={
        "name": "마우스만", "peripherals": [{"kind": "mouse", "variant_id": mouse["product"]["variant_id"], "qty": 1}]})
    assert r.status_code == 200, r.text
    history = c.get(f"/lists/{lid}/history").json()
    assert [e["kind"] for e in history["events"]] == ["confirm"]
    assert not any(step.get("quote") for step in history["steps"])
