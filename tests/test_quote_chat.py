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


def test_compare_facts_carry_the_same_group_totals_the_note_promises(review):
    """notes 가 "같은 부품군끼리의 합계를 따로 냈다"고 하면 그 합계가 실려야 한다 — 없어서 "가격 차이 얼마나 나?"에 모델이
    "자료에 없다"고 하거나 견적 합계를 추천 전체 합계와 빼서 틀린 차이를 냈다(10/13 실측 3/3)."""
    s = review["compare"]["summary"]
    assert s["missing_in_quote"]
    text = quote_facts.compare(review)
    assert f"견적 {s['quote_total']:,}원" in text and f"우리 추천 {s['our_total_same_slots']:,}원" in text
    assert f"{s['diff']:+,}원" in text


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
    from tests.quote_review_helpers import create_review
    return create_review(client, QUOTE, COND)["list_id"]


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


def test_price_claims_guard_accepts_a_correct_single_part_claim():
    """판정은 가격 비교 행의 상태와 문장의 방향이 같은지만 본다 — 매칭 결과에 기대지 않게 상태를 직접 준다."""
    from src.agent.quote_review_agent import price_claims_are_grounded
    review = _prices_review({"GPU": "cheaper", "메인보드": "no_catalog"})
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
    assert price_claims_are_grounded("CPU가 GPU보다 비싸서 저렴한 쪽을 찾았습니다", review) is True


def test_price_claims_guard_splits_after_each_parts_own_predicate():
    """"CPU는 비슷하고 GPU는 더 저렴하며" — 부품마다 서술어가 따로면 '~고/~며' 뒤에서 끊어 각자 검사한다. 끊지 않으면 "저렴"이
    CPU(similar)에도 붙어 맞는 답을 버렸다(10/13 실측 2/3)."""
    from src.agent.quote_review_agent import price_claims_are_grounded

    review = _prices_review({"CPU": "similar", "GPU": "cheaper", "저장장치": "pricier"})
    assert price_claims_are_grounded("CPU는 비슷하고 GPU는 더 저렴하며, 저장장치는 더 비쌉니다.", review) is True
    assert price_claims_are_grounded("CPU는 비슷한 가격이고 GPU는 더 저렴하지만, 저장장치는 32,000원 더 비쌉니다.", review) is True
    assert price_claims_are_grounded("CPU는 비싸고 GPU는 저렴합니다", _prices_review({"CPU": "cheaper", "GPU": "pricier"})) is False


def test_price_claims_guard_does_not_split_inside_a_number():
    """"55,000원"의 쉼표에서 끊으면 "000원 저렴하고 메인보드는 55"가 되어 앞 부품의 방향어가 메인보드에 붙었다(10/13 실측)."""
    from src.agent.quote_review_agent import price_claims_are_grounded

    review = _prices_review({"RAM": "cheaper", "메인보드": "pricier"})
    assert price_claims_are_grounded("RAM은 30,000원 저렴하고 메인보드는 55,000원 비쌉니다.", review) is True


def test_price_claims_guard_accepts_a_direction_from_the_comparison_with_our_recommendation(review):
    """카탈로그와 비교하지 못한 부품(no_catalog)도 우리 추천과는 비교했다 — "RAM은 우리 추천보다 30,000원 저렴"은 사실이다.
    'similar'라도 차이가 있으면 "10,000원 비싸다"는 사실이다. 어느 비교에도 없는 방향은 여전히 막는다."""
    from src.agent.quote_review_agent import price_claims_are_grounded

    review = {"prices": {"rows": [{"part": "CPU", "state": "similar", "diff": 10000},
                                  {"part": "RAM", "state": "no_catalog", "diff": None}]},
              "compare": {"rows": [{"part": "CPU", "price_state": "similar", "price_diff": 10000},
                                   {"part": "RAM", "price_state": "cheaper", "price_diff": -30000}]}}
    assert price_claims_are_grounded("RAM은 우리 추천보다 30,000원 저렴합니다.", review) is True
    assert price_claims_are_grounded("CPU는 견적이 10,000원 비쌉니다.", review) is True
    assert price_claims_are_grounded("RAM은 더 비쌉니다.", review) is False
    assert price_claims_are_grounded("CPU는 더 저렴합니다.", review) is False


def test_guard_accepts_the_same_value_written_as_a_percentage_but_not_a_new_number():
    """근거의 "750W × 0.9 = 675W"를 "90%"로 쓴 답은 같은 값의 다른 표기라 통과해야 한다 — 새 숫자(95%)는 여전히 막는다."""
    from src.agent.quote_review_agent import reply_is_grounded

    facts = ["파워 750W × 0.9 = 675W, CPU 120W + GPU 115W = 235W"]
    ok, outside, _ = reply_is_grounded("합계 235W는 750W의 90%인 675W 이하입니다.", facts)
    assert ok and not outside
    bad, outside, _ = reply_is_grounded("합계 235W는 750W의 95%입니다.", facts)
    assert not bad and "95" in outside
    ok_back, _, _ = reply_is_grounded("여유율은 0.9입니다.", ["여유율 90% 기준 675W"])
    assert ok_back


# ── 비교 질문: 브랜드 이름으로 부품군 찾기·시리즈 되묻기·없는 제품은 동의 후 검색 (2026-10-07) ─────────────────

@pytest.mark.parametrize("text,slot", [
    ("라이젠 9000이랑 비교해줘", "CPU"), ("i5 14400F랑 비교해줘", "CPU"), ("인텔 코어 울트라 7 대신 쓰면 어때", "CPU"),
    ("엔비디아 5070이랑 비교해줘", "GPU"), ("RTX 4070 대신 쓰면 어때", "GPU"), ("라데온 RX 7800 XT랑 비교", "GPU"),
    ("DDR5 말고 다른 건?", "RAM"), ("B650 보드랑 비교해줘", "메인보드"),
])
def test_brand_and_series_words_identify_the_part_group(text, slot):
    assert chat.match_slot(text.lower()) == slot


def test_a_series_name_asks_which_model_instead_of_comparing_with_nothing(review):
    calls = chat.route("라이젠 9000이랑 비교해줘", loader(), review)
    assert [c[0] for c in calls] == ["series_hint"]
    assert calls[0][1]["slot"] == "CPU" and calls[0][1]["product"] == "라이젠 9000"
    assert set(calls[0][1]["options"]) == {"AMD Ryzen 7 9800X3D", "AMD Ryzen 9 9950X"}
    text = chat.run_fact(review, *calls[0], loader())
    assert "시리즈 이름" in text and "9800X3D" in text and "어느 모델과 비교할까요" in text


def test_a_product_missing_the_series_word_is_compared_with_the_catalog_product(review):
    assert chat.route("엔비디아 5070이랑 비교해줘", loader(), review) == [
        ("compare_parts", {"slot": "GPU", "direction": None, "targets": ["NVIDIA GeForce RTX 5070 Ti"]})]
    assert chat.route("라이젠 9800X3D랑 비교해줘", loader(), review)[0][0] == "compare_parts"


def test_a_product_that_is_not_in_the_catalog_asks_for_search_consent(review):
    from src.agent.conditions_agent import SEARCH_PERMISSION_MARKER

    calls = chat.route("RTX 6090이랑 비교해줘", loader(), review)
    assert calls == [("search_consent", {"slot": "GPU", "product": "RTX 6090"})]
    text = chat.run_fact(review, *calls[0], loader())
    assert "RTX 6090" in text and "저희 DB에 없는 상품" in text and SEARCH_PERMISSION_MARKER in text


def test_product_phrase_keeps_only_the_product_that_was_asked_about():
    assert chat.product_phrase("RTX 6090이랑 비교해줘", ["6090"]) == "RTX 6090"
    assert chat.product_phrase("라이젠 9000과 비교해줘?", ["9000"]) == "라이젠 9000"
    # 비교하려는 견적 속 부품(5600X)·절 경계(대신)·어조 낱말이 검색어에 섞이지 않는다
    assert chat.product_phrase("CPU 5600X 대신 9999X 쓰면 뭐가 달라져?", ["9999x"]) == "9999X"
    assert chat.product_phrase("내 PC에 엔비디아 RTX 6090 쓰면 어때?", ["6090"]) == "엔비디아 RTX 6090"
    assert chat.product_phrase("5600X랑 AMD Ryzen 9 9999X 비교해줘", ["9999x"]) == "AMD Ryzen 9 9999X"


@db_only
def test_the_search_is_asked_first_and_runs_only_after_the_user_agrees(client, monkeypatch):
    from src.services import live_spec_lookup
    from src.services.live_spec_lookup import LiveSpecLookupResult

    calls = []

    def fake_lookup(conn, text, **kw):
        calls.append((text, kw))
        return LiveSpecLookupResult.model_validate(
            {"relevant": True, "supported_fields": {"interface": "PCIe 5.0"}, "source_url": "https://example.com/rtx6090"})

    monkeypatch.setattr(quote_review_agent, "available", lambda: False)
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    monkeypatch.setattr(live_spec_lookup, "lookup", fake_lookup)
    list_id = _created(client)

    ask = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "RTX 6090이랑 비교해줘"}).json()
    assert "외부 검색을 진행해도 될까요?" in ask["reply"] and "RTX 6090" in ask["reply"]
    assert ask["via"] == "rules" and ask["evidence"] == ["실시간 검색 동의"]
    assert calls == []                                                   # 동의 전에는 검색하지 않는다

    done = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "진행해줘"}).json()
    assert calls == [("RTX 6090", {"slot": "GPU"})]
    assert "실시간 검색 결과" in done["reply"] and "PCIe 5.0" in done["reply"] and "카탈로그 정식 등재 값이 아니" in done["reply"]
    assert done["evidence"] == ["실시간 검색"]

    again = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "진행해줘"}).json()
    assert len(calls) == 1 and "실시간 검색 결과" not in again["reply"]     # 한 번 동의로 계속 검색하지 않는다


@db_only
def test_a_different_message_after_the_consent_question_does_not_search(client, monkeypatch):
    from src.services import live_spec_lookup

    def boom(*a, **k):
        raise AssertionError("동의하지 않았는데 검색이 호출됨")

    monkeypatch.setattr(quote_review_agent, "available", lambda: False)
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    monkeypatch.setattr(live_spec_lookup, "lookup", boom)
    list_id = _created(client)
    client.post(f"/pc/reviews/{list_id}/messages", json={"text": "RTX 6090이랑 비교해줘"})
    for answer in ("아니 됐어", "호환은 문제없어?", "진행하지마"):
        reply = client.post(f"/pc/reviews/{list_id}/messages", json={"text": answer}).json()["reply"]
        assert "실시간 검색 결과" not in reply


@db_only
def test_a_series_question_is_answered_with_the_model_options_without_the_agent(client, monkeypatch):
    monkeypatch.setattr(quote_review_agent, "available", lambda: True)
    monkeypatch.setattr(quote_review_agent, "run_turn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("에이전트가 불림")))
    list_id = _created(client)
    res = client.post(f"/pc/reviews/{list_id}/messages", json={"text": "라이젠 9000이랑 비교해줘"}).json()
    assert res["via"] == "rules" and "시리즈 이름" in res["reply"] and res["evidence"] == ["제품 후보"]


# ── 게임이 돌아가는지 묻는 질문(C5) ──────────────────────────────────────────────────

GAME_QUOTE = {"CPU": "라이젠 5 7600", "GPU": "RTX 4060", "RAM": "삼성전자 DDR5-5600 (16GB)"}


def _game_review():
    return qrs.analyze(GAME_QUOTE, {"purpose": "game"})


@pytest.mark.parametrize("text", ["이 견적으로 사이버펑크 돌아가?", "배그 돌릴 수 있어?", "엘든링 프레임 잘 나와?"])
def test_a_game_question_routes_to_the_game_check(text):
    assert chat.route(text, loader(), _game_review())[0][0] == "game"


def test_a_swap_in_a_game_question_is_passed_as_the_hypothetical_part():
    call = chat.route("RTX 5070 으로 바꾸면 사이버펑크 돌아가?", loader(), _game_review())[0]
    assert call[0] == "game" and call[1]["swap_slot"] == "GPU" and "5070" in call[1]["swap_product"]


def test_the_game_fact_compares_the_requirement_table_with_the_current_build():
    review = _game_review()
    out = chat.run_fact(review, "game", {"text": "사이버펑크 돌아가?", "swap_slot": "", "swap_product": ""}, loader())
    assert "GPU 성능 등급 요구" in out and "지금" in out and "fps" in out
    assert "가정:" not in out


def test_the_game_fact_uses_the_swapped_part_and_says_the_quote_is_unchanged():
    review = _game_review()
    pool = loader()()
    name = next(c.name for c in pool["GPU"] if "5070" in c.name)
    out = chat.run_fact(review, "game", {"text": "사이버펑크 돌아가?", "swap_slot": "GPU", "swap_product": name}, loader())
    assert f"가정: GPU 를 {name} 로 바꾼 구성" in out and "바꾼 뒤" in out and "견적은 그대로" in out


def test_an_unconfirmed_cpu_or_gpu_is_reported_instead_of_guessed():
    review = qrs.analyze({"CPU": "라이젠 5 7600", "GPU": "만리 폴라 폭스"}, {"purpose": "game"})
    out = chat.run_fact(review, "game", {"text": "사이버펑크 돌아가?"}, loader())
    assert "확정되지 않아 성능 등급을 알 수 없습니다" in out


def test_every_fact_the_router_can_choose_has_a_label_in_both_label_tables():
    """에이전트가 근거 이름표를 못 찾아 KeyError 로 규칙 경로로 떨어지던 일(게임 점검을 추가할 때 한쪽에만 넣었다)을 막는다."""
    from src.agent.quote_review_agent import EVIDENCE_LABEL as agent_labels
    for name in ("game", "overview", "compat", "prices", "balance", "compare", "alternatives", "compare_parts", "series_hint",
                 "search_consent"):
        assert name in chat.EVIDENCE_LABEL and name in agent_labels, name


def test_a_shortened_swap_product_from_the_agent_is_resolved_to_the_catalog_name_or_reported():
    """에이전트가 "RTX 5070"처럼 줄여 넘겨도 카탈로그 제품으로 풀어 쓰고, 못 풀면 지금 견적 기준이라고 밝힌다(조용히 무시하지 않는다)."""
    review = _game_review()
    out = chat.run_fact(review, "game", {"text": "사이버펑크 돌아가?", "swap_slot": "GPU", "swap_product": "RTX 5070"}, loader())
    assert "가정: GPU 를" in out and "5070" in out
    out = chat.run_fact(review, "game", {"text": "사이버펑크 돌아가?", "swap_slot": "GPU", "swap_product": "RTX 9999"}, loader())
    assert "하나로 찾지 못해 지금 견적 기준" in out and "가정:" not in out


@pytest.mark.parametrize("text", ["롤 돌리기 좋아?", "R02에서 GPU를 바꿔도 배그 돌아가?", "롤이랑 배그 돼?"])
def test_a_short_game_nickname_inside_a_sentence_is_found_in_the_requirement_table(text):
    out = chat.run_fact(_game_review(), "game", {"text": text, "swap_slot": "", "swap_product": ""}, loader())
    assert "게임 요구 사양 표에 없어" not in out and "요구" in out


def test_compare_parts_facts_carry_the_gap_between_the_two_candidates():
    """"7700X와 9700X 비교"에서 모델이 두 후보의 차이(470원 등)를 직접 빼면 근거에 없는 숫자로 거부돼 원문 나열로 바뀌던 문제 — 차이를 코드가 계산해 싣는다."""
    from src.services import quote_facts
    cand = lambda name, price, power: {"name": name, "price": price, "price_delta": price - 569_200, "incompatible": [], "compat_changes": [],  # noqa: E731
                                       "specs": [{"label": "기본 전력", "unit": "W", "baseline": 120, "candidate": power, "diff": power - 120}], "review": {}}
    out = quote_facts.compare_parts({"slot": "CPU", "baseline": {"name": "7800X3D", "price": 569_200},
                                     "candidates": [cand("7700X", 417_760, 105), cand("9700X", 417_290, 65)]})
    assert "후보끼리 가격: 9700X이(가) 7700X보다 470원 저렴" in out
    assert "후보끼리 기본 전력: 7700X 105W / 9700X 65W (-40)" in out


def test_numbers_from_earlier_turns_are_grounded_for_a_follow_up_question():
    """후속 질문("둘 중 뭐가 나아?")의 답이 앞 턴에서 이미 나온 수치를 다시 써도 거부하지 않는다."""
    earlier = ["AMD Ryzen 7 7700X와 9700X를 비교해서 보여줘", "7700X는 기본 전력 105W, 9700X는 65W입니다."]
    reply = "기본 전력은 7700X가 105W, 9700X가 65W입니다. 어느 쪽이 낫다고 판단하지는 않아요."
    assert quote_review_agent.reply_is_grounded(reply, ["이번 턴 근거"])[0] is False
    assert quote_review_agent.reply_is_grounded(reply, ["이번 턴 근거", *earlier])[0] is True


def test_a_rejected_reply_without_a_matching_lookup_is_not_replaced_by_the_whole_overview(monkeypatch):
    """질문에 맞는 조회가 없는데 답이 거부되면 요약 전체를 던지지 않고, 어떻게 다시 물으면 되는지 안내한다."""
    from types import SimpleNamespace
    import strands
    monkeypatch.setattr(strands, "Agent", lambda **kw: (lambda text: "근거에 없는 99999원이에요."), raising=False)
    monkeypatch.setattr(quote_review_agent, "_model", lambda: None)
    monkeypatch.setattr(quote_review_agent, "make_tools", lambda session: [])
    monkeypatch.setattr(quote_review_agent, "system_prompt", lambda *a, **k: "prompt")
    result = quote_review_agent.run_turn({}, [], "둘 중 뭐가 나아?", [], lambda n, a: "요약 전체 문장", user_text="둘 중 뭐가 나아?")
    assert result.reply == quote_review_agent.NO_GROUNDED_REPLY and "요약 전체 문장" not in result.reply
