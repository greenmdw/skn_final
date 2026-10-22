"""문장에서 강조 축·선호/기피 브랜드를 읽는 규칙(기획 3.3·3.7) — 단어 규칙, 정리(sanitize), 이어 말하기(merge), 요청 계약, 설정 검사.

DB·모델 호출 없음."""
from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from src import schemas
from src.engine import peripheral_intent as pi
from src.engine.peripheral_rules import PeripheralRuleError, load_peripheral_rules

RULES = load_peripheral_rules()


# ── 단어 규칙 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, kind, emphasis, like, avoid", [
    ("마우스 가성비 좋은 걸로", "mouse", {"가격"}, set(), set()),
    ("키보드 평이 좋은 걸로 찾아요", "keyboard", {"리뷰"}, set(), set()),
    ("모니터 AS가 중요해요", "monitor", {"무상AS"}, set(), set()),
    ("로지텍 마우스 찾아요", "mouse", {"브랜드"}, {"Logitech"}, set()),         # 선호 브랜드를 말하면 브랜드 축도 강조
    ("마우스 로지텍 말고 레이저로", "mouse", {"브랜드"}, {"Razer"}, {"Logitech"}),
    ("마우스 델 제품 빼고 hp로", "mouse", {"브랜드"}, {"HP"}, {"Dell"}),
    ("마우스 레이저는 별로예요", "mouse", set(), set(), {"Razer"}),
])
def test_words_read_emphasis_and_brands(text, kind, emphasis, like, avoid):
    got = pi.interpret_by_words(text, RULES)
    assert got.kinds == [kind]
    assert set(got.emphasis.get(kind, [])) == emphasis
    assert set(got.brand_like.get(kind, [])) == like
    assert set(got.brand_avoid.get(kind, [])) == avoid


def test_a_short_brand_name_inside_another_word_is_not_read():
    """"델"이 "모델" 안에서, "hp"가 "hpc" 안에서 잡히지 않는다."""
    assert pi.interpret_by_words("모델 좋은 마우스 찾아요", RULES).brand_like == {}
    assert pi.interpret_by_words("마우스 hpc 용도", RULES).brand_like == {}


def test_nothing_is_attached_when_the_kind_is_unknown():
    got = pi.interpret_by_words("가성비 좋은 로지텍으로", RULES)
    assert got.kinds == [] and got.emphasis == {} and got.brand_like == {}


def test_a_kind_card_lets_the_same_sentence_attach_to_that_kind():
    got = pi.interpret_by_words("가성비 좋은 로지텍으로", RULES, kinds_hint=["mouse"])
    assert got.emphasis == {"mouse": ["가격", "브랜드"]} and got.brand_like == {"mouse": ["Logitech"]}


# ── 정리·이어 말하기 ─────────────────────────────────────────────────────────
def test_sanitize_drops_unknown_axes_and_brands_and_keeps_listed_ones():
    got = pi.sanitize({"kinds": ["mouse"], "emphasis": {"mouse": ["가격", "손맞춤", "없는축", 3], "toaster": ["가격"]},
                       "brand_like": {"mouse": ["Logitech", "NoSuchBrand"]}, "brand_avoid": {"mouse": ["Razer"]}}, RULES)
    assert got.emphasis == {"mouse": ["가격", "손맞춤", "브랜드"]}         # 손맞춤은 마우스의 스펙 기준 이름이다
    assert got.brand_like == {"mouse": ["Logitech"]} and got.brand_avoid == {"mouse": ["Razer"]}


def test_a_brand_cannot_be_liked_and_avoided_at_once_avoid_wins():
    got = pi.sanitize({"kinds": ["mouse"], "brand_like": {"mouse": ["Logitech"]}, "brand_avoid": {"mouse": ["Logitech"]}}, RULES)
    assert got.brand_like == {} and got.brand_avoid == {"mouse": ["Logitech"]}
    assert "브랜드" not in got.emphasis.get("mouse", [])


def test_a_spec_criterion_of_another_kind_is_not_accepted():
    got = pi.sanitize({"kinds": ["mouse"], "emphasis": {"mouse": ["화면", "손맞춤"]}}, RULES)    # 화면은 모니터의 기준
    assert got.emphasis == {"mouse": ["손맞춤"]}


def test_merge_unions_emphasis_and_brands_across_sentences():
    first = pi.interpret_by_words("마우스 가성비 좋은 걸로", RULES)
    second = pi.interpret_by_words("마우스 로지텍 말고", RULES)
    merged = pi.merge(first, second)
    assert set(merged.emphasis["mouse"]) == {"가격"} and merged.brand_avoid == {"mouse": ["Logitech"]}


# ── 요청 계약: 입력이 점수식까지 이어진다 ────────────────────────────────────
def test_request_inputs_are_cleaned_and_unknown_names_are_reported():
    from src.services import peripherals_service as svc

    body = schemas.PeripheralsRecommendIn(
        kinds=["mouse"], emphasis={"mouse": ["가격", "없는축"]}, brand_like={"mouse": ["Logitech", "Nope"]},
        brand_avoid={"mouse": ["Razer"]})
    interp, ignored = svc._intent_from_body(body)
    assert interp.emphasis["mouse"][0] == "가격" and interp.brand_like == {"mouse": ["Logitech"]}
    assert interp.brand_avoid == {"mouse": ["Razer"]}
    assert ignored == ["Nope", "없는축"]


# ── 모델 경로 ───────────────────────────────────────────────────────────────
def test_agent_schema_and_prompt_carry_the_new_fields():
    from src.agent import peripheral_intent_agent as agent

    schema = agent._output_schema(RULES)
    for key in ("emphasis", "brand_like", "brand_avoid"):
        assert key in schema["properties"] and key in schema["required"]
    enum = schema["properties"]["brand_like"]["properties"]["mouse"]["items"]["enum"]
    assert "Logitech" in enum and "NoSuchBrand" not in enum
    axes = schema["properties"]["emphasis"]["properties"]["mouse"]["items"]["enum"]
    assert {"가격", "리뷰", "무상AS", "손맞춤"} <= set(axes) and "화면" not in axes
    prompt = agent.build_system_prompt(RULES)
    assert "emphasis" in prompt and "Logitech" in prompt


# ── 설정 검사 ───────────────────────────────────────────────────────────────
def _write(tmp_path, rules):
    path = tmp_path / "peripherals.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_loader_rejects_a_word_listed_under_two_axes(tmp_path):
    bad = deepcopy(RULES)
    bad["emphasis"]["words"]["리뷰"].append("가성비")           # 가격에도 있다
    with pytest.raises(PeripheralRuleError, match="두 축"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_loader_rejects_an_uppercase_alias(tmp_path):
    bad = deepcopy(RULES)
    bad["emphasis"]["brands"]["Logitech"].append("LOGITECH")
    with pytest.raises(PeripheralRuleError, match="소문자"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_shipped_brand_names_match_the_catalog_spelling():
    """브랜드 이름은 카탈로그의 brand 와 같은 철자여야 후보에 닿는다(점수식은 소문자로 비교한다)."""
    names = set(RULES["emphasis"]["brands"])
    for brand in ("Logitech", "Razer", "Dell", "HP", "Samsung", "LG", "Creative"):
        assert brand in names
