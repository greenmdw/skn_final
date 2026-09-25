"""예산 예비 판정(engine/feasibility)과 추천 기여도(stage5._contribution) — DB 없이 도는 단위 테스트."""
from __future__ import annotations

from src.dto import BuildItem, BuildResult, Candidate, RankResult, RequirementSpec
from src.engine import feasibility
from src.engine.stage5_explain import _contribution
from src.services.recommendation_service import budget_notice


def _cand(slot: str, name: str, price: int, **specs) -> Candidate:
    return Candidate(product_key=name.lower(), slot=slot, name=name, price=price, specs=specs)


def _spec(budget: int, targets: dict) -> RequirementSpec:
    return RequirementSpec(list_id="t", category="computer", mode="build", targets=targets, budget={"total": budget})


# ── 예비 판정 ─────────────────────────────────────────────────────────────
def test_cheapest_candidate_that_meets_the_requirement_sets_the_floor():
    by_slot = {
        "GPU": [_cand("GPU", "weak", 100_000, perf_tier=2), _cand("GPU", "ok", 400_000, perf_tier=6),
                _cand("GPU", "big", 900_000, perf_tier=9)],
        "CPU": [_cand("CPU", "cpu", 200_000, perf_tier=5)],
    }
    spec = _spec(1_000_000, {"GPU": {"perf_tier_min": 6}, "CPU": {"perf_tier_min": 4}})
    r = feasibility.assess(spec, by_slot)
    assert r["per_slot"] == {"GPU": 400_000, "CPU": 200_000}     # 100,000짜리는 tier 미달이라 못 쓴다
    assert r["estimated_min"] == 600_000
    assert r["level"] == "ok" and r["message"] is None


def test_floor_above_budget_is_infeasible_with_the_shortfall_in_the_message():
    by_slot = {"GPU": [_cand("GPU", "g", 900_000, perf_tier=8)], "CPU": [_cand("CPU", "c", 400_000, perf_tier=8)]}
    r = feasibility.assess(_spec(1_000_000, {"GPU": {"perf_tier_min": 7}, "CPU": {"perf_tier_min": 7}}), by_slot)
    assert r["level"] == "infeasible"
    assert r["shortfall"] == 300_000
    assert "1,300,000원" in r["message"] and "1,000,000원" in r["message"] and "300,000원" in r["message"]


def test_floor_close_to_budget_is_tight_not_infeasible():
    by_slot = {"GPU": [_cand("GPU", "g", 900_000, perf_tier=8)]}
    r = feasibility.assess(_spec(1_000_000, {"GPU": {"perf_tier_min": 7}}), by_slot)
    assert r["level"] == "tight" and r["shortfall"] == 0
    assert "90%" in r["message"]


def test_no_budget_means_nothing_to_compare():
    r = feasibility.assess(_spec(0, {"GPU": {"perf_tier_min": 7}}), {"GPU": [_cand("GPU", "g", 900_000, perf_tier=8)]})
    assert r["level"] == "ok" and r["message"] is None


def test_unknown_spec_is_pending_not_fail_so_it_still_counts_toward_the_floor():
    """정보 없음 ≠ 비호환 — perf_tier 값이 없는 후보도 후보다(하한이 부풀지 않게)."""
    by_slot = {"GPU": [_cand("GPU", "no-tier", 300_000), _cand("GPU", "tiered", 500_000, perf_tier=8)]}
    r = feasibility.assess(_spec(2_000_000, {"GPU": {"perf_tier_min": 7}}), by_slot)
    assert r["per_slot"]["GPU"] == 300_000


def test_slot_with_no_qualifying_candidate_is_reported_not_silently_zero():
    by_slot = {"GPU": [_cand("GPU", "weak", 100_000, perf_tier=1)]}
    r = feasibility.assess(_spec(1_000_000, {"GPU": {"perf_tier_min": 7}}), by_slot)
    assert r["unfillable"] == ["GPU"] and r["per_slot"] == {}
    assert "GPU" in r["message"]


# ── 기여도 ────────────────────────────────────────────────────────────────
def _rank(weights: dict, slots: dict) -> RankResult:
    return RankResult(weights_used=weights, slots=slots)


def _item(slot: str, key: str) -> BuildItem:
    return BuildItem(slot=slot, product_key=key, name=key, price=1, rank_from_3b=1)


def _build(*items: BuildItem) -> BuildResult:
    return BuildResult(list_id="t", items=list(items))


def test_contribution_follows_weight_times_axis_value_and_sums_to_100():
    rank = _rank({"가격": 0.5, "성능": 0.5}, {
        "GPU": {"ranked": [{"product_key": "g", "breakdown": {"가격": 0.2, "성능": 0.8}}]},
        "CPU": {"ranked": [{"product_key": "c", "breakdown": {"가격": 0.6, "성능": 0.4}}]},
    })
    out = _contribution(_build(_item("GPU", "g"), _item("CPU", "c")), rank)
    # 가격: 0.5*(0.2+0.6)=0.4 / 성능: 0.5*(0.8+0.4)=0.6
    assert out == {"가격": 40, "성능": 60}
    assert sum(out.values()) == 100


def test_contribution_rounding_never_breaks_the_100_total():
    rank = _rank({"가격": 1.0, "성능": 1.0, "리뷰": 1.0}, {
        "GPU": {"ranked": [{"product_key": "g", "breakdown": {"가격": 1.0, "성능": 1.0, "리뷰": 1.0}}]},
    })
    out = _contribution(_build(_item("GPU", "g")), rank)
    assert sum(out.values()) == 100 and sorted(out.values()) == [33, 33, 34]


def test_contribution_reads_parts_the_widened_search_took_from_outside_top_n():
    rank = _rank({"가격": 1.0}, {"GPU": {"ranked": [], "pool": [{"product_key": "g", "breakdown": {"가격": 0.5}}]}})
    assert _contribution(_build(_item("GPU", "g")), rank) == {"가격": 100}


def test_contribution_without_rank_is_empty_rather_than_invented():
    assert _contribution(_build(_item("GPU", "g")), None) == {}
    assert _contribution(_build(_item("GPU", "g")), _rank({}, {})) == {}


def test_negative_axis_value_does_not_push_another_axis_over_100():
    rank = _rank({"가격": 1.0, "밸런스": 1.0}, {"GPU": {"ranked": [{"product_key": "g", "breakdown": {"가격": 0.5, "밸런스": -0.5}}]}})
    assert _contribution(_build(_item("GPU", "g")), rank) == {"가격": 100, "밸런스": 0}


# ── 예산 남김 안내 ────────────────────────────────────────────────────────
def _totals(spent: int, over: bool = False) -> dict:
    return {"selected_price": spent, "over_budget": over}


def test_value_priority_that_leaves_a_lot_explains_why_and_offers_performance():
    notice = budget_notice(_totals(1_516_788), {"mode": "build", "budget_max": 2_000_000, "priority": "value"})
    assert notice["remaining"] == 483_212 and notice["spent"] == 1_516_788 and notice["suggest_priority"] == "performance"
    assert "1,516,788원" in notice["message"] and "483,212원" in notice["message"] and "가성비 우선" in notice["message"]
    assert "성능 우선" in notice["message"]


def test_quiet_priority_gets_its_own_reason():
    notice = budget_notice(_totals(1_000_000), {"mode": "build", "budget_max": 2_000_000, "priority": "quiet"})
    assert "저소음" in notice["message"]


def test_no_notice_when_the_leftover_is_small_or_priority_already_fills_the_budget():
    build = {"mode": "build", "budget_max": 2_000_000}
    assert budget_notice(_totals(1_800_000), {**build, "priority": "value"}) is None          # 10% 남음 — 흔한 정도
    assert budget_notice(_totals(1_700_000), {**build, "priority": "value"}) is not None      # 정확히 15% 는 안내
    assert budget_notice(_totals(1_000_000), {**build, "priority": "performance"}) is None    # 성능 우선은 채우는 쪽이다


def test_no_notice_for_upgrade_over_budget_or_missing_data():
    assert budget_notice(_totals(300_000), {"mode": "upgrade", "budget_max": 2_000_000, "priority": "value"}) is None
    assert budget_notice(_totals(2_500_000, over=True), {"mode": "build", "budget_max": 2_000_000, "priority": "value"}) is None
    assert budget_notice(None, {"mode": "build", "budget_max": 2_000_000, "priority": "value"}) is None
    assert budget_notice(_totals(1_000_000), {"mode": "build", "budget_max": None, "priority": "value"}) is None
    assert budget_notice(_totals(0), {"mode": "build", "budget_max": 2_000_000, "priority": "value"}) is None
