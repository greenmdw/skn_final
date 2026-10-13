"""부품 점수식(정책 §2~§4) — 세 축 가중합, 입력 검증, 설정 검증.

가격 = B/(B+P), 성능 = perf_tier/10, 리뷰 = 리뷰 적합도, S_base = clip01(Σ w·s). 반올림하지 않는다."""
from __future__ import annotations

import math
from copy import deepcopy

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RequirementSpec, ReviewRequirementProfile, ReviewScoreDetail, Slots
from src.engine import stage2_requirement, stage3b_rank
from src.engine.score_policy import AXES, ScoreInputError, clip01, price_axis, validate_axis_weights
from src.services.review_aspect_score import build_review_requirement_profile


def _ranking() -> dict:
    return stage2_requirement.load_computer_rules()["ranking"]


def _detail(value):
    return ReviewScoreDetail(profile=ReviewRequirementProfile(
        profile_version="t", analysis_version="t", part_type="gpu"), value=value)


def _cand(key="g", price=100_000, slot="GPU", **specs):
    return Candidate(product_key=key, slot=slot, name=key, price=price, specs=specs)


def _slots(**values):
    return Slots(category="computer", mode="build", objective_text="", values=values)


def _spec(total=1_000_000, alloc=None, slot="GPU"):
    return RequirementSpec(list_id="r", category="computer", mode="build", targets={slot: {}},
                           budget={"total": total, "alloc": {slot: 0.2} if alloc is None else alloc})


def _run(cands, spec=None, slot="GPU", **values):
    return stage3b_rank.run(HardFilterResult(slots={slot: cands}), spec or _spec(slot=slot), _slots(**values),
                            lambda _: None)


# ── 가격 축 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("price, expected", [(50_000, 0.8), (100_000, 2 / 3), (200_000, 0.5),
                                              (400_000, 1 / 3), (800_000, 0.2)])
def test_price_axis_table_at_a_200k_reference_budget(price, expected):
    assert price_axis(price, 200_000) == pytest.approx(expected)
    assert round(price_axis(price, 200_000), 4) == pytest.approx(round(expected, 4))


@pytest.mark.parametrize("price, budget", [
    (0, 200_000), (-1, 200_000), (None, 200_000), (True, 200_000), (math.nan, 200_000), (math.inf, 200_000),
    (100_000, 0), (100_000, -5), (100_000, None), (100_000, False), (100_000, math.nan), (100_000, math.inf),
    ("100000", 200_000),
])
def test_price_axis_rejects_bad_inputs(price, budget):
    with pytest.raises(ScoreInputError):
        price_axis(price, budget)


@pytest.mark.parametrize("bad", [True, None, math.nan, math.inf, -math.inf, "0.5"])
def test_clip01_rejects_non_finite_or_non_real(bad):
    with pytest.raises(ScoreInputError):
        clip01(bad)


def test_clip01_clips_to_the_unit_interval():
    assert (clip01(-0.2), clip01(0.4), clip01(1.7)) == (0.0, 0.4, 1.0)


# ── 가중치 검증 ───────────────────────────────────────────────────────────────

def _w(**kw):
    return {"가격": 0.45, "성능": 0.30, "리뷰": 0.25, **kw}


def test_valid_weights_pass():
    validate_axis_weights(_w(), "t")
    assert AXES == ("가격", "성능", "리뷰")


@pytest.mark.parametrize("weights", [
    _w(가격=0.5),                       # 합 != 1
    _w(가격=-0.05, 성능=0.8),            # 음수
    _w(가격=0.455, 성능=0.295),          # 0.005 단위
    _w(가격=math.nan),
    _w(가격=True, 성능=0.0, 리뷰=0.0),    # bool 은 실수가 아니다
    {"가격": 0.5, "성능": 0.5},          # 축 누락
    {**_w(), "소음": 0.0},              # 축 추가
    _w(가격=1.2, 성능=-0.2, 리뷰=0.0),
    None,
])
def test_invalid_weights_are_rejected_with_where(weights):
    with pytest.raises(ValueError, match="내 위치"):
        validate_axis_weights(weights, "내 위치")


def test_stage2_wraps_weight_errors_as_rule_errors_with_location(tmp_path):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["ranking"]["priority_weights"]["quiet"]["가격"] = 0.9
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError, match="quiet"):
        stage2_requirement.load_computer_rules(path)


@pytest.mark.parametrize("key, value", [("noise_proxy", {"cpu_tdp_w": [65, 200]}), ("noise_sensitive_min_weight", 0.15)])
def test_removed_policy_keys_are_rejected(tmp_path, key, value):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["ranking"][key] = value
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError, match=key):
        stage2_requirement.load_computer_rules(path)


def test_default_and_priority_weights_match_the_policy_table():
    ranking = _ranking()
    assert ranking["score_method"] == "pc-fit-v2"
    assert ranking["weights"] == {"가격": 0.45, "성능": 0.30, "리뷰": 0.25}
    assert ranking["priority_weights"] == {
        "performance": {"가격": 0.20, "성능": 0.60, "리뷰": 0.20},
        "value": {"가격": 0.55, "성능": 0.25, "리뷰": 0.20},
        "quiet": {"가격": 0.40, "성능": 0.25, "리뷰": 0.35},
    }


# ── 점수 계산 ─────────────────────────────────────────────────────────────────

def test_policy_example_7_1_reproduces_0_665():
    # 가격 0.8 · 성능 0.6 · 리뷰 0.5, 기본 가중치.
    scored = stage3b_rank._score(_cand(price=50_000, perf_tier=6), 200_000.0, "GPU",
                                 review_detail=_detail(0.5))
    assert scored.breakdown == pytest.approx({"가격": 0.8, "성능": 0.6, "리뷰": 0.5})
    assert scored.score == pytest.approx(0.665)


def test_policy_example_7_2_reproduces_0_605():
    # 가격 0.4 · 성능 1.0 · 리뷰 0.5.
    scored = stage3b_rank._score(_cand(price=300_000, perf_tier=10), 200_000.0, "GPU",
                                 review_detail=_detail(0.5))
    assert scored.breakdown["가격"] == pytest.approx(0.4)
    assert scored.score == pytest.approx(0.605)


def test_score_and_breakdown_are_not_rounded():
    scored = stage3b_rank._score(_cand(price=137_000, perf_tier=7.3), 211_000.0, "GPU",
                                 review_detail=_detail(0.123456789))
    values = [scored.score, *scored.breakdown.values()]
    assert any(round(v, 3) != v for v in values)
    assert scored.breakdown["리뷰"] == 0.123456789
    assert 0.0 <= scored.score <= 1.0


def test_review_value_is_clipped_into_the_unit_interval():
    high = stage3b_rank._score(_cand(perf_tier=5), 100_000.0, "GPU", review_detail=_detail(1.0))
    assert high.breakdown["리뷰"] == 1.0


def test_candidate_score_does_not_depend_on_other_candidates():
    a = _cand("a", 120_000, perf_tier=6)
    b = _cand("b", 300_000, perf_tier=9)
    c = _cand("c", 20_000, perf_tier=3)
    alone = _run([a]).slots["GPU"]["pool"][0]
    with_others = next(x for x in _run([a, b, c]).slots["GPU"]["pool"] if x["product_key"] == "a")
    removed = next(x for x in _run([a, c]).slots["GPU"]["pool"] if x["product_key"] == "a")
    assert alone["score"] == with_others["score"] == removed["score"]
    assert alone["breakdown"] == with_others["breakdown"]


def test_cpu_gpu_without_perf_tier_is_an_input_error_other_slots_are_neutral():
    with pytest.raises(ScoreInputError):
        stage3b_rank._score(_cand(slot="GPU"), 100_000.0, "GPU")
    ram = stage3b_rank._score(_cand("r", 50_000, slot="RAM"), 100_000.0, "RAM")
    assert ram.breakdown["성능"] == 0.5 and ram.score_notes == ["neutral:성능"]
    gpu = stage3b_rank._score(_cand(perf_tier=6), 100_000.0, "GPU")
    assert gpu.score_notes == []


def test_noise_sensitive_does_not_change_the_outer_weights_or_the_score():
    plain = _run([_cand(perf_tier=6)], priority="quiet")
    flagged = _run([_cand(perf_tier=6)], priority="quiet", noise_sensitive=True)
    assert plain.weights_used == flagged.weights_used == _ranking()["priority_weights"]["quiet"]
    assert plain.slots["GPU"]["ranked"][0]["score"] == flagged.slots["GPU"]["ranked"][0]["score"]
    assert stage3b_rank._weights_for({"noise_sensitive": True}, _ranking())[0] == _ranking()["weights"]


def test_quiet_alpha_is_adjusted_once_by_the_review_profile():
    only_quiet = build_review_requirement_profile("gpu", {"priority": "quiet"})
    both = build_review_requirement_profile("gpu", {"priority": "quiet", "noise_sensitive": True})
    plain = build_review_requirement_profile("gpu", {})

    def alphas(profile):
        return {(a.aspect_code, a.context_code): a.alpha for a in profile.attributes}

    assert alphas(only_quiet) == alphas(both)
    assert alphas(only_quiet) != alphas(plain)


# ── 참고 예산 오류 ────────────────────────────────────────────────────────────

def test_missing_alloc_slot_or_bad_total_is_a_score_input_error():
    cand = _cand(perf_tier=6, review_detail=None)
    with pytest.raises(ScoreInputError):
        _run([cand], spec=_spec(alloc={"CPU": 0.2}))
    with pytest.raises(ScoreInputError):
        _run([cand], spec=_spec(alloc={}))
    for total in (0, -1, None, math.nan, math.inf, True):
        with pytest.raises(ScoreInputError):
            _run([cand], spec=_spec(total=total))


def test_sort_key_breaks_ties_by_price_then_product_key():
    a = _cand("b", 100_000, perf_tier=6)
    b = _cand("a", 100_000, perf_tier=6)
    ranked = _run([a, b]).slots["GPU"]["pool"]
    assert [c["product_key"] for c in ranked] == ["a", "b"]
