"""체감 적합도 R 계산(개발_확정사양.md 6장) — DB 없이 도는 순수 계산 테스트.

식을 손으로 계산한 값과 맞는지, 세는 규칙(한 작성자 × 한 제품 × 한 속성 = 한 표)과 같은 조건 묶음, 성향(갈림·불일치),
근거가 없을 때의 동작, 순위 축에 연결되는지를 확인한다."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest
import yaml

from src.dto import (
    Candidate, ReviewAspectContribution, ReviewRequirementProfile, ReviewScoreDetail,
)
from src.engine import peripheral_intent as pi
from src.engine import peripheral_rules as pr
from src.engine.peripheral_feel import FeelObservation as Obs
from src.engine.peripheral_feel import compute_feel, select_corpus
from src.engine.peripheral_select import rank_candidates

RULES = pr.load_peripheral_rules()
CFG = RULES["feel"]
K, KB = CFG["k"], CFG["kb"]


def _cand(key: str, kind: str = "keyboard", price: int = 100_000, **external: tuple[int, int]) -> Candidate:
    """external: {외부 큰 속성 코드: (긍정, 부정)}"""
    contributions = [
        ReviewAspectContribution(aspect_code=a, context_code="actual_use", alpha=0.2, p=p, n=n, q=0.5, alpha_q=0.1,
                                 evidence_state="observed")
        for a, (p, n) in external.items()
    ]
    detail = ReviewScoreDetail(
        profile=ReviewRequirementProfile(profile_version="t", analysis_version="t", part_type=kind),
        value=0.5, contributions=contributions,
    )
    return Candidate(product_key=key, slot=kind, name=key, product_id=f"pid-{key}", price=price, review_detail=detail)


def _feel(kind, pool, targets, interp=None, observations=(), resolved=None):
    interp = interp or pi.Interpretation(kinds=[kind])
    if resolved is None:
        resolved = pi.resolve(interp, RULES).get(kind)
    return compute_feel(kind, pool, targets, interp, resolved, observations, RULES)


def _attr(detail, code):
    return next(a for a in detail.attributes if a.code == code)


# ── 출발값: 외부 리뷰만 있을 때 ────────────────────────────────────────────
def test_start_value_follows_the_formula_without_community_evidence():
    a = _cand("A", typing_noise=(10, 2))
    b = _cand("B", typing_noise=(2, 10))
    out = _feel("keyboard", [a, b], [a, b])
    m = 12 / 24
    k0 = CFG["k0"]["keyboard"]["typing_noise"]
    ext_a = (10 + k0 * m) / (12 + k0)
    # 커뮤니티 근거가 없으면 B = m 이라 Q0 = 외부 점수
    assert _attr(out["A"], "key_noise").value == pytest.approx(ext_a, abs=1e-3)
    assert _attr(out["A"], "key_noise").state == "external_only"
    assert out["A"].basis == "external_only"
    assert out["A"].value > out["B"].value


def test_attribute_without_external_aspect_starts_at_neutral_m():
    a = _cand("A", typing_noise=(10, 2))
    out = _feel("keyboard", [a], [a])
    durability = _attr(out["A"], "durability")      # external: null
    assert durability.value == pytest.approx(CFG["default_m"])
    assert durability.state == "no_evidence"


def test_alphas_sum_to_one_and_are_equal_without_purposes():
    a = _cand("A")
    out = _feel("keyboard", [a], [a])
    alphas = [d.alpha for d in out["A"].attributes]
    assert sum(alphas) == pytest.approx(1.0, abs=1e-3)
    assert max(alphas) == pytest.approx(min(alphas), abs=1e-3)
    assert "looks" not in {d.code for d in out["A"].attributes}          # 외관 만족은 디자인을 말했을 때만


def test_purpose_boost_raises_alpha_of_named_attributes_only():
    a = _cand("A")
    interp = pi.Interpretation(kinds=["keyboard"], purposes=["numbers"])
    out = _feel("keyboard", [a], [a], interp)
    layout, hollow = _attr(out["A"], "layout"), _attr(out["A"], "hollow")
    assert layout.alpha == pytest.approx(hollow.alpha * CFG["purpose_boost"], abs=1e-3)
    assert sum(d.alpha for d in out["A"].attributes) == pytest.approx(1.0, abs=1e-3)


def test_quiet_situation_boosts_sound_attributes():
    a = _cand("A")
    interp = pi.Interpretation(kinds=["keyboard"], situations=["quiet_place"])
    out = _feel("keyboard", [a], [a], interp)
    assert _attr(out["A"], "key_noise").alpha == pytest.approx(_attr(out["A"], "software").alpha * CFG["purpose_boost"], abs=1e-3)


def test_design_situation_adds_looks_and_boosts_build():
    a = _cand("A")
    interp = pi.Interpretation(kinds=["keyboard"], situations=["design"])
    out = _feel("keyboard", [a], [a], interp)
    assert "looks" in {d.code for d in out["A"].attributes}
    assert _attr(out["A"], "build").alpha > _attr(out["A"], "software").alpha


# ── 커뮤니티 근거: 두 묶음 ────────────────────────────────────────────────
def _quiet_interp():
    return pi.Interpretation(kinds=["keyboard"], situations=["quiet_place"])


def test_two_stage_blend_matches_hand_calculation():
    a = _cand("A", typing_noise=(10, 2))
    b = _cand("B", typing_noise=(2, 10))
    quiet = frozenset({"quiet_place"})
    obs = [
        Obs("u1", "pid-A", "key_noise", direction="good", situations=quiet),
        Obs("u2", "pid-A", "key_noise", direction="good", situations=quiet),
        Obs("u3", "pid-A", "key_noise", direction="good", situations=quiet),
        Obs("u4", "pid-A", "key_noise", direction="bad"),
        Obs("u5", "pid-A", "key_noise", direction="bad"),
    ]
    out = _feel("keyboard", [a, b], [a], _quiet_interp(), obs)
    m = 0.5
    k0 = CFG["k0"]["keyboard"]["typing_noise"]
    ext = (10 + k0 * m) / (12 + k0)
    base = (3 + KB * m) / (5 + KB)                       # B: 커뮤니티 전체 긍정 3, 평가 5
    q0 = base + (ext - m)
    q_rest = (0 + K * q0) / (2 + K)
    expected = (3 + K * q_rest) / (3 + K)
    detail = _attr(out["A"], "key_noise")
    assert detail.value == pytest.approx(expected, abs=1e-3)
    assert (detail.same_good, detail.same_bad, detail.rest_good, detail.rest_bad) == (3, 0, 0, 2)
    assert detail.state == "same_condition" and detail.split is True        # 2/5 가 적은 쪽 ≥ 1/4
    assert out["A"].basis == "community"


def test_without_requester_condition_a_single_group_is_used():
    a = _cand("A", typing_noise=(10, 2))
    obs = [Obs(f"u{i}", "pid-A", "key_noise", direction="bad") for i in range(4)]
    plain = _feel("keyboard", [a], [a], pi.Interpretation(kinds=["keyboard"]), obs)
    d = _attr(plain["A"], "key_noise")
    assert (d.same_good, d.same_bad) == (0, 0) and d.rest_bad == 4
    assert d.state == "other_condition"


def test_other_condition_votes_only_move_the_value_through_the_rest_group():
    a = _cand("A")
    obs = [Obs(f"u{i}", "pid-A", "key_noise", direction="bad") for i in range(6)]
    with_quiet = _feel("keyboard", [a], [a], _quiet_interp(), obs)
    d = _attr(with_quiet["A"], "key_noise")
    assert d.state == "other_condition"
    base = (0 + KB * 0.5) / (6 + KB)
    expected = (0 + K * base) / (6 + K)                  # 같은 조건 묶음이 비면 Q = Q나머지
    assert d.value == pytest.approx(expected, abs=1e-3)


# ── 세는 규칙 ──────────────────────────────────────────────────────────────
def test_one_vote_per_author_product_attribute_latest_wins():
    a = _cand("A")
    obs = [
        Obs("u1", "pid-A", "wrist", direction="bad", written_at=datetime(2026, 1, 1)),
        Obs("u1", "pid-A", "wrist", direction="good", written_at=datetime(2026, 6, 1)),
        Obs("u2", "pid-A", "wrist", direction="good"),
    ]
    d = _attr(_feel("keyboard", [a], [a], observations=obs)["A"], "wrist")
    assert (d.rest_good, d.rest_bad) == (2, 0)


def test_conflicting_situational_evaluations_use_the_one_matching_the_requester():
    a = _cand("A")
    obs = [
        Obs("u1", "pid-A", "wrist", direction="good", evaluated_in=frozenset({"office"})),
        Obs("u1", "pid-A", "wrist", direction="bad", evaluated_in=frozenset({"fps"})),
    ]
    interp = pi.Interpretation(kinds=["keyboard"], purposes=["fps"])
    d = _attr(_feel("keyboard", [a], [a], interp, obs)["A"], "wrist")
    assert (d.rest_good + d.same_good, d.rest_bad + d.same_bad) == (0, 1)


def test_conflicting_evaluations_without_a_matching_situation_are_not_counted():
    a = _cand("A")
    obs = [
        Obs("u1", "pid-A", "wrist", direction="good", evaluated_in=frozenset({"office"})),
        Obs("u1", "pid-A", "wrist", direction="bad", evaluated_in=frozenset({"travel"})),
    ]
    d = _attr(_feel("keyboard", [a], [a], observations=obs)["A"], "wrist")
    assert d.rest_good == d.rest_bad == d.same_good == d.same_bad == 0
    assert d.situational == 1 and d.state == "no_evidence"


def test_mixed_direction_is_not_a_vote():
    a = _cand("A")
    obs = [Obs("u1", "pid-A", "wrist", direction="mixed")]
    d = _attr(_feel("keyboard", [a], [a], observations=obs)["A"], "wrist")
    assert d.state == "no_evidence"


def test_real_posts_replace_example_posts_for_the_kind():
    obs = [Obs("e1", "pid-A", "wrist", direction="bad", is_example=True),
           Obs("r1", "pid-A", "wrist", direction="good")]
    used, basis = select_corpus(obs)
    assert [o.author_id for o in used] == ["r1"] and basis == "community"
    used, basis = select_corpus([obs[0]])
    assert [o.author_id for o in used] == ["e1"] and basis == "example"
    assert select_corpus([]) == ([], "external_only")


def test_example_only_corpus_is_marked_as_example_basis():
    a = _cand("A")
    obs = [Obs("e1", "pid-A", "wrist", direction="good", is_example=True)]
    assert _feel("keyboard", [a], [a], observations=obs)["A"].basis == "example"


# ── 성향 ──────────────────────────────────────────────────────────────────
def _taste_interp():
    # 키보드 numbers 목적은 "소리 조용한 쪽" 취향을 푼다 → sound_volume 축에 요청자의 쪽이 생긴다
    return pi.Interpretation(kinds=["keyboard"], purposes=["numbers"])


def test_taste_not_chosen_is_left_out_and_alpha_renormalised():
    a = _cand("A")
    out = _feel("keyboard", [a], [a], pi.Interpretation(kinds=["keyboard"]))
    assert all(d.type == "rating" for d in out["A"].attributes)


def test_taste_fit_uses_neutral_start_and_counts_same_side():
    a = _cand("A")
    obs = [Obs(f"u{i}", "pid-A", "sound_volume", side="quiet") for i in range(3)]
    d = _attr(_feel("keyboard", [a], [a], _taste_interp(), obs)["A"], "sound_volume")
    assert d.type == "taste" and d.value == pytest.approx((3 + K * 0.5) / (3 + K), abs=1e-3)
    assert d.split is False and d.mismatch is False


def test_taste_without_evidence_is_neutral():
    a = _cand("A")
    d = _attr(_feel("keyboard", [a], [a], _taste_interp())["A"], "sound_volume")
    assert d.value == pytest.approx(0.5) and d.state == "no_evidence"


def test_taste_split_and_mismatch_are_judged_separately():
    a = _cand("A")
    split = [Obs("u1", "pid-A", "sound_volume", side="quiet"), Obs("u2", "pid-A", "sound_volume", side="quiet"),
             Obs("u3", "pid-A", "sound_volume", side="quiet"), Obs("u4", "pid-A", "sound_volume", side="loud")]
    d = _attr(_feel("keyboard", [a], [a], _taste_interp(), split)["A"], "sound_volume")
    assert d.split is True and d.mismatch is False
    mismatch = [Obs(f"u{i}", "pid-A", "sound_volume", side="loud") for i in range(9)] + [
        Obs("x", "pid-A", "sound_volume", side="quiet")]
    d = _attr(_feel("keyboard", [a], [a], _taste_interp(), mismatch)["A"], "sound_volume")
    assert d.split is False and d.mismatch is True
    assert d.value < 0.5


# ── 순위 축 연결 ──────────────────────────────────────────────────────────
def test_feel_value_replaces_the_review_axis_in_ranking():
    a = _cand("A", price=100_000, typing_noise=(10, 2))
    b = _cand("B", price=100_000, typing_noise=(2, 10))
    detail = _feel("keyboard", [a, b], [a, b])
    a2 = a.model_copy(update={"feel_detail": detail["A"]})
    b2 = b.model_copy(update={"feel_detail": detail["B"]})
    req = __import__("src.dto", fromlist=["PeripheralRequirement"]).PeripheralRequirement(kind="keyboard")
    weights = {"가격": 0.0, "선호적합": 0.0, "데이터충실": 0.0, "리뷰": 1.0}
    ranked = rank_candidates("keyboard", req, [b2, a2], weights)
    assert [c.product_key for c in ranked] == ["A", "B"]
    assert ranked[0].breakdown["리뷰"] == detail["A"].value


def test_ranking_falls_back_to_external_review_value_without_feel():
    a = _cand("A")
    req = __import__("src.dto", fromlist=["PeripheralRequirement"]).PeripheralRequirement(kind="keyboard")
    ranked = rank_candidates("keyboard", req, [a], {"가격": 0.0, "선호적합": 0.0, "데이터충실": 0.0, "리뷰": 0.0})
    assert ranked[0].breakdown["리뷰"] == 0.5          # review_detail.value


def test_run_peripherals_ranks_by_feel_when_review_axis_has_weight(monkeypatch):
    """종류 전체 흐름: 관측 → R → 순위. 가중치를 올리면 사용기에서 더 좋게 평가받은 제품이 1위가 된다."""
    from src.engine import peripheral_select as sel

    rules = deepcopy(RULES)
    rules["ranking"]["keyboard"]["weights"] = {"가격": 0.0, "선호적합": 0.0, "데이터충실": 0.0, "리뷰": 1.0}
    monkeypatch.setattr(sel, "load_peripheral_rules", lambda *a, **k: rules)
    a = _cand("A", typing_noise=(5, 5))
    b = _cand("B", typing_noise=(5, 5))
    observations = {"keyboard": [Obs("u1", "pid-B", "wrist", direction="good"), Obs("u2", "pid-B", "wrist", direction="good"),
                                 Obs("u3", "pid-A", "wrist", direction="bad")]}
    values = {"peripherals": ["keyboard"], "peripheral_intent": pi.Interpretation(kinds=["keyboard"]),
              "peripheral_resolved": pi.resolve(pi.Interpretation(kinds=["keyboard"]), rules),
              "peripheral_feel_observations": observations}
    result = sel.run_peripherals(values, {"keyboard": [a, b]}, lambda *_: None)
    assert result.picks[0].candidate.product_key == "B"
    assert result.picks[0].candidate.feel_detail.value > result.picks[0].alternatives[0].feel_detail.value


def test_payload_reports_the_review_weight_it_actually_used():
    from src.engine.peripheral_payload import _review_note, _review_weight

    assert _review_weight("keyboard", RULES) == RULES["ranking"]["keyboard"]["weights"]["리뷰"]
    assert "반영되지 않았" in _review_note(0.0)
    assert "반영되었" in _review_note(0.2)


def test_review_axis_is_on_in_every_kind_and_price_with_preference_stay_central():
    """체감 R 이 순위에 반영된다(잠정 가중치). 가격과 스펙 선호가 여전히 합쳐 과반을 차지한다."""
    for kind in ("monitor", "keyboard", "mouse", "speaker"):
        weights = RULES["ranking"][kind]["weights"]
        assert 0 < weights["리뷰"] <= 0.35
        assert weights["가격"] + weights["선호적합"] > 0.5
        assert sum(weights.values()) == pytest.approx(1.0)


# ── 설정 ──────────────────────────────────────────────────────────────────
def _write(tmp_path, rules):
    path = tmp_path / "peripherals.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_every_external_aspect_exists_in_review_profiles():
    profiles = yaml.safe_load(open("config/review_aspect_profiles.yaml", encoding="utf-8"))["part_types"]
    for kind, table in CFG["attributes"].items():
        for code, entry in table.items():
            if entry["type"] == "rating" and entry["external"]:
                assert entry["external"] in profiles[kind], (kind, code, entry["external"])
        assert set(CFG["k0"].get(kind, {})) <= set(profiles[kind])


def test_every_purpose_feel_and_taste_name_points_at_an_attribute():
    """5장 목적 표가 말하는 체감·성향 이름은 모두 속성(4.2)·성향 축(4.3)을 가리킨다. 가리키지 못하는 이름이 생기면
    점수에 들어가지 못하고 조용히 사라지므로, 표에 이름을 더할 때 속성도 함께 더해야 한다."""
    for kind, table in CFG["attributes"].items():
        aliases = {a for e in table.values() for a in e["aliases"]}
        tastes = {t for e in table.values() if e["type"] == "taste" for t in e["taste_labels"]}
        feel = {f for p in RULES["purposes"][kind].values() for f in p["feel"]}
        taste = {t for p in RULES["purposes"][kind].values() for t in p["taste"]}
        assert feel - aliases == set(), (kind, feel - aliases)
        assert taste - tastes == set(), (kind, taste - tastes)


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r["feel"].update(k=0), "양수"),
    (lambda r: r["feel"].update(split_ratio=1.5), "0과 1 사이"),
    (lambda r: r["feel"]["attributes"]["mouse"]["grip"].update(group="elsewhere"), "type/group"),
    (lambda r: r["feel"]["attributes"]["mouse"]["size_feel"].update(taste_labels={"x": "huge"}), "sides"),
    (lambda r: r["feel"]["attributes"]["mouse"]["grip"].pop("aliases"), "키 오류"),
])
def test_invalid_feel_config_is_rejected(tmp_path, mutate, match):
    rules = deepcopy(RULES)
    mutate(rules)
    with pytest.raises(pr.PeripheralRuleError, match=match):
        pr.load_peripheral_rules(_write(tmp_path, rules))
