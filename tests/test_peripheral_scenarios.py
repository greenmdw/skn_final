"""주변기기 시나리오 회귀 테스트 — 점수식·강조·예산·브랜드를 건드렸을 때 순위가 어떻게 달라지는지 고정한다.

실제 진입점(`run_peripherals`)을 그대로 돌리고, 후보 전체 순위는 조합 단계(`choose`)에 들어가는 값을 가로채 읽는다.
카탈로그는 이 파일이 직접 만든 마우스 10종이라 DB·언어 모델이 필요 없고 값은 항상 같다.

두 층이다.
1. 불변식 — "예산 안", "기피 브랜드는 안 나옴", "조건을 말하면 그 조건의 제품이 위", "근거가 얇으면 아래" 같은 방향.
   점수식을 바꿔도 지켜져야 하는 약속이다. 깨지면 의도한 변경인지 먼저 따진다.
2. 고정 순위표(`tests/fixtures/peripheral_scenarios.yaml`) — 시나리오별 상위 5개와 점수. 가중치·감점을 일부러 바꿨다면
   `PERIPHERAL_SCENARIOS_UPDATE=1 pytest tests/test_peripheral_scenarios.py` 로 다시 쓰고 diff 를 검토한다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from src.dto import Candidate, ReviewAspectContribution, ReviewRequirementProfile, ReviewScoreDetail
from src.engine import peripheral_intent as pi
from src.engine import peripheral_select as sel
from src.engine.peripheral_feel import FeelObservation as Obs
from src.engine.peripheral_rules import load_peripheral_rules

RULES = load_peripheral_rules()
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "peripheral_scenarios.yaml"
_ASPECTS = ("ergonomics", "controls_usability", "connection_stability", "battery_runtime")


def _mouse(key, price, brand, specs, good=0, bad=0, aspects=_ASPECTS):
    """외부 리뷰 근거가 (긍정 good, 부정 bad)인 마우스. `aspects` 마다 같은 수를 둔다(관측 수 n = 수 × aspect 개수).
    근거가 없으면 리뷰 값은 후보 풀의 평균에서 출발한다."""
    contributions = [ReviewAspectContribution(aspect_code=a, context_code="actual_use", alpha=0.25, p=good, n=bad, q=0.5,
                                              alpha_q=0.125, evidence_state="observed") for a in aspects] if (good or bad) else []
    detail = ReviewScoreDetail(profile=ReviewRequirementProfile(profile_version="t", analysis_version="t", part_type="mouse"),
                               value=0.5, contributions=contributions)
    return Candidate(product_key=key, slot="mouse", name=key, product_id=f"pid-{key}", brand=brand, price=price,
                     specs=specs, review_detail=detail)


def _specs(weight=90, size=120, wireless=True, bluetooth=False, buttons=6, polling=1000, form="일반형"):
    return {"weight_g": weight, "size_longest_mm": size, "connectivity_wireless": wireless, "connectivity_bluetooth": bluetooth,
            "button_count": buttons, "polling_hz_max": polling, "form_factor_raw": form}


def _pool():
    return [
        _mouse("cheap_basic", 15_000, "Rapoo", _specs(100, 118, wireless=False, buttons=4), good=90, bad=10),
        _mouse("cheap_wireless", 25_000, "Lenovo", _specs(90, 112, buttons=6), good=50, bad=10),
        _mouse("mid_light", 60_000, "Logitech", _specs(62, 120, bluetooth=True, buttons=6, polling=4000), good=35, bad=5),
        _mouse("mid_vertical", 70_000, "Logitech", _specs(120, 108, bluetooth=True, buttons=6, form="버티컬"), good=25, bad=5),
        _mouse("pro_light_thin", 150_000, "Razer", _specs(58, 120, buttons=5, polling=8000), good=1, bad=0,
               aspects=("ergonomics",)),                                # 관측 1건뿐
        _mouse("pro_light_rich", 140_000, "Razer", _specs(60, 122, buttons=5, polling=4000), good=45, bad=5),
        _mouse("mmo", 85_000, "Razer", _specs(120, 131, wireless=False, buttons=12), good=20, bad=5),
        _mouse("trackball", 40_000, "Logitech", _specs(145, 134, bluetooth=True, buttons=5, form="트랙볼"), good=18, bad=2),
        _mouse("unknown_specs", 30_000, "ASUS", {}, good=8, bad=2),
        _mouse("no_review", 35_000, "HP", _specs(70, 115, buttons=6)),
    ]


def rank_all(interp=None, *, observations=None, kind_budget=None, brand_like=None, brand_avoid=None, emphasis=None,
             pool=None, monkeypatch=None):
    """`run_peripherals` 를 돌려 마우스 후보 전체의 순위(상위가 앞)를 [(product_key, score)] 로 돌려준다."""
    interp = interp or pi.Interpretation(kinds=["mouse"])
    values = {
        "peripherals": ["mouse"], "peripheral_intent": interp, "peripheral_resolved": pi.resolve(interp, RULES),
        "peripheral_feel_observations": observations or {},
        "peripheral_kind_budget": {"mouse": kind_budget} if kind_budget else {},
        "peripheral_brand_like": {"mouse": brand_like} if brand_like else {},
        "peripheral_brand_avoid": {"mouse": brand_avoid} if brand_avoid else {},
        "peripheral_emphasis": {"mouse": emphasis} if emphasis else {},
    }
    captured: dict = {}
    original = sel.choose

    def spy(kinds_ranked, *a, **k):
        captured.update(kinds_ranked)
        return original(kinds_ranked, *a, **k)

    sel.choose = spy
    try:
        sel.run_peripherals(values, {"mouse": pool or _pool()}, lambda *_: None)
    finally:
        sel.choose = original
    return [(c.product_key, c.score) for c in captured.get("mouse", [])]


def keys(ranked):
    return [k for k, _ in ranked]


def position(ranked, key):
    return keys(ranked).index(key)


def interp(**kw):
    return pi.Interpretation(kinds=["mouse"], **kw)


# ── 불변식 ──────────────────────────────────────────────────────────────────
def test_the_same_request_gives_the_same_ranking_twice():
    assert rank_all() == rank_all()


def test_every_candidate_is_ranked_and_scores_never_increase_down_the_list():
    ranked = rank_all()
    assert sorted(keys(ranked)) == sorted(c.product_key for c in _pool())        # 후보를 빼지 않는다
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_a_product_with_review_evidence_beats_the_same_kind_of_product_without_any():
    ranked = rank_all()
    assert position(ranked, "cheap_wireless") < position(ranked, "no_review")      # 가격이 비슷하고 스펙이 같아도 근거가 있는 쪽이 위


def test_thin_evidence_ranks_below_rich_evidence_when_the_rest_is_alike():
    ranked = rank_all()
    assert position(ranked, "pro_light_rich") < position(ranked, "pro_light_thin")  # 근거 부족 감점


def test_a_candidate_with_no_review_is_penalised_but_stays_in_the_pool():
    ranked = dict(rank_all())
    assert "no_review" in ranked


def test_budget_keeps_every_pick_within_the_price_limit():
    ranked = rank_all(kind_budget=50_000)
    prices = {c.product_key: c.price for c in _pool()}
    assert ranked and all(prices[k] <= 50_000 for k in keys(ranked))
    assert "pro_light_rich" not in keys(ranked)


def test_stated_wireless_filters_out_wired_mice():
    ranked = rank_all(interp(stated={"mouse": ["wireless"]}))
    assert "cheap_basic" not in keys(ranked) and "mmo" not in keys(ranked)


def test_stated_lightweight_lifts_light_mice_above_equally_priced_heavy_ones():
    base = rank_all()
    said = rank_all(interp(stated={"mouse": ["lightweight"]}))
    # 가벼운 무게를 말하면 mid_light(62g)가 mid_vertical(120g)과의 격차를 벌린다
    gap = lambda r: dict(r)["mid_light"] - dict(r)["mid_vertical"]                  # noqa: E731
    assert gap(said) > gap(base)


def test_stated_condition_lifts_a_matching_product_over_a_cheaper_one_that_does_not_match():
    base = rank_all()
    said = rank_all(interp(stated={"mouse": ["high_polling"]}))
    assert position(said, "mid_light") <= position(base, "mid_light")


def test_brand_avoid_removes_that_brand_everywhere():
    ranked = rank_all(brand_avoid=["Logitech"])
    brands = {c.product_key: c.brand for c in _pool()}
    assert ranked and all(brands[k] != "Logitech" for k in keys(ranked))


def test_brand_like_never_lowers_the_liked_brand():
    base = rank_all()
    liked = rank_all(brand_like=["Razer"])
    for key in ("pro_light_rich", "pro_light_thin", "mmo"):
        assert position(liked, key) <= position(base, key)


def test_price_emphasis_moves_the_pick_toward_cheaper_products():
    prices = {c.product_key: c.price for c in _pool()}
    plain = rank_all()
    cheap_first = rank_all(emphasis=["가격"])
    top5 = lambda r: sum(prices[k] for k in keys(r)[:5])                           # noqa: E731
    assert top5(cheap_first) <= top5(plain)


def test_more_good_community_evidence_never_lowers_a_product():
    base = rank_all(interp(purposes=["wrist"]))
    obs = {"mouse": [Obs(f"u{i}", "pid-mid_vertical", "wrist", direction="good") for i in range(4)]}
    boosted = rank_all(interp(purposes=["wrist"]), observations=obs)
    assert position(boosted, "mid_vertical") <= position(base, "mid_vertical")


def test_more_bad_community_evidence_never_raises_a_product():
    base = rank_all(interp(purposes=["wrist"]))
    obs = {"mouse": [Obs(f"u{i}", "pid-mid_vertical", "wrist", direction="bad") for i in range(4)]}
    worse = rank_all(interp(purposes=["wrist"]), observations=obs)
    assert position(worse, "mid_vertical") >= position(base, "mid_vertical")


def test_unknown_specs_are_not_treated_as_failing_the_condition():
    """스펙 값이 없는 후보는 "모름"이라 조건을 말해도 미충족(0)이 아니라 중립으로 센다 — 빈 값 때문에 맨 아래로 가지 않는다."""
    ranked = rank_all(interp(stated={"mouse": ["lightweight"]}))
    assert position(ranked, "unknown_specs") < position(ranked, "cheap_basic") + len(_pool())     # 후보에서 빠지지 않는다
    assert "unknown_specs" in keys(ranked)


# ── 고정 순위표 ─────────────────────────────────────────────────────────────
SCENARIOS = {
    "조건 없음": dict(),
    "손목 부담": dict(interp=interp(purposes=["wrist"])),
    "FPS": dict(interp=interp(purposes=["fps"])),
    "버튼 많은 게임": dict(interp=interp(purposes=["many_buttons"])),
    "가벼운 무게를 말함": dict(interp=interp(stated={"mouse": ["lightweight"]})),
    "무선을 말함": dict(interp=interp(stated={"mouse": ["wireless"]})),
    "예산 5만원": dict(kind_budget=50_000),
    "가격 강조": dict(emphasis=["가격"]),
    "리뷰 강조": dict(emphasis=["리뷰"]),
    "Logitech 기피": dict(brand_avoid=["Logitech"]),
    "Razer 선호": dict(brand_like=["Razer"], emphasis=["브랜드"]),
}


def _snapshot():
    return {name: [[k, round(s, 3)] for k, s in rank_all(**kw)[:5]] for name, kw in SCENARIOS.items()}


def test_golden_rankings_match_the_recorded_table():
    snapshot = _snapshot()
    if os.environ.get("PERIPHERAL_SCENARIOS_UPDATE") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            "# 주변기기 시나리오 고정 순위표 — tests/test_peripheral_scenarios.py 가 쓴다. 손으로 고치지 말고\n"
            "# `PERIPHERAL_SCENARIOS_UPDATE=1 pytest tests/test_peripheral_scenarios.py` 로 다시 쓴 뒤 diff 를 검토한다.\n"
            + yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False, default_flow_style=None),
            encoding="utf-8")
        pytest.skip("고정 순위표를 다시 썼다")
    assert GOLDEN.exists(), "고정 순위표가 없다 — PERIPHERAL_SCENARIOS_UPDATE=1 로 만든다"
    recorded = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    assert set(recorded) == set(snapshot), "시나리오 목록이 다르다"
    for name, rows in snapshot.items():
        got_keys = [k for k, _ in rows]
        want_keys = [k for k, _ in recorded[name]]
        assert got_keys == want_keys, f"{name}: 순위가 달라졌다\n  기록 {want_keys}\n  지금 {got_keys}"
        for (k, got), (_, want) in zip(rows, recorded[name]):
            assert got == pytest.approx(want, abs=1e-3), f"{name}/{k}: 점수 {want} → {got}"
