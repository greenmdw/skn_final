"""주변기기 채팅 한 턴 API (`POST /session/{id}/peripherals/chat`, QA PQA-012·013·014).

해석과 질문 답변이 한 번의 호출로 오고, 결과가 필요한 질문은 같은 입력의 추천(`/peripherals/recommend`)과 같은 결과로
답하는지 확인한다. 일회용 DB 가 필요하다."""
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
        "email": f"pchat-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "채팅", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _session(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _chat(c, lid, text, previous=None, kinds=None, **extra):
    r = c.post(f"/session/{lid}/peripherals/chat", json={"text": text, "previous": previous, "kinds": kinds, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_condition_turn_returns_interpretation_and_server_reply():
    c = _client()
    out = _chat(c, _session(c), "마우스 가벼운 무선으로 5만원 이하")
    assert out["interpretation"]["kinds"] == ["mouse"] and out["source"] == "rules"
    turn = out["turn"]
    assert {i["label"] for i in turn["new_conditions"]} >= {"무선", "가벼운 무게", "마우스 예산 50,000원"}
    assert turn["reply"].startswith("이번에 반영했어요:") and turn["answer"] is None
    assert turn["result_chips"]


def test_question_does_not_change_conditions_nor_repeat_them():
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "마우스랑 스피커 가벼운 무선으로")
    second = _chat(c, lid, "스피커는 어떤 조건으로 나눌 수 있어?", previous=first["interpretation"])
    assert second["interpretation"]["stated"] == first["interpretation"]["stated"]
    assert second["turn"]["new_conditions"] == []
    assert "무선 · 가벼운 무게" not in second["turn"]["reply"]
    assert second["turn"]["answer"]["type"] == "conditions" and second["turn"]["answer"]["kinds"] == ["speaker"]


def test_result_question_is_answered_with_the_same_result_as_recommend():
    """왜 골랐어?에 나온 제품이 같은 조건의 추천 1위와 같다 — 화면에 보이는 결과와 다른 제품으로 답하지 않는다."""
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "마우스 가벼운 무선 5만원 이하")
    interp = first["interpretation"]
    rec = c.post(f"/session/{lid}/peripherals/recommend", json={
        "kinds": interp["kinds"], "purposes": interp["purposes"], "situations": interp["situations"],
        "stated": interp["stated"], "kind_budget": interp["budget"],
    })
    assert rec.status_code == 200, rec.text
    top = rec.json()["items"][0]["product"]["name"]

    asked = _chat(c, lid, "왜 이걸 1위로 골랐어?", previous=interp)
    assert asked["turn"]["answer"]["type"] == "why" and top in asked["turn"]["answer"]["text"]
    assert asked["turn"]["new_conditions"] == [] and asked["interpretation"]["stated"] == interp["stated"]


def test_compare_and_spec_questions_use_recommendation_data():
    c = _client()
    lid = _session(c)
    first = _chat(c, lid, "마우스 추천해줘")
    compare = _chat(c, lid, "1위랑 2위 차이가 뭐야?", previous=first["interpretation"])
    assert compare["turn"]["answer"]["type"] == "compare" and "2위" in compare["turn"]["answer"]["text"]
    spec = _chat(c, lid, "이 마우스 무게 어때?", previous=first["interpretation"])
    assert spec["turn"]["answer"]["type"] == "spec" and "무게:" in spec["turn"]["answer"]["text"]


def test_kinds_card_value_keeps_the_question():
    """종류 카드로 고른 값(kinds)을 함께 보내도 이번 문장의 질문이 사라지지 않는다."""
    c = _client()
    out = _chat(c, _session(c), "왜 이걸 1위로 골랐어?", kinds=["keyboard"])
    assert out["interpretation"]["question"]["type"] == "why" and out["turn"]["answer"]["kinds"] == ["keyboard"]


def test_compat_question_needs_a_pc_quote_and_says_so():
    c = _client()
    out = _chat(c, _session(c), "내 컴퓨터에 이 모니터 맞아?", kinds=["monitor"])
    assert out["turn"]["answer"]["type"] == "compat" and "PC 견적" in out["turn"]["answer"]["text"]


def test_monitor_without_pc_is_not_filtered_and_chat_answer_still_works():
    c = _client()
    out = _chat(c, _session(c), "모니터 스펙이 어떻게 돼?", kinds=["monitor"])
    answer = out["turn"]["answer"]
    assert answer["type"] == "spec" and answer["kinds"] == ["monitor"] and "·" in answer["text"]


def test_unowned_session_is_not_found():
    c = _client()
    r = c.post(f"/session/{uuid4()}/peripherals/chat", json={"text": "마우스 추천"})
    assert r.status_code == 404, r.text


def test_empty_text_is_rejected():
    c = _client()
    r = c.post(f"/session/{_session(c)}/peripherals/chat", json={"text": ""})
    assert r.status_code == 422
