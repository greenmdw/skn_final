"""[3-B] priority(성능/가성비/저소음)·noise_sensitive 가 순위에 반영된다.

회귀 배경: 엔진(stage2~4)이 priority 와 noise_sensitive 를 전혀 읽지 않아(결과 화면 라벨에만 쓰임)
"성능 우선"·"가성비"·"저소음"을 골라도 추천이 같았다. 가중치 값은 정책이라 여기서는 값 자체가 아니라
동작 원리를 검증한다: 조건이 없으면 기본 가중치이고, priority 가 있으면 그 표로 바뀌며,
noise_sensitive 는 바깥 가중치를 바꾸지 않고(정숙성은 리뷰 프로필이 한 번만 반영), 잘못된 설정은 로드 시점에 거부된다."""
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
    assert perf["quiet"]["리뷰"] > base["리뷰"] > perf["value"]["리뷰"] == perf["performance"]["리뷰"]


def test_unknown_priority_falls_back_to_the_base_weights():
    assert stage3b_rank._weights_for({"priority": "nonsense"}, _ranking())[0] == _ranking()["weights"]


def test_noise_sensitive_does_not_change_the_outer_weights():
    for priority in (None, "performance", "value", "quiet"):
        plain = stage3b_rank._weights_for({"priority": priority}, _ranking())
        flagged = stage3b_rank._weights_for({"priority": priority, "noise_sensitive": True}, _ranking())
        assert flagged == plain


# ── _score / run ─────────────────────────────────────────────────────────────

def test_performance_vs_value_flips_the_ranking_between_a_cheap_and_a_strong_part():
    cheap = _cand("GPU", "cheap", 200_000, perf_tier=6)
    strong = _cand("GPU", "strong", 700_000, perf_tier=9)
    first = lambda **v: _rank("GPU", [cheap, strong], purpose="game", **v).slots["GPU"]["ranked"][0]["product_key"]
    assert first(priority="performance") == "strong"
    assert first(priority="value") == "cheap"


def test_rank_result_reports_the_weights_actually_used():
    rank = _rank("GPU", [_cand("GPU", "g", 1, perf_tier=6)], priority="quiet", noise_sensitive=True)
    assert rank.weights_used == _ranking()["priority_weights"]["quiet"]
    assert rank.weight_adjustments and "quiet" in rank.weight_adjustments[0] and len(rank.weight_adjustments) == 1
    assert _rank("GPU", [_cand("GPU", "g", 1, perf_tier=6)]).weight_adjustments == []


def test_cooling_type_reaches_candidate_specs():
    assert _specs_from_row("cooler", {"cooling_type": "Air (Dual-Tower)"})["cooling_type"] == "Air (Dual-Tower)"
    assert "cooling_type" not in _specs_from_row("cooler", {"cooling_type": None})


# ── 잘못된 설정은 로드 시점에 거부한다 ───────────────────────────────────────

@pytest.mark.parametrize("label, mutate", [
    ("가중치 합계", lambda r: r["priority_weights"]["quiet"].update(가격=0.9)),
    ("축 누락", lambda r: r["priority_weights"]["value"].pop("리뷰")),
    ("축 추가", lambda r: r["priority_weights"]["value"].update(소음=0.0)),
    ("음수 가중치", lambda r: r["priority_weights"]["value"].update(가격=-0.1, 성능=0.85)),
    ("0.01 단위 아님", lambda r: r["priority_weights"]["value"].update(가격=0.555, 성능=0.245)),
    ("제거된 소음 최소 가중치", lambda r: r.update(noise_sensitive_min_weight=0.15)),
    ("제거된 소음 대용값", lambda r: r.update(noise_proxy={"cpu_tdp_w": [65, 200]})),
    ("score_method 없음", lambda r: r.pop("score_method")),
    ("score_method 빈 문자열", lambda r: r.update(score_method=" ")),
])
def test_invalid_priority_or_noise_config_is_rejected(tmp_path, monkeypatch, label, mutate):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    mutate(rules["ranking"])
    path = tmp_path / "computer_verification_rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError):
        stage2_requirement.load_computer_rules(path)
