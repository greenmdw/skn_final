"""키보드 키압 판정 조건(요청서 B-8 후속, 0016 컬럼): 가벼운 키압(min ≤ 45g) · 묵직한 키압(max ≥ 50g).

DB·모델 호출 없음. 후보는 테스트가 직접 만든다. 규칙 값(45g·50g)은 설정(`spec_conditions.keyboard`)에 있다."""
from __future__ import annotations

import pytest

from src.dto import Candidate
from src.engine import peripheral_intent as pi
from src.engine import peripheral_select as sel
from src.engine import spec_rules
from src.engine.peripheral_requirement import build_requirements
from src.engine.peripheral_rules import load_peripheral_rules, spec_conditions

RULES = load_peripheral_rules()
LIGHT = spec_conditions("keyboard", RULES)["light_key_force"]
HEAVY = spec_conditions("keyboard", RULES)["heavy_key_force"]
ZERO = {"스위치소음": 0.0, "배열크기": 0.0, "연결": 0.0, "리뷰": 0.0, "가격": 0.0, "브랜드": 0.0, "무상AS": 0.0}


def _verdict(cond, **specs):
    return spec_rules.evaluate_all(cond["prefs"], specs)[0]


# ── 판정 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("min_g, max_g, light, heavy", [
    (35, 35, "Pass", "Fail"),          # 35g 한 가지 — 가볍다
    (45, 45, "Pass", "Fail"),          # 경계: 45g 는 가볍다
    (46, 46, "Fail", "Fail"),          # 46~49g 는 어느 쪽도 아니다
    (50, 50, "Fail", "Pass"),          # 경계: 50g 는 묵직하다
    (60, 60, "Fail", "Pass"),
    (45, 60, "Pass", "Pass"),          # 스위치를 고르는 상품: 가장 가벼운 쪽·가장 묵직한 쪽으로 각각 판정
    (35, 80, "Pass", "Pass"),
])
def test_light_and_heavy_are_judged_from_the_min_and_the_max(min_g, max_g, light, heavy):
    specs = {"key_force_min_g": min_g, "key_force_max_g": max_g}
    assert _verdict(LIGHT, **specs) == light
    assert _verdict(HEAVY, **specs) == heavy


def test_a_product_without_key_force_is_unknown_not_failing():
    assert _verdict(LIGHT) == "Pending" and _verdict(HEAVY) == "Pending"
    assert _verdict(LIGHT, key_force_min_g=None) == "Pending"


def test_neither_condition_filters_candidates():
    assert LIGHT["filter"] is False and HEAVY["filter"] is False


# ── 순위 ────────────────────────────────────────────────────────────────────
def _kb(key, min_g=None, max_g=None, price=100_000):
    specs = {}
    if min_g is not None:
        specs["key_force_min_g"] = min_g
    if max_g is not None:
        specs["key_force_max_g"] = max_g
    return Candidate(product_key=key, slot="keyboard", name=key, price=price, specs=specs)


def _rank(stated=None, purposes=None):
    interp = pi.Interpretation(kinds=["keyboard"], stated={"keyboard": stated} if stated else {}, purposes=purposes or [])
    values = {"peripheral_resolved": pi.resolve(interp, RULES)}
    req = build_requirements(values, ["keyboard"], RULES)["keyboard"]
    pool = [_kb("light", 35, 40), _kb("heavy", 60, 70), _kb("unknown"), _kb("range", 45, 60)]
    return {c.product_key: c for c in sel.rank_candidates("keyboard", req, pool, {**ZERO, "스위치소음": 1.0}, rules=RULES)}


def test_saying_light_key_force_lifts_light_boards_and_keeps_unknown_in_the_middle():
    got = _rank(stated=["light_key_force"])
    value = {k: c.breakdown["스위치소음"] for k, c in got.items()}
    assert value == {"light": 1.0, "range": 1.0, "unknown": 0.5, "heavy": 0.0}
    order = sorted(got, key=lambda k: -got[k].score)
    assert order.index("light") < order.index("unknown") < order.index("heavy")


def test_saying_heavy_key_force_reverses_the_preference():
    got = _rank(stated=["heavy_key_force"])
    value = {k: c.breakdown["스위치소음"] for k, c in got.items()}
    assert value == {"heavy": 1.0, "range": 1.0, "unknown": 0.5, "light": 0.0}


def test_without_a_key_force_condition_the_criterion_is_neutral():
    got = _rank()
    assert {c.breakdown["스위치소음"] for c in got.values()} == {0.5}


def test_both_stated_conditions_cancel_for_a_range_that_satisfies_both():
    got = _rank(stated=["light_key_force", "heavy_key_force"])
    assert got["range"].breakdown["스위치소음"] == 1.0                 # 45~60g 는 둘 다 충족
    assert got["light"].breakdown["스위치소음"] == pytest.approx(0.5, abs=1e-3)
    assert got["heavy"].breakdown["스위치소음"] == pytest.approx(0.5, abs=1e-3)


def test_stated_key_force_doubles_the_switch_criterion_weight():
    got = _rank(stated=["light_key_force"])
    reasons = got["light"].score_detail["weights_reason"]
    assert any("스위치소음" in r for r in reasons)


# ── 목적에서 풀린 선호 ───────────────────────────────────────────────────────
def test_competitive_games_prefer_light_key_force_as_a_derived_not_stated_condition():
    resolved = pi.resolve(pi.Interpretation(kinds=["keyboard"], purposes=["fps"]), RULES)["keyboard"]
    ids = {c.condition: c.sources for c in resolved.preferences}
    assert "light_key_force" in ids and ids["light_key_force"] == ["fps"]       # 직접 말한 게 아니다
    assert resolved.stated_preference_prefs() == []                              # → 기준 가중 ×2 가 붙지 않는다


# ── 문장 해석 · 칩 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("가벼운 키압 키보드 찾아요", "light_key_force"),
    ("키압이 묵직한 키보드가 좋아요", "heavy_key_force"),
    ("키보드 묵직한 타건 느낌으로", "heavy_key_force"),
])
def test_words_read_key_force_as_a_stated_condition(text, expected):
    got = pi.interpret_by_words(text, RULES)
    assert got.kinds == ["keyboard"] and expected in got.stated.get("keyboard", [])


def test_key_force_chips_are_defined_for_keyboards_only():
    chips = {c["id"]: c for c in RULES["adjust_chips"]["keyboard"]}
    assert chips["light_key_force"]["add"] == {"stated": ["light_key_force"]}
    assert chips["heavy_key_force"]["add"] == {"stated": ["heavy_key_force"]}
    assert not any("key_force" in c["id"] for kind in ("monitor", "mouse", "speaker") for c in RULES["adjust_chips"][kind])


def test_a_key_force_chip_is_offered_when_it_changes_the_visible_order():
    from src.engine.peripheral_suggest import suggest_chips

    pool = [_kb("heavy_cheap", 60, 70, price=50_000), _kb("light_pricey", 35, 40, price=120_000), _kb("unknown_mid", price=80_000)]
    interp = pi.Interpretation(kinds=["keyboard"])
    values = {"peripherals": ["keyboard"], "peripheral_intent": interp, "peripheral_resolved": pi.resolve(interp, RULES)}
    base = sel.run_peripherals(values, {"keyboard": pool}, lambda *_: None)
    chips = suggest_chips(values, interp, {"keyboard": pool}, base, RULES, limit=10)
    ids = {c["id"] for c in chips}
    assert "light_key_force" in ids
    light = next(c for c in chips if c["id"] == "light_key_force")
    assert light["add"]["stated"] == {"keyboard": ["light_key_force"]} and light["moved"] >= 1


def test_chip_is_not_offered_once_the_condition_was_said():
    from src.engine.peripheral_suggest import suggest_chips

    pool = [_kb("heavy_cheap", 60, 70, price=50_000), _kb("light_pricey", 35, 40, price=120_000)]
    interp = pi.Interpretation(kinds=["keyboard"], stated={"keyboard": ["light_key_force"]})
    values = {"peripherals": ["keyboard"], "peripheral_intent": interp, "peripheral_resolved": pi.resolve(interp, RULES)}
    base = sel.run_peripherals(values, {"keyboard": pool}, lambda *_: None)
    assert "light_key_force" not in {c["id"] for c in suggest_chips(values, interp, {"keyboard": pool}, base, RULES, limit=10)}
