"""견적 점검 되묻기 채팅 (CHAT-04) + 대화 이력 저장 (CHAT-08).

저장된 비교 분석 결과만 근거로 답하는지, 대안 조회가 호환·가격 차이를 함께 내는지, 에이전트 실패 시 규칙 경로로 내려가는지,
숫자 가드가 근거 밖 숫자를 막는지, 대화가 저장·복원되고 소유자만 읽는지를 본다. 합성 카탈로그로 DB 없이(앞 절) / 일회용 DB(뒤 절).
"""
from __future__ import annotations

import os

import pytest

from src.agent import quote_review_agent
from src.engine.stage3_0_candidates import load_pc_catalog
from src.services import quote_alternatives, quote_chat_service as chat, quote_facts
from src.services import quote_review_service as qrs

QUOTE = {"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원", "메인보드": "MSI PRO B450M 100,000원", "RAM": "DDR5 16GB 60,000원"}
COND = {"purpose": "game", "resolution": "QHD_165", "budget_max": 2_000_000}


@pytest.fixture(autouse=True)
def _synthetic_catalog(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")


@pytest.fixture()
def review() -> dict:
    return qrs.analyze(QUOTE, COND)


def loader():
    pool = load_pc_catalog(lambda _m: None)
    return lambda: pool


# ── 질문 → 어떤 사실을 읽을지 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,first", [
    ("이 견적 호환은 문제없어?", "compat"),
    ("소켓이 맞아?", "compat"),
    ("가격이 비싼 편이야?", "prices"),
    ("우리 추천이랑 뭐가 달라?", "compare"),
    ("성능이 부족하지 않아?", "balance"),
    ("그래픽카드 더 저렴한 걸로 뭐가 있어?", "alternatives"),
    ("CPU 대신 쓸 만한 거 추천해줘", "alternatives"),
    ("안녕", "overview"),
])
def test_the_question_picks_the_matching_fact(text, first):
    assert chat.route(text)[0][0] == first


def test_a_compat_question_about_power_targets_the_power_check():
    assert chat.route("파워 전력은 충분해?")[0] == ("compat", {"axis": "power"})


def test_the_direction_words_in_an_alternatives_request_are_kept():
    assert chat.route("그래픽카드 더 저렴한 걸로 바꿀 수 있어?")[0] == ("alternatives", {"slot": "GPU", "direction": "cheaper"})
    assert chat.route("CPU 더 좋은 걸로 교체하고 싶어")[0] == ("alternatives", {"slot": "CPU", "direction": "better"})


def test_a_part_only_question_shows_the_comparison_with_our_recommendation():
    assert chat.route("GPU는 어때?")[0] == ("compare", {"part": "GPU"})


# ── 근거 문장은 저장된 값만 옮긴다 ─────────────────────────────────────────────────────

def test_compat_facts_separate_confirmed_incompatibility_from_unknown(review):
    text = quote_facts.compat(review)
    assert "확정된 비호환" in text and "확인 못 함" in text
    assert text.index("확정된 비호환") < text.index("확인 못 함")               # 문제부터
    assert "소켓" in quote_facts.compat(review, "socket")


def test_price_and_balance_and_compare_facts_carry_the_stored_numbers(review):
    assert "250,000원" in quote_facts.prices(review, "CPU")
    assert "기준" in quote_facts.balance(review)
    assert "우리 추천" in quote_facts.compare(review, "GPU")


def test_missing_blocks_explain_why_instead_of_inventing(review):
    bare = qrs.analyze({"GPU": "RTX 4060 Ti"}, None)                      # 조건·가격 없음
    assert "가격이 적혀 있지 않아" in quote_facts.prices(bare)
    assert "용도" in quote_facts.balance(bare)
    assert "용도" in quote_facts.compare(bare) or "예산" in quote_facts.compare(bare)


# ── 대안 조회 ─────────────────────────────────────────────────────────────────────────

def test_alternatives_list_other_products_with_price_delta_and_compat(review):
    result = quote_alternatives.alternatives(review, "GPU", loader()(), "cheaper")
    assert result["baseline"]["price"] == 500_000
    assert result["candidates"] and all(c["price"] < 500_000 and c["price_delta"] < 0 for c in result["candidates"])
    assert all(c["name"] != result["baseline"]["name"] for c in result["candidates"])


def test_alternatives_flag_a_new_confirmed_incompatibility_with_the_rest_of_the_quote(review):
    """AM4 보드(B450M)가 견적에 있는데 AM5 CPU 후보는 새 비호환을 만든다 — 숨기지 않고 이유와 함께 보인다."""
    result = quote_alternatives.alternatives(review, "CPU", loader()(), None, limit=40)
    by_name = {c["name"]: c for c in result["candidates"]}
    am5 = next(c for n, c in by_name.items() if "7600" in n or "9600" in n or "7700" in n)
    assert "socket" in am5["incompatible"] or am5["incompatible"] == []          # 소켓 정보에 따라 — 아래 정렬 규칙이 핵심
    ordered = [bool(c["incompatible"]) for c in result["candidates"]]
    assert ordered == sorted(ordered)                                            # 비호환 없는 후보가 먼저


def test_alternatives_never_change_the_stored_review(review):
    before = qrs.analyze(QUOTE, COND)
    quote_alternatives.alternatives(review, "GPU", loader()(), "cheaper")
    assert review["input"] == before["input"] and review["compat"] == before["compat"]


def test_an_unknown_part_group_is_reported(review):
    assert "부품군이 아닙니다" in quote_alternatives.alternatives(review, "모니터", loader()())["error"]


# ── 규칙 경로 ─────────────────────────────────────────────────────────────────────────

def test_the_rule_reply_returns_the_matching_facts_with_their_evidence_label(review):
    reply, evidence = chat.rule_reply(review, "호환 문제 있어?", loader())
    assert evidence == ["호환 검사"] and "[호환 검사]" in reply and "확정된 비호환" in reply


def test_the_rule_reply_for_an_alternatives_question_lists_candidates(review):
    reply, evidence = chat.rule_reply(review, "그래픽카드 더 저렴한 걸로 뭐가 있어?", loader())
    assert evidence == ["대안 조회"] and "GPU 현재:" in reply and "1." in reply


def test_an_unclear_question_gets_the_overview_and_a_hint(review):
    reply, evidence = chat.rule_reply(review, "음..", loader())
    assert evidence == ["견적 분석 요약"] and "부품을 골라 대안을" in reply


# ── 숫자·평가어 가드 ───────────────────────────────────────────────────────────────────

def test_the_guard_accepts_numbers_that_came_from_the_inputs():
    ok, outside, bad = quote_review_agent.reply_is_grounded("GPU 가격은 견적 500,000원이에요.", ["견적 500,000원 · 카탈로그 654,210원"])
    assert ok and not outside and not bad


def test_the_guard_rejects_invented_numbers_and_verdicts():
    ok, outside, _ = quote_review_agent.reply_is_grounded("GPU가 45만원이면 충분해요. 성능은 30% 더 좋아요.", ["견적 500,000원"])
    assert not ok and {"45", "30"} <= outside
    ok, _, bad = quote_review_agent.reply_is_grounded("이 견적은 사도 됩니다.", [])
    assert not ok and bad == ["사도 됩니다"]


# ── 에이전트 경로 ─────────────────────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
db_only = pytest.mark.skipif(not DSN, reason="requires disposable test database")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as c:
        yield c


def _created(client) -> str:
    return client.post("/pc/reviews", json={"current_specs": QUOTE, "conditions": COND}).json()["list_id"]


@db_only
def test_the_agent_path_is_used_when_available_and_falls_back_to_rules_on_failure(client, monkeypatch):
    list_id = _created(client)
    monkeypatch.setattr(quote_review_agent, "available", lambda: True)
    monkeypatch.setattr(quote_review_agent, "run_turn", lambda *a, **k: quote_review_agent.TurnResult("에이전트 답", ["호환 검사"], []))
    res = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환 괜찮아?"}).json()
    assert res["via"] == "agent" and res["reply"] == "에이전트 답" and res["evidence"] == ["호환 검사"]

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(quote_review_agent, "run_turn", boom)
    res = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환 괜찮아?"}).json()
    assert res["via"] == "rules" and "[호환 검사]" in res["reply"]


# ── 저장·복원·소유자 (HTTP, 일회용 DB) ───────────────────────────────────────────────

@db_only
def test_the_conversation_is_saved_in_order_and_restored(client):
    list_id = _created(client)
    assert client.get(f"/pc/reviews/{list_id}/messages").json() == {"messages": []}
    first = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "가격이 비싼 편이야?"}).json()
    assert first["via"] == "rules" and first["evidence"] == ["가격 비교"]
    client.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환은?"})
    got = client.get(f"/pc/reviews/{list_id}/messages").json()["messages"]
    assert [m["role"] for m in got] == ["user", "assistant", "user", "assistant"]
    assert got[0]["text"] == "가격이 비싼 편이야?" and got[1]["text"] == first["reply"]


@db_only
def test_asking_does_not_change_the_saved_review_or_the_recommendation_inputs(client):
    list_id = _created(client)
    before = client.get(f"/pc/reviews/{list_id}").json()
    client.post(f"/pc/reviews/{list_id}/messages", json={"text": "그래픽카드 더 저렴한 걸로 뭐가 있어?"})
    assert client.get(f"/pc/reviews/{list_id}").json() == before


@db_only
def test_only_the_owner_can_ask_or_read_the_conversation(client):
    from fastapi.testclient import TestClient
    from src.api import app

    list_id = _created(client)
    with TestClient(app) as stranger:
        assert stranger.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환은?"}).status_code == 404
        assert stranger.get(f"/pc/reviews/{list_id}/messages").status_code == 404


@db_only
def test_bad_input_and_a_list_without_a_review_are_rejected(client):
    list_id = _created(client)
    assert client.post(f"/pc/reviews/{list_id}/messages", json={"text": ""}).status_code == 422
    assert client.post(f"/pc/reviews/{list_id}/messages", json={"text": "가" * 1001}).status_code == 422
    empty = client.post("/session").json()["list_id"]
    assert client.post(f"/pc/reviews/{empty}/messages", json={"text": "호환은?"}).status_code == 404


@db_only
def test_a_reedited_review_keeps_the_same_conversation(client):
    list_id = _created(client)
    client.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환은?"})
    client.put(f"/pc/reviews/{list_id}", json={"current_specs": {"CPU": "라이젠 5 7600 250,000원"}})
    assert len(client.get(f"/pc/reviews/{list_id}/messages").json()["messages"]) == 2


# ── 부품별 가격 서술 가드 (2026-09-27 실측 결함) ─────────────────────────────────────────

def test_price_claims_guard_catches_a_state_attached_to_the_wrong_part(review):
    from src.agent.quote_review_agent import price_claims_are_grounded
    # 메인보드는 no_catalog(비교 안 함)인데 "비쌌다"고 잘못 붙인 문장 — 진짜 숫자만 쓰였어도 잡아야 한다.
    bad = "GPU는 견적이 비쌌습니다. 메인보드도 비쌌습니다. RAM은 더 쌌습니다."
    assert price_claims_are_grounded(bad, review) is False


def test_price_claims_guard_accepts_a_correct_single_part_claim(review):
    from src.agent.quote_review_agent import price_claims_are_grounded
    assert price_claims_are_grounded("GPU는 견적이 더 저렴했습니다.", review) is True
    assert price_claims_are_grounded("메인보드는 카탈로그에서 찾지 못해 비교하지 못했습니다.", review) is True


def test_price_claims_guard_skips_a_clause_with_no_direction_word(review):
    from src.agent.quote_review_agent import price_claims_are_grounded
    assert price_claims_are_grounded("CPU와 GPU는 가격을 비교했습니다.", review) is True


def _prices_review(states: dict[str, str]) -> dict:
    return {"prices": {"rows": [{"part": part, "state": state} for part, state in states.items()]}}


def test_price_claims_guard_applies_a_joint_claim_to_every_part_named_in_the_clause():
    """"A와 B는 X" 는 한국어 문법상 A·B 둘 다 X 라는 뜻이다 — 절 하나에 부품이 여럿이어도 방향이 하나면
    전부 검사한다(2026-09-28 실측 결함: "CPU와 RAM은 견적이 비싸고"에서 RAM은 실제 cheaper인데 놓쳤다)."""
    from src.agent.quote_review_agent import price_claims_are_grounded

    review = _prices_review({"CPU": "pricier", "RAM": "cheaper", "저장장치": "cheaper"})
    bad = "CPU와 RAM은 견적이 비싸고, 저장장치는 견적이 더 쌉니다."
    assert price_claims_are_grounded(bad, review) is False

    good = "CPU와 파워는 견적이 비싸고, RAM과 저장장치는 견적이 더 쌉니다."
    review2 = _prices_review({"CPU": "pricier", "파워": "pricier", "RAM": "cheaper", "저장장치": "cheaper"})
    assert price_claims_are_grounded(good, review2) is True


def test_price_claims_guard_skips_a_clause_whose_direction_is_ambiguous():
    """한 절에 비쌈·쌈 방향어가 둘 다 있으면 어느 부품에 어느 방향이 붙는지 코드가 못 가른다 — 건너뛴다."""
    from src.agent.quote_review_agent import price_claims_are_grounded

    review = _prices_review({"CPU": "cheaper", "GPU": "pricier"})
    assert price_claims_are_grounded("CPU는 비싸고 GPU는 저렴합니다", review) is True
