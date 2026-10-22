"""주변기기 점수식(기획 3.1~3.8, 개발요청 점수식 개선): 스펙 기준 · 가중 배수 · 근거 부족 감점 · 예산/브랜드 · 접전.

DB·모델 호출 없음. 설정(`config/peripherals.yaml` ranking·scoring)의 값에 기대지 않도록, 가중치는 시험이 직접 만든다."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.dto import (
    Candidate, FeelAttributeDetail, FeelDetail, PeripheralPick, PeripheralRequirement, ReviewAspectContribution,
    ReviewRequirementProfile, ReviewScoreDetail,
)
from src.engine import peripheral_intent as pi
from src.engine import peripheral_select as sel
from src.engine.peripheral_rules import PeripheralRuleError, load_peripheral_rules

RULES = load_peripheral_rules()
CFG = RULES["scoring"]
ZERO_MOUSE = {"손맞춤": 0.0, "연결": 0.0, "기능": 0.0, "리뷰": 0.0, "가격": 0.0, "브랜드": 0.0, "무상AS": 0.0}


def _w(**axes):
    return {**ZERO_MOUSE, **axes}


def _cand(key, price=50_000, brand="B", specs=None, n=None, value=0.5, verdict="Pass"):
    """n 이 있으면 외부 리뷰 관측 수를 n 건(긍정)으로 가진 체감 근거를 붙인다."""
    feel = None
    review = None
    if n is not None:
        attr = FeelAttributeDetail(code="grip", label="그립", type="rating", alpha=1.0, value=value, state="external_only",
                                   external_p=n, external_n=0)
        feel = FeelDetail(value=value, attributes=[attr])
        review = _review_detail(("ergonomics", n, 0))
    return Candidate(product_key=key, slot="mouse", name=key, price=price, brand=brand, specs=specs or {},
                     feel_detail=feel, review_detail=review, verdict=verdict)


def _req(preferences=None, stated=None):
    soft = {}
    if preferences:
        soft["preferences"] = preferences
        if stated:
            soft["stated"] = stated
    return PeripheralRequirement(kind="mouse", hard={}, soft=soft)


# ── 가중치: 강조 ×1.5, 직접 말한 조건 ×2, 합 1 ─────────────────────────────
CRITERIA = {"손맞춤": ["weight_g"], "연결": ["connectivity_wireless"], "기능": ["button_count"]}
BASE = {"손맞춤": 0.15, "연결": 0.07, "기능": 0.08, "리뷰": 0.35, "가격": 0.27, "브랜드": 0.04, "무상AS": 0.04}


def test_weights_are_normalised_and_unchanged_without_stated_or_emphasis():
    w, reasons = sel.effective_weights(BASE, CRITERIA, set(), set(), CFG)
    assert sum(w.values()) == pytest.approx(1.0) and reasons == []
    assert w == pytest.approx(BASE)


def test_stated_criterion_gets_double_weight_before_normalising():
    w, reasons = sel.effective_weights(BASE, CRITERIA, {"연결"}, set(), CFG)
    total = sum(BASE.values()) + BASE["연결"]
    assert w["연결"] == pytest.approx(BASE["연결"] * 2 / total)
    assert w["손맞춤"] == pytest.approx(BASE["손맞춤"] / total)         # 말하지 않은 기준에는 곱하지 않는다
    assert sum(w.values()) == pytest.approx(1.0) and len(reasons) == 1 and "연결" in reasons[0]


def test_emphasised_spec_criterion_with_stated_condition_is_tripled():
    w, _ = sel.effective_weights(BASE, CRITERIA, {"연결"}, {"연결"}, CFG)
    total = sum(BASE.values()) - BASE["연결"] + BASE["연결"] * 1.5 * 2
    assert w["연결"] == pytest.approx(BASE["연결"] * 3 / total)


def test_emphasis_alone_multiplies_the_axis_by_one_and_a_half():
    w, _ = sel.effective_weights(BASE, CRITERIA, set(), {"가격"}, CFG)
    total = sum(BASE.values()) + BASE["가격"] * 0.5
    assert w["가격"] == pytest.approx(BASE["가격"] * 1.5 / total)


# ── 스펙 기준 값 ────────────────────────────────────────────────────────────
def test_criterion_without_conditions_is_neutral_for_every_candidate():
    a = _cand("a", specs={"weight_g": 50})
    b = _cand("b", specs={"weight_g": 120})
    ranked = sel.rank_candidates("mouse", _req(), [a, b], _w(손맞춤=1.0))
    assert {c.breakdown["손맞춤"] for c in ranked} == {0.5}


def test_stated_condition_counts_double_inside_the_criterion_value():
    prefs = [{"key": "weight_g", "op": "max", "value": 80}, {"key": "weight_g", "op": "max", "value": 60}]
    cand = _cand("a", specs={"weight_g": 70})          # 80 이하는 통과, 60 이하는 미충족
    derived_only = sel.rank_candidates("mouse", _req(prefs), [cand], _w(손맞춤=1.0))[0].breakdown["손맞춤"]
    stated_first = sel.rank_candidates("mouse", _req(prefs, stated=[prefs[0]]), [cand], _w(손맞춤=1.0))[0].breakdown["손맞춤"]
    assert derived_only == pytest.approx(0.5)             # 1·0 을 같은 가중으로 평균
    assert stated_first == pytest.approx(2 / 3, abs=1e-3)   # 통과한 조건이 직접 말한 것이라 가중 2(축 값은 소수 셋째 자리)


def test_derived_conditions_do_not_double_the_criterion_weight():
    pref = {"key": "weight_g", "op": "max", "value": 80}
    ranked = sel.rank_candidates("mouse", _req([pref]), [_cand("a", specs={"weight_g": 70})], BASE)
    assert not [r for r in ranked[0].score_detail["weights_reason"] if "직접 말한" in r]   # 예산 없음 배수는 별개다
    stated = sel.rank_candidates("mouse", _req([pref], stated=[pref]), [_cand("a", specs={"weight_g": 70})], BASE)
    assert any("손맞춤" in r for r in stated[0].score_detail["weights_reason"])


def test_stated_condition_lifts_a_matching_but_pricier_candidate():
    """조건을 말했는데 조건에 안 맞는 싼 상품이 가격 축 때문에 1위가 되는 일을 줄인다(기획 3.3)."""
    pref = {"key": "connectivity_wireless", "op": "equals", "value": True}
    cheap = _cand("cheap", price=20_000, specs={"connectivity_wireless": False}, n=10)
    pricey = _cand("pricey", price=60_000, specs={"connectivity_wireless": True}, n=10)
    plain = sel.rank_candidates("mouse", _req([pref]), [cheap, pricey], BASE)
    said = sel.rank_candidates("mouse", _req([pref], stated=[pref]), [cheap, pricey], BASE)
    gap = lambda ranked: {c.product_key: c.score for c in ranked}                      # noqa: E731
    assert gap(said)["pricey"] - gap(said)["cheap"] > gap(plain)["pricey"] - gap(plain)["cheap"]


# ── 근거 부족 감점 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("n, penalty", [(0, 0.10), (1, 0.08), (2, 0.06), (3, 0.04), (4, 0.02), (5, 0.0), (40, 0.0)])
def test_evidence_penalty_values(n, penalty):
    assert sel.evidence_penalty(n, CFG) == pytest.approx(penalty)


def _review_detail(*contribs):
    return ReviewScoreDetail(
        profile=ReviewRequirementProfile(profile_version="p", analysis_version="a", part_type="mouse"), value=0.6,
        contributions=[ReviewAspectContribution(aspect_code=a, context_code="actual_use", rule_id="r", aggregate_id=a,
                                                alpha=1.0, p=p, n=n, mixed=7, k=4, q=0.6, alpha_q=0.6, evidence_state="observed")
                       for a, p, n in contribs])


def test_evidence_count_counts_each_external_aspect_once_plus_community_votes():
    """외부 리뷰는 aspect 마다 한 번(체감 속성이 같은 aspect 를 가리켜도 다시 세지 않는다), 사용기 표는 평가 속성만 더한다."""
    attrs = [
        # 같은 외부 aspect(ergonomics)를 가리키는 두 평가 속성 — 외부 p·n 이 속성마다 복제돼 있다
        FeelAttributeDetail(code="grip", label="g", type="rating", alpha=0.3, value=0.5, state="same_condition",
                            same_good=2, same_bad=1, rest_good=1, rest_bad=0, external_p=3, external_n=2),
        FeelAttributeDetail(code="wrist", label="w", type="rating", alpha=0.3, value=0.5, state="same_condition",
                            same_good=0, same_bad=0, rest_good=0, rest_bad=1, external_p=3, external_n=2),
        FeelAttributeDetail(code="weight_feel", label="w", type="taste", alpha=0.4, value=0.5, state="same_condition",
                            same_good=9, same_bad=9),                                    # 성향은 세지 않는다
    ]
    cand = Candidate(product_key="a", slot="mouse", name="a", price=1, feel_detail=FeelDetail(value=0.5, attributes=attrs),
                     review_detail=_review_detail(("ergonomics", 3, 2), ("battery_runtime", 4, 0)))
    assert sel.evidence_count(cand) == (3 + 2) + (4 + 0) + (2 + 1 + 1 + 0) + (0 + 0 + 0 + 1)


def test_evidence_count_falls_back_to_external_review_contributions():
    cand = Candidate(product_key="a", slot="mouse", name="a", price=1, review_detail=_review_detail(("x", 3, 1)))
    assert sel.evidence_count(cand) == 4                       # 혼합(mixed)은 세지 않는다


def test_penalty_is_per_product_and_keeps_thin_candidates_in_the_pool():
    pool = [_cand("rich", n=30), _cand("thin", n=1), _cand("none", n=None)]
    ranked = sel.rank_candidates("mouse", _req(), pool, _w(리뷰=1.0))
    by = {c.product_key: c for c in ranked}
    assert len(ranked) == 3                                              # 후보에서 빼지 않는다
    assert by["rich"].score_detail["penalties"]["evidence"] == 0.0
    assert by["thin"].score_detail["penalties"]["evidence"] == pytest.approx(0.08)
    assert by["none"].score_detail["penalties"]["evidence"] == pytest.approx(0.10)
    # 후보 풀이 달라져도 같은 감점
    alone = sel.rank_candidates("mouse", _req(), [_cand("thin", n=1)], _w(리뷰=1.0))[0]
    assert alone.score_detail["penalties"]["evidence"] == by["thin"].score_detail["penalties"]["evidence"]


def test_penalties_add_up():
    from src.config import PENDING_SCORE_PENALTY

    pref = {"key": "weight_g", "op": "max", "value": 80}
    other = _cand("other", specs={"weight_g": 70, "button_count": 6})
    gap = _cand("gap", specs={}, verdict="Pending", n=0)               # 판정 키 비어 있음 + Pending + 근거 0건
    ranked = sel.rank_candidates("mouse", _req([pref]), [other, gap], _w(리뷰=1.0))
    d = {c.product_key: c.score_detail for c in ranked}["gap"]
    assert d["penalties"]["pending"] == pytest.approx(PENDING_SCORE_PENALTY)
    assert d["penalties"]["missing_keys"] == pytest.approx(0.05)         # 다른 후보가 가진 weight_g 가 비어 있다
    assert d["penalties"]["evidence"] == pytest.approx(0.10)


def test_missing_key_penalty_only_when_another_candidate_has_the_key():
    pref = {"key": "weight_g", "op": "max", "value": 80}
    a, b = _cand("a", specs={}), _cand("b", specs={})
    ranked = sel.rank_candidates("mouse", _req([pref]), [a, b], _w(리뷰=1.0))
    assert all(c.score_detail["penalties"]["missing_keys"] == 0.0 for c in ranked)   # 아무도 값이 없으면 감점하지 않는다


def test_same_penalty_on_every_candidate_does_not_change_the_order():
    """리뷰가 아예 없는 품목(해커톤 구성의 스피커)은 모든 후보에 같은 감점이 붙어 순위가 안 바뀐다."""
    pool = [_cand("a", price=10_000), _cand("b", price=30_000), _cand("c", price=90_000)]
    weights = _w(가격=1.0)
    with_penalty = [c.product_key for c in sel.rank_candidates("mouse", _req(), pool, weights)]
    cfg_off = deepcopy(RULES)
    cfg_off["scoring"]["evidence_penalty"] = 0.0
    without = [c.product_key for c in sel.rank_candidates("mouse", _req(), pool, weights, rules=cfg_off)]
    assert with_penalty == without == ["a", "b", "c"]


# ── 가격·브랜드·무상 AS ─────────────────────────────────────────────────────
def test_price_axis_uses_the_kind_budget_when_given_and_the_median_otherwise():
    pool = [_cand("a", price=20_000), _cand("b", price=60_000)]
    with_budget = {c.product_key: c.breakdown["가격"]
                   for c in sel.rank_candidates("mouse", _req(), pool, _w(가격=1.0), kind_budget=100_000)}
    assert with_budget == {"a": 0.8, "b": 0.4}
    median = {c.product_key: c.breakdown["가격"] for c in sel.rank_candidates("mouse", _req(), pool, _w(가격=1.0))}
    assert median["a"] > median["b"] and median["a"] != 0.8            # 예산이 없으면 중앙값 대비 식


def test_brand_like_lifts_only_that_brand_and_is_neutral_otherwise():
    pool = [_cand("a", brand="Logitech"), _cand("b", brand="Razer")]
    liked = {c.product_key: c.breakdown["브랜드"] for c in sel.rank_candidates("mouse", _req(), pool, _w(브랜드=1.0), brand_like={"logitech"})}
    assert liked == {"a": 1.0, "b": 0.5}
    none = {c.breakdown["브랜드"] for c in sel.rank_candidates("mouse", _req(), pool, _w(브랜드=1.0))}
    assert none == {0.5}


def test_warranty_axis_is_neutral_without_data_and_relative_with_it():
    none = {c.breakdown["무상AS"] for c in sel.rank_candidates("mouse", _req(), [_cand("a"), _cand("b")], _w(무상AS=1.0))}
    assert none == {0.5}
    pool = [_cand("a", specs={"warranty_months": 12}), _cand("b", specs={"warranty_months": 36}), _cand("c", specs={"warranty_months": 24})]
    got = {c.product_key: c.breakdown["무상AS"] for c in sel.rank_candidates("mouse", _req(), pool, _w(무상AS=1.0))}
    assert got == {"a": 0.0, "b": 1.0, "c": 0.5}


def test_brand_avoid_removes_candidates_before_ranking():
    pool = [_cand("a", brand="Logitech"), _cand("b", brand="Razer")]
    values = {"peripherals": ["mouse"], "peripheral_brand_avoid": {"mouse": ["Razer"]},
              "peripheral_intent": pi.Interpretation(kinds=["mouse"]),
              "peripheral_resolved": pi.resolve(pi.Interpretation(kinds=["mouse"]), RULES)}
    result = sel.run_peripherals(values, {"mouse": pool}, lambda *_: None)
    assert result.picks[0].candidate.product_key == "a"
    assert [alt.product_key for alt in result.picks[0].alternatives] == []
    assert result.counts["mouse"]["avoided_brand"] == 1


# ── 직접 말한 조건 / 유도한 조건 구분이 요구사양까지 이어진다 ─────────────────────
def test_stated_preference_is_marked_and_derived_one_is_not():
    from src.engine.peripheral_requirement import build_requirements

    interp = pi.Interpretation(kinds=["mouse"], stated={"mouse": ["lightweight"]}, purposes=["fps"])
    values = {"peripheral_resolved": pi.resolve(interp, RULES)}
    soft = build_requirements(values, ["mouse"], RULES)["mouse"].soft
    stated_keys = {p["key"] for p in soft.get("stated", [])}
    assert "weight_g" in stated_keys                        # "가벼운"을 직접 말했다
    assert len(soft["preferences"]) >= len(soft["stated"])


# ── 접전 표시 ───────────────────────────────────────────────────────────────
def _pick(kind, gap):
    cand = Candidate(product_key=kind, slot=kind, name=kind, price=1, score=0.8)
    alt = Candidate(product_key=kind + "2", slot=kind, name=kind + "2", price=1, score=0.8 - (gap if gap is not None else 0))
    return PeripheralPick(kind=kind, candidate=cand, score=0.8, alternatives=[alt] if gap is not None else [], score_gap=gap)


def test_close_calls_are_marked_for_at_most_two_kinds_smallest_gap_first():
    picks = [_pick("monitor", 0.015), _pick("keyboard", 0.005), _pick("mouse", 0.01), _pick("speaker", 0.2)]
    sel._mark_close_calls(picks, RULES)
    marked = {p.kind for p in picks if p.close_call}
    assert marked == {"keyboard", "mouse"}                      # 접전이 셋이어도 차이가 작은 둘만


def test_no_alternative_means_no_close_call():
    picks = [_pick("mouse", None)]
    sel._mark_close_calls(picks, RULES)
    assert not picks[0].close_call


# ── 설정 검사 ───────────────────────────────────────────────────────────────
def _write(tmp_path, rules):
    import yaml

    path = tmp_path / "peripherals.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_loader_accepts_a_nonzero_review_weight():
    assert all(RULES["ranking"][k]["weights"]["리뷰"] > 0 for k in RULES["ranking"])


def test_loader_rejects_weights_that_do_not_match_the_criteria(tmp_path):
    bad = deepcopy(RULES)
    bad["ranking"]["mouse"]["weights"].pop("기능")
    with pytest.raises(PeripheralRuleError, match="가중치 축 오류"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_loader_rejects_a_spec_key_in_two_criteria(tmp_path):
    bad = deepcopy(RULES)
    bad["ranking"]["mouse"]["criteria"]["연결"].append("weight_g")           # 손맞춤에도 있다
    with pytest.raises(PeripheralRuleError, match="두 기준"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_loader_rejects_an_unusable_spec_key_in_a_criterion(tmp_path):
    bad = deepcopy(RULES)
    bad["ranking"]["mouse"]["criteria"]["기능"].append("no_such_key")
    with pytest.raises(PeripheralRuleError, match="판정에 쓸 수 없는"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_loader_rejects_weights_that_do_not_sum_to_one(tmp_path):
    bad = deepcopy(RULES)
    bad["ranking"]["mouse"]["weights"]["가격"] = 0.5
    with pytest.raises(PeripheralRuleError, match="합계가 1"):
        load_peripheral_rules(_write(tmp_path, bad))


def test_loader_rejects_a_condition_key_no_criterion_covers(tmp_path):
    bad = deepcopy(RULES)
    bad["ranking"]["mouse"]["criteria"]["기능"].remove("button_count")
    bad["ranking"]["mouse"]["criteria"]["연결"].append("button_count")      # 다른 기준으로 옮기면 통과
    load_peripheral_rules(_write(tmp_path, bad))
    worse = deepcopy(RULES)
    worse["ranking"]["mouse"]["criteria"]["기능"].remove("button_count")    # 어느 기준에도 없다
    (tmp_path / "second").mkdir()                                          # 같은 경로면 적재 결과가 캐시된다
    with pytest.raises(PeripheralRuleError, match="스펙 기준에도 없음"):
        load_peripheral_rules(_write(tmp_path / "second", worse))


def test_every_condition_key_is_covered_by_a_criterion_in_the_shipped_config():
    for kind, conds in RULES["spec_conditions"].items():
        covered = {k for keys in RULES["ranking"][kind]["criteria"].values() for k in keys}
        for cond_id, cond in conds.items():
            for pref in cond["prefs"]:
                assert pref["key"] in covered, (kind, cond_id, pref["key"])
