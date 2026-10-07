"""챗봇 말투 변형 — 실제 LLM 으로 (2026-10-07). 전부 `llm_live` 마커: 기본 실행에서 빠지고, 비용이 든다.

  MOCK_MODE=0 PYTHONPATH=. TRUEFIT_REQUIRE_TEST_DB=1 uv run pytest -q -m llm_live tests/test_chat_llm_live.py

규칙 코드로 풀리는 부분(동의 판정, 금액 정정, 부품군 인식, 제품 이름 매칭)은 tests/test_phrasing_variants.py 가 LLM 없이 본다.
여기서는 **모델이 도구를 제대로 불러 상태를 바꾸는지**를 본다 — 같은 뜻을 여러 말투로 해도 조건·구성이 같게 바뀌는가, 검색 동의 흐름이
모델이 끼어도 끊기지 않는가. 모델은 비결정적이므로 한 번 통과가 보장은 아니다(§2.5) — 흔들리면 변형을 늘려 비율로 본다.
"""
from __future__ import annotations

import os

import pytest

from src import config as cfg

DSN = os.getenv("DATABASE_URL")
_KEY = bool(cfg.OPENAI_API_KEY) and cfg.LLM_PROVIDER == "openai"
pytestmark = [
    pytest.mark.llm_live, pytest.mark.db,
    pytest.mark.skipif(not DSN, reason="일회용 DB 필요"),
    pytest.mark.skipif(not _KEY, reason="OPENAI_API_KEY/LLM_PROVIDER 미설정 — 실호출 불가"),
]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import conditions_agent, quote_review_agent, result_agent
    from src.api import app
    from src.auth import ratelimit
    from src.clients import llm_client
    from src.services import live_spec_lookup
    from tests.test_list_history_http import _recommended_list, _signed_up

MARKER = "외부 검색을 진행해도 될까요?"


@pytest.fixture()
def live(monkeypatch):
    """이 테스트 동안만 세 챗봇과 실시간 검색을 실제 모델로 켠다(끝나면 monkeypatch 가 되돌린다). 검색 호출 횟수를 센다."""
    for module in (conditions_agent, result_agent, quote_review_agent, live_spec_lookup, llm_client):
        monkeypatch.setattr(module, "MOCK_MODE", False)
    monkeypatch.setattr(conditions_agent, "CONDITIONS_AGENT", True)
    monkeypatch.setattr(result_agent, "RESULT_AGENT", True)
    monkeypatch.setattr(quote_review_agent, "QUOTE_REVIEW_AGENT", True)
    monkeypatch.setattr(live_spec_lookup, "LIVE_PART_LOOKUP", True)
    calls: list[str] = []
    original = live_spec_lookup.lookup

    def counted(conn, text, **kw):
        calls.append(text)
        return original(conn, text, **kw)

    monkeypatch.setattr(live_spec_lookup, "lookup", counted)
    ratelimit.reset_all()
    yield calls
    ratelimit.reset_all()


def _fields(state: dict) -> dict:
    return {f["key"]: f.get("value") for f in state["fields"]}


def _say(client, sid, text) -> dict:
    r = client.post(f"/session/{sid}/message", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def _reply(state: dict) -> str:
    messages = state.get("messages") or []
    return messages[-1]["text"] if messages else ""


def _new_conditions(client, text="150만원으로 엘든링 돌릴 PC 맞춰줘, 가성비 위주로") -> str:
    sid = client.post("/session").json()["list_id"]
    client.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    _say(client, sid, text)
    return sid


# ── 조건 대화: 같은 뜻의 다른 말투 ───────────────────────────────────────────────────────────────

PRIORITY_TO_PERFORMANCE = ["우선순위 성능으로 바꿔줘", "가성비 말고 성능 위주로 해줘", "성능이 제일 중요해졌어", "성능 우선으로 갈게",
                           "이제 성능 위주로 추천해줘"]


def test_every_phrasing_of_a_priority_change_changes_the_priority(live):
    client = TestClient(app)
    sid = _new_conditions(client)
    wrong = []
    for phrase in PRIORITY_TO_PERFORMANCE:
        _say(client, sid, "다시 가성비 위주로 해줘")
        state = _say(client, sid, phrase)
        if _fields(state).get("priority") != "performance":
            wrong.append((phrase, _fields(state).get("priority"), _reply(state)[:80]))
    assert wrong == [], f"우선순위가 안 바뀐 말투 {len(wrong)}/{len(PRIORITY_TO_PERFORMANCE)}: {wrong}"


BUDGET_CORRECTIONS = ["예산 150이 아니라 200만원이야", "150만원 말고 200만원으로 해줘", "아 예산은 200만원으로 할게요"]


def test_every_phrasing_of_a_budget_correction_uses_the_corrected_amount(live):
    client = TestClient(app)
    wrong = []
    for phrase in BUDGET_CORRECTIONS:
        sid = _new_conditions(client)
        state = _say(client, sid, phrase)
        if _fields(state).get("budget_max") != 2_000_000:
            wrong.append((phrase, _fields(state).get("budget_max")))
    assert wrong == [], f"정정한 금액이 아닌 값이 된 말투: {wrong}"


# ── 검색 동의: 모델이 끼어도 흐름이 끊기지 않는가 ──────────────────────────────────────────────

YES = ["진행해줘", "응 찾아줘", "ㅇㅇ", "그래 검색해줘", "네 부탁해요"]
NO = ["아니 됐어", "괜찮아요 안 해도 돼", "ㄴㄴ"]


@pytest.mark.parametrize("answer", YES)
def test_conditions_chat_searches_after_any_yes_phrasing(live, answer):
    client = TestClient(app)
    sid = client.post("/session").json()["list_id"]
    client.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    asked = _say(client, sid, "게임용 180만원, RTX 6090으로 맞춰줘")
    assert MARKER in _reply(asked), _reply(asked)
    assert live == []                                           # 동의 전에는 검색하지 않는다
    done = _say(client, sid, answer)
    assert MARKER not in _reply(done), f"다시 물었다: {_reply(done)}"
    assert live, f"'{answer}' 에 검색이 실행되지 않았다: {_reply(done)}"


@pytest.mark.parametrize("answer", NO)
def test_conditions_chat_does_not_search_after_a_no(live, answer):
    client = TestClient(app)
    sid = client.post("/session").json()["list_id"]
    client.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    _say(client, sid, "게임용 180만원, RTX 6090으로 맞춰줘")
    _say(client, sid, answer)
    assert live == [], f"거절했는데 검색됨: {live}"


@pytest.mark.parametrize("answer", ["진행해줘", "응 검색해줘"])
def test_result_chat_searches_only_after_consent(live, answer):
    client = _signed_up()
    sid, _rev, _data = _recommended_list(client)
    asked = client.post(f"/session/{sid}/result-message", json={"text": "그래픽카드를 RTX 6090으로 바꿔줘"}).json()
    assert MARKER in asked["reply"], asked["reply"]
    assert live == []
    done = client.post(f"/session/{sid}/result-message", json={"text": answer}).json()
    assert MARKER not in done["reply"] and live, done["reply"]


# ── 결과 화면 대화: 조건 변경 요청 ────────────────────────────────────────────────────────────────

def test_result_chat_does_not_silently_change_conditions_or_the_build(live):
    """결과 화면 대화는 부품만 바꾼다 — "우선순위를 성능으로 바꿔줘"가 조건·구성을 몰래 바꾸면 안 된다(현재 동작 고정)."""
    client = _signed_up()
    sid, _rev, before = _recommended_list(client)
    client.post(f"/session/{sid}/result-message", json={"text": "우선순위를 성능으로 바꿔줘"})
    after = client.get(f"/session/{sid}/result").json()
    assert [i["product"]["name"] for i in after["items"]] == [i["product"]["name"] for i in before["items"]]
    assert after["conditions_summary"] == before["conditions_summary"]


@pytest.mark.xfail(reason="관찰된 이상(2026-10-07): 결과 화면 대화에서 조건 변경을 요청하면 '성능 우선으로 보면…'이라며 부품 후보만 안내하고 "
                          "조건은 안 바뀐다. 조건은 '조건 바꾸기'에서 바꾼다는 안내가 없어 반영된 것처럼 읽힌다.", strict=False)
def test_result_chat_points_to_the_conditions_screen_when_asked_to_change_a_condition(live):
    client = _signed_up()
    sid, _rev, _data = _recommended_list(client)
    reply = client.post(f"/session/{sid}/result-message", json={"text": "우선순위를 성능으로 바꿔줘"}).json()["reply"]
    assert "조건 바꾸기" in reply or "조건 화면" in reply, reply


# ── 받은 견적 점검 챗봇: 제품 비교 ───────────────────────────────────────────────────────────────

QUOTE = {"CPU": "AMD Ryzen 5 7600", "GPU": "NVIDIA GeForce RTX 4060 Ti", "메인보드": "ASRock B650 PG Lighting", "RAM": "삼성전자 DDR5-5600 (16GB)"}
COND = {"purpose": "game", "resolution": "QHD_165", "budget_max": 2_000_000}


@pytest.mark.parametrize("question,expect", [
    ("RTX 5080이랑 비교해줘", "5080"), ("엔비디아 5070 Ti 대신 쓰면 어때?", "5070"), ("라이젠 9800X3D랑 비교해줘", "9800"),
])
def test_quote_chat_answers_a_named_comparison_with_that_product(live, question, expect):
    client = TestClient(app)
    lid = client.post("/pc/reviews", json={"current_specs": QUOTE, "conditions": COND}).json()["list_id"]
    res = client.post(f"/pc/reviews/{lid}/messages", json={"text": question}).json()
    assert expect in res["reply"], res["reply"]
    assert res["evidence"] == ["부품 비교"], res["evidence"]


def test_quote_chat_asks_which_model_for_a_series_and_for_consent_for_an_unknown_product(live):
    client = TestClient(app)
    lid = client.post("/pc/reviews", json={"current_specs": QUOTE, "conditions": COND}).json()["list_id"]
    series = client.post(f"/pc/reviews/{lid}/messages", json={"text": "라이젠 9000이랑 비교해줘"}).json()
    assert "시리즈" in series["reply"] and "어느 모델" in series["reply"], series["reply"]
    ask = client.post(f"/pc/reviews/{lid}/messages", json={"text": "RTX 6090이랑 비교해줘"}).json()
    assert MARKER in ask["reply"] and live == []
    client.post(f"/pc/reviews/{lid}/messages", json={"text": "진행해줘"})
    assert live == ["RTX 6090"], live
