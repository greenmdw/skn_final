"""PC 정책값은 코드 상수가 아니라 버전 있는 YAML에서 읽는다."""
from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from src.dto import Candidate, RankResult, RequirementSpec, Slots
from src.engine import stage2_requirement, stage3a_hardfilter, stage3b_rank, stage4_optimize


def _slots(**values) -> Slots:
    return Slots(category="computer", mode="build", objective_text="", values=values)


def _cand(key: str, slot: str, price: int, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=key, price=price, specs=specs)


def test_default_yaml_preserves_pc_requirement_contract():
    rules = stage2_requirement.load_computer_rules()
    assert rules["rule_set_version"] == "computer-rules-v5"
    spec = stage2_requirement.run(_slots(resolution="QHD_165", brand_pref="amd", budget_max=2_000_000), {}, lambda _: None)
    assert spec.targets["GPU"]["vram_gb_min"] == 12
    assert spec.targets["CPU"]["socket_in"] == ["AM5"]
    assert spec.targets["파워"]["wattage_min"] == 750
    assert spec.link_rules[-1] == "sum(power) <= psu.wattage * 0.9"
    assert len(spec.link_rules) == len(rules["verification"]["link_rules"])
    assert spec.budget["alloc"] == rules["requirements"]["budget_allocation"]


def test_changed_yaml_changes_requirement_without_code_edit(tmp_path, monkeypatch):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["rule_set_version"] = "computer-rules-test"
    rules["requirements"]["game_tiers"]["QHD_165"]["vram_gb"] = 16
    rules["requirements"]["psu_headroom_multiplier"] = 1.8
    path = tmp_path / "computer_verification_rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(stage2_requirement, "_COMPUTER_RULES_PATH", path)

    spec = stage2_requirement.run(_slots(resolution="QHD_165", budget_max=2_000_000), {}, lambda _: None)
    assert spec.targets["GPU"]["vram_gb_min"] == 16
    assert spec.targets["파워"]["wattage_min"] == 1000


def test_yaml_validation_rejects_bad_budget_allocation(tmp_path):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["requirements"]["budget_allocation"]["GPU"] = 0.5
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError, match="예산 배분"):
        stage2_requirement.load_computer_rules(path)


def test_efficiency_order_and_rank_weights_come_from_yaml(monkeypatch):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["verification"]["efficiency_order"] = ["Standard", "Gold", "Bronze"]
    monkeypatch.setattr(stage3a_hardfilter, "load_computer_rules", lambda: rules)
    assert stage3a_hardfilter._rating_rank("80+ Bronze") > stage3a_hardfilter._rating_rank("Gold")

    rules["ranking"]["weights"] = {"가격": 1.0, "성능": 0.0, "밸런스": 0.0, "리뷰": 0.0, "호환여유": 0.0}
    monkeypatch.setattr(stage3b_rank, "load_computer_rules", lambda: rules)
    monkeypatch.setattr(stage3b_rank, "_review_axis", lambda _: (0.5, []))
    scored = stage3b_rank._score(_cand("cpu", "CPU", 100), None, 200, "CPU", {})
    assert scored.score == 0.5


def test_psu_capacity_factor_controls_set_verification(monkeypatch):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["verification"]["power"]["psu_capacity_factor"] = 0.5
    monkeypatch.setattr(stage4_optimize, "load_computer_rules", lambda: rules)
    pools = {
        "CPU": [_cand("cpu", "CPU", 100, tdp_w=100)],
        "GPU": [_cand("gpu", "GPU", 100, power_w=200)],
        "파워": [_cand("psu", "파워", 100, wattage_w=500)],
    }
    rank = RankResult(slots={slot: {"ranked": [candidate.model_dump() for candidate in candidates]}
                             for slot, candidates in pools.items()})
    spec = RequirementSpec(list_id="test", category="computer", mode="build",
                           targets={slot: {} for slot in pools}, budget={"total": 1000})
    build = stage4_optimize.build_computer(rank, spec, lambda _: None)
    assert build.link_check["power"] == "fail"  # 300 W > 500 W * 0.5


@pytest.mark.parametrize("bad", [
    {"gpu": {"Entry": 0}},          # 1 미만
    {"gpu": {"Entry": 11}},         # 10 초과
    {"gpu": {"Entry": "high"}},     # 숫자 아님
    {"gpu": {}},                    # 비어 있음
    {"psu": {"Entry": 5}},          # cpu/gpu 이외
])
def test_lineup_perf_tier_table_rejects_bad_values(tmp_path, bad):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules["requirements"]["lineup_perf_tier"] = bad
    path = tmp_path / "computer_verification_rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(stage2_requirement.RequirementRuleError):
        stage2_requirement.load_computer_rules(path)
