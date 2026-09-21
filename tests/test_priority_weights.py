"""[3-B] priority(성능/가성비/저소음)·noise_sensitive 가 순위에 반영된다.

회귀 배경: 엔진(stage2~4)이 priority 와 noise_sensitive 를 전혀 읽지 않아(결과 화면 라벨에만 쓰임)
"성능 우선"·"가성비"·"저소음"을 골라도 추천이 같았다. 가중치 값은 정책이라 여기서는 값 자체가 아니라
동작 원리를 검증한다: 조건이 없으면 점수가 그대로이고, 있으면 가중치가 바뀌며, 소음 축은
가중치가 있을 때만 계산되고, 잘못된 설정은 로드 시점에 거부된다."""
from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.engine import stage2_requirement, stage3b_rank
from src.repo.catalog_repo import _specs_from_row


def _ranking() -> dict:
    return stage2_requirement.load_computer_rules()["ranking"]


def _slots(**values) -> Slots:
    return Slots(category="computer", mode="build", objective_text="", values=values)


def _cand(slot, key, price, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=key, price=price, specs=specs)


@pytest.fixture(autouse=True)
def _no_review_signal(monkeypatch):
    monkeypatch.setattr(stage3b_rank, "_review_axis", lambda _: (0.5, []))


def _rank(slot, cands, budget=2_000_000, alloc=0.4, **values):
    spec = RequirementSpec(list_id="r", category="computer", mode="build", targets={slot: {}},
                           budget={"total": budget, "alloc": {slot: alloc}})
    return stage3b_rank.run(HardFilterResult(slots={slot: cands}), spec, _slots(**values), lambda _: None)


# ── 가중치 선택 ──────────────────────────────────────────────────────────────

def test_no_priority_and_no_noise_condition_keeps_the_base_weights():
    weights, notes = stage3b_rank._weights_for({}, _ranking())
    assert weights == _ranking()["weights"] and notes == []
    assert stage3b_rank._weights_for({"priority": None, "noise_sensitive": False}, _ranking()) == (weights, [])


@pytest.mark.parametrize("priority", ["performance", "value", "quiet"])
def test_each_priority_selects_its_own_weight_set(priority):
    weights, notes = stage3b_rank._weights_for({"priority": priority}, _ranking())
    assert weights == _ranking()["priority_weights"][priority]
    assert abs(sum(weights.values()) - 1) < 1e-9
    assert notes and priority in notes[0]


def test_priorities_move_the_weight_in_the_expected_direction():
    base, perf = _ranking()["weights"], _ranking()["priority_weights"]
    assert perf["performance"]["성능"] > base["성능"] > perf["value"]["성능"]
    assert perf["value"]["가격"] > base["가격"] > perf["performance"]["가격"]
    assert perf["quiet"]["소음"] > base["소음"] == perf["performance"]["소음"] == 0


def test_unknown_priority_falls_back_to_the_base_weights():
    assert stage3b_rank._weights_for({"priority": "nonsense"}, _ranking())[0] == _ranking()["weights"]


def test_noise_sensitive_guarantees_a_minimum_noise_weight_and_keeps_the_sum():
    floor = _ranking()["noise_sensitive_min_weight"]
    for priority in (None, "performance", "value"):
        weights, notes = stage3b_rank._weights_for({"priority": priority, "noise_sensitive": True}, _ranking())
        assert weights["소음"] == pytest.approx(floor)
        assert sum(weights.values()) == pytest.approx(1.0)
        assert any("소음 민감" in n for n in notes)


def test_noise_sensitive_shrinks_the_other_axes_in_proportion():
    before, _ = stage3b_rank._weights_for({"priority": "performance"}, _ranking())
    after, _ = stage3b_rank._weights_for({"priority": "performance", "noise_sensitive": True}, _ranking())
    ratios = {k: after[k] / before[k] for k in before if k != "소음" and before[k]}
    assert max(ratios.values()) - min(ratios.values()) < 1e-9 and max(ratios.values()) < 1


def test_noise_sensitive_does_not_lower_an_already_higher_noise_weight():
    quiet = _ranking()["priority_weights"]["quiet"]
    assert quiet["소음"] >= _ranking()["noise_sensitive_min_weight"]
    weights, _ = stage3b_rank._weights_for({"priority": "quiet", "noise_sensitive": True}, _ranking())
    assert weights == quiet


# ── 소음 축(대용값) ──────────────────────────────────────────────────────────

def _noise(slot, **specs):
    return stage3b_rank._noise_axis(_cand(slot, "k", 1, **specs), slot, _ranking()["noise_proxy"])


def test_lower_power_parts_score_as_quieter_and_the_axis_stays_in_range():
    assert _noise("CPU", tdp_w=65) > _noise("CPU", tdp_w=125) > _noise("CPU", tdp_w=170)
    assert _noise("GPU", power_w=115) > _noise("GPU", power_w=300) > _noise("GPU", power_w=575)
    for value in (_noise("CPU", tdp_w=1), _noise("CPU", tdp_w=999), _noise("GPU", power_w=1), _noise("GPU", power_w=9999)):
        assert 0.0 <= value <= 1.0


def test_cooler_type_orders_big_air_towers_above_low_profile():
    assert _noise("쿨러", cooling_type="Air (Dual-Tower)") > _noise("쿨러", cooling_type="Air (Low-Profile)")


@pytest.mark.parametrize("slot, specs", [
    ("CPU", {}), ("GPU", {}), ("쿨러", {}), ("쿨러", {"cooling_type": "Air (Passive)"}),   # 정보 없음·표에 없음
    ("RAM", {"capacity_gb": 32}), ("파워", {"efficiency_rating": "Titanium"}), ("케이스", {"max_gpu_len_mm": 400}),
])
def test_unknown_or_unrelated_inputs_are_neutral_not_invented(slot, specs):
    assert _noise(slot, **specs) == 0.5


def test_psu_efficiency_is_deliberately_not_a_noise_signal():
    # 넣었더니 저소음 요청이 1300W Titanium 파워를 골라 견적이 64만원 뛰었다 — 근거가 약해 뺐다.
    assert "psu_rating" not in _ranking()["noise_proxy"]


# ── _score / run ─────────────────────────────────────────────────────────────

def test_noise_axis_is_recorded_only_when_it_has_weight():
    cand = _cand("CPU", "c", 100_000, tdp_w=65, perf_tier=6)
    assert "소음" not in stage3b_rank._score(cand, 6.0, 100_000, "CPU", {}).breakdown
    quiet = _ranking()["priority_weights"]["quiet"]
    assert "소음" in stage3b_rank._score(cand, 6.0, 100_000, "CPU", {}, quiet).breakdown


def test_default_score_is_unchanged_by_the_new_axis():
    cand = _cand("CPU", "c", 100_000, tdp_w=65, perf_tier=6)
    scored = stage3b_rank._score(cand, 6.0, 100_000, "CPU", {})
    base = _ranking()["weights"]
    expected = sum(base[k] * v for k, v in scored.breakdown.items())
    assert scored.score == round(expected, 3)


def test_quiet_priority_ranks_the_lower_power_gpu_first_only_when_asked():
    hot = _cand("GPU", "hot", 500_000, power_w=400, perf_tier=6)
    cool = _cand("GPU", "cool", 500_000, power_w=115, perf_tier=6)
    quiet = _rank("GPU", [hot, cool], priority="quiet").slots["GPU"]["ranked"]
    assert [c["product_key"] for c in quiet][0] == "cool"
    assert quiet[0]["score"] > quiet[1]["score"]
    plain = _rank("GPU", [hot, cool]).slots["GPU"]["ranked"]
    assert plain[0]["score"] == plain[1]["score"]                        # 조건이 없으면 소음은 점수에 영향 없음


def test_performance_vs_value_flips_the_ranking_between_a_cheap_and_a_strong_part():
    cheap = _cand("GPU", "cheap", 400_000, perf_tier=6)
    strong = _cand("GPU", "strong", 600_000, perf_tier=9)
    first = lambda **v: _rank("GPU", [cheap, strong], purpose="game", **v).slots["GPU"]["ranked"][0]["product_key"]
    assert first(priority="performance") == "strong"
    assert first(priority="value") == "cheap"


def test_rank_result_reports_the_weights_actually_used():
    rank = _rank("GPU", [_cand("GPU", "g", 1, perf_tier=6)], priority="quiet", noise_sensitive=True)
    assert rank.weights_used == _ranking()["priority_weights"]["quiet"]
    assert rank.weight_adjustments and "quiet" in rank.weight_adjustments[0]
    assert _rank("GPU", [_cand("GPU", "g", 1, perf_tier=6)]).weight_adjustments == []


def test_cooling_type_reaches_candidate_specs():
    assert _specs_from_row("cooler", {"cooling_type": "Air (Dual-Tower)"})["cooling_type"] == "Air (Dual-Tower)"
    assert "cooling_type" not in _specs_from_row("cooler", {"cooling_type": None})


# ── 잘못된 설정은 로드 시점에 거부한다 ───────────────────────────────────────

@pytest.mark.parametrize("label, mutate", [
    ("가중치 합계", lambda r: r["priority_weights"]["quiet"].update(가격=0.9)),
    ("축 누락", lambda r: r["priority_weights"]["value"].pop("소음")),
    ("음수 가중치", lambda r: r["priority_weights"]["value"].update(가격=-0.1, 성능=0.75)),
    ("소음 최소 가중치 범위", lambda r: r.update(noise_sensitive_min_weight=1.0)),
    ("소음 범위 역전", lambda r: r["noise_proxy"].update(cpu_tdp_w=[200, 65])),
    ("쿨러 표 범위", lambda r: r["noise_proxy"].update(cooler_type={"Air (Dual-Tower)": 1.5})),
])
def test_invalid_priority_or_noise_config_is_rejected(tmp_path, monkeypatch, label, mutate):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    mutate(rules["ranking"])
    path = tmp_path / "computer_verification_rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError):
        stage2_requirement.load_computer_rules(path)
