"""[5] 기여도 실계산 — _contribution 이 [3-B] breakdown × rank.weights_used 를 [3-B] 축 이름 그대로 낸다.

축을 가격/성능/호환성 3축으로 묶지 않는다 — 결과 화면(ContributionCard)과 HTTP 계약이 가격·성능·밸런스·리뷰·호환여유를 쓴다.

고정값(41/33/26)을 지어내지 않는다는 원칙(docs/decisions, E4) 을 확인한다.
"""
from __future__ import annotations

from src.dto import BuildItem, BuildResult, RankResult
from src.engine import stage5_explain as s5


def _build(*items: BuildItem) -> BuildResult:
    return BuildResult(list_id="L", items=list(items), totals={"price": 0}, budget={"max": 0})


def _rank(weights_used: dict, slots: dict) -> RankResult:
    return RankResult(slots=slots, weights_used=weights_used)


def test_price_only_weight_gives_all_contribution_to_price():
    build = _build(BuildItem(slot="CPU", product_key="x", name="X", price=1))
    rank = _rank(
        {"가격": 1.0, "성능": 0.0, "밸런스": 0.0, "호환여유": 0.0, "리뷰": 0.0},
        {"CPU": {"ranked": [{"product_key": "x",
                             "breakdown": {"가격": 1.0, "성능": 0.5, "밸런스": 0.3, "호환여유": 0.2}}]}},
    )
    assert s5._contribution(build, rank) == {"가격": 100, "성능": 0, "밸런스": 0, "호환여유": 0}


def test_balance_and_compat_margin_stay_separate_axes():
    build = _build(BuildItem(slot="GPU", product_key="y", name="Y", price=1))
    rank = _rank(
        {"가격": 0.0, "성능": 0.0, "밸런스": 0.5, "호환여유": 0.5},
        {"GPU": {"ranked": [{"product_key": "y",
                             "breakdown": {"가격": 1.0, "성능": 1.0, "밸런스": 0.4, "호환여유": 0.6}}]}},
    )
    assert s5._contribution(build, rank) == {"가격": 0, "성능": 0, "밸런스": 40, "호환여유": 60}


def test_review_axis_is_included_as_its_own_axis():
    # 결정 0001 은 리뷰 단위 진위 판정을 금지할 뿐 랭킹의 리뷰 축은 허용한다 — 점수에 든 만큼 보여준다.
    build = _build(BuildItem(slot="CPU", product_key="x", name="X", price=1))
    rank = _rank(
        {"가격": 0.0, "성능": 0.0, "밸런스": 0.0, "호환여유": 0.0, "리뷰": 1.0},
        {"CPU": {"ranked": [{"product_key": "x", "breakdown": {"리뷰": 0.75}}]}},
    )
    assert s5._contribution(build, rank) == {"리뷰": 100}


def test_rank_none_gives_empty_dict():
    build = _build(BuildItem(slot="CPU", product_key="x", name="X", price=1))
    assert s5._contribution(build, None) == {}


def test_no_matching_candidate_found_gives_empty_dict():
    build = _build(BuildItem(slot="CPU", product_key="missing", name="X", price=1))
    rank = _rank(
        {"가격": 1.0},
        {"CPU": {"ranked": [{"product_key": "other", "breakdown": {"가격": 1.0}}]}},
    )
    assert s5._contribution(build, rank) == {}


def test_falls_back_to_pool_when_not_in_ranked():
    build = _build(BuildItem(slot="CPU", product_key="x", name="X", price=1))
    rank = _rank(
        {"가격": 1.0, "성능": 0.0, "밸런스": 0.0, "호환여유": 0.0},
        {"CPU": {"ranked": [{"product_key": "other", "breakdown": {"가격": 1.0}}],
                 "pool": [{"product_key": "other", "breakdown": {"가격": 1.0}},
                          {"product_key": "x", "breakdown": {"가격": 1.0}}]}},
    )
    assert s5._contribution(build, rank) == {"가격": 100}


def test_result_sums_to_100_including_rounding_remainder_case():
    build = _build(
        BuildItem(slot="CPU", product_key="a", name="A", price=1),
    )
    # 세 축이 정확히 1/3씩 나오도록 설계 — 단순 반올림이면 99 또는 101이 될 수 있는 경계 사례.
    rank = _rank(
        {"가격": 1 / 3, "성능": 1 / 3, "밸런스": 1 / 3, "호환여유": 0.0},
        {"CPU": {"ranked": [{"product_key": "a",
                             "breakdown": {"가격": 1.0, "성능": 1.0, "밸런스": 1.0, "호환여유": 0.0}}]}},
    )
    result = s5._contribution(build, rank)
    assert sum(result.values()) == 100
    assert set(result) == {"가격", "성능", "밸런스", "호환여유"}


def test_negative_balance_breakdown_is_clamped_to_zero_not_negative_share():
    # 밸런스 축(1 - |tier-ideal|/4)은 클램프가 없어 음수가 될 수 있다 — 음수를 그대로 더하면
    # 밸런스가 음수 퍼센트로 나오거나 다른 축이 100%를 넘는다. 0으로 클램프해 모든 축이 0 이상,
    # 합은 항상 100이어야 한다.
    build = _build(BuildItem(slot="CPU", product_key="a", name="A", price=1))
    rank = _rank(
        {"가격": 0.5, "성능": 0.0, "밸런스": 0.5, "호환여유": 0.0},
        {"CPU": {"ranked": [{"product_key": "a",
                             "breakdown": {"가격": 1.0, "성능": 0.0, "밸런스": -0.5, "호환여유": 0.0}}]}},
    )
    result = s5._contribution(build, rank)
    assert all(v >= 0 for v in result.values())
    assert sum(result.values()) == 100


def test_run_logs_no_rank_info_when_rank_missing(caplog=None):
    from src.dto import VerificationResult

    logs: list[str] = []
    build = _build(BuildItem(slot="CPU", product_key="x", name="X", price=1))
    e = s5.run(build, VerificationResult(list_id="L", category="computer", mode="set"),
              logs.append, rank=None)
    assert e.contribution == {}
    assert any("기여도: (순위 정보 없음)" in line for line in logs)
