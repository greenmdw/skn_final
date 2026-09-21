"""[2] 용도별 요구 프로필 — 사무·학습·창작이 게임 기준 하드 조건을 그대로 쓰지 않는다.

회귀 배경: _computer_build 가 purpose 를 읽지 않아 game/office/study 의 요구가 완전히 같았다
(CPU 티어 6·DDR5·NVMe 1TB·파워 750W Gold·최신 소켓). 사무 60만·학습 80만 요청에도 게임용
하한을 채운 견적이 나왔다. 숫자는 정책(초안)이라 여기서는 값 자체가 아니라 동작 원리를
검증한다: 프로필이 덮어쓰는 것, 덮어쓰지 않는 것, 잘못된 프로필을 거부하는 것."""
from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.engine import stage2_requirement, stage3b_rank


def _slots(**values) -> Slots:
    return Slots(category="computer", mode="build", objective_text="", values=values)


def _targets(assumed=(), **values):
    slots = _slots(**values).model_copy(update={"assumed_keys": list(assumed)})
    return stage2_requirement.run(slots, {}, lambda _: None)


def _with_rules(tmp_path, monkeypatch, mutate):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    mutate(rules)
    path = tmp_path / "computer_verification_rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(stage2_requirement, "_COMPUTER_RULES_PATH", path)
    return path


# ── 프로필이 요구를 바꾼다 ────────────────────────────────────────────────────

def test_office_and_study_drop_the_gaming_floor_while_creation_raises_it():
    game = _targets(purpose="game").targets
    office, study = _targets(purpose="office").targets, _targets(purpose="study").targets
    creation = _targets(purpose="creation").targets

    for light in (office, study):
        assert light["GPU"]["perf_tier_min"] < game["GPU"]["perf_tier_min"]
        assert light["RAM"]["type"] is None                      # DDR4 플랫폼도 허용
        assert light["저장장치"]["capacity_gb_min"] < game["저장장치"]["capacity_gb_min"]
        assert light["파워"]["wattage_min"] < game["파워"]["wattage_min"]
        assert set(game["CPU"]["socket_in"]) < set(light["CPU"]["socket_in"])
    assert office["CPU"]["perf_tier_min"] < game["CPU"]["perf_tier_min"] <= creation["CPU"]["perf_tier_min"]
    assert creation["RAM"]["capacity_gb_min"] > game["RAM"]["capacity_gb_min"]
    assert creation["RAM"]["type"] == game["RAM"]["type"]          # 프로필이 안 덮은 값은 기본 그대로


def test_profile_budget_allocation_is_used_for_that_purpose_only():
    rules = stage2_requirement.load_computer_rules()["requirements"]
    assert _targets(purpose="office", budget_max=1).budget["alloc"] == rules["purpose_profiles"]["office"]["budget_allocation"]
    assert _targets(purpose="game", budget_max=1).budget["alloc"] == rules["budget_allocation"]


@pytest.mark.parametrize("purpose", ["office", "study", "creation", "other"])
def test_profile_purposes_ignore_resolution(purpose):
    assert _targets(purpose=purpose, resolution="4K").targets == _targets(purpose=purpose, resolution="FHD_144").targets


# ── 프로필이 없는 용도는 종전 동작 그대로 ─────────────────────────────────────

@pytest.mark.parametrize("purpose", [None, "nonexistent"])
def test_purposes_without_a_profile_keep_the_game_requirements(purpose):
    values = {"purpose": purpose} if purpose else {}
    assert _targets(**values).targets == _targets(purpose="game").targets


def test_other_is_a_general_purpose_profile_at_study_level():
    # 2026-09-21 결정: 용도를 특정하지 못한 "기타"에 게임급 하한을 강제하지 않는다.
    assert _targets(purpose="other").targets == _targets(purpose="study").targets
    assert _targets(purpose="other").targets != _targets(purpose="game").targets


def test_resolution_assumed_flag_only_applies_to_resolution_driven_purposes():
    # 해상도를 기본값으로 가정한 경우(assumed_keys 에 resolution)만 플래그가 붙는다.
    assert "resolution_assumed" in _targets(("resolution",), purpose="game").flags
    assert "resolution_assumed" not in _targets(("resolution",), purpose="office").flags
    assert "resolution_assumed" not in _targets(purpose="game", resolution="QHD_165").flags


def test_game_resolution_tiers_are_untouched_by_profiles():
    for res in ("FHD_144", "QHD_165", "4K"):
        tier = stage2_requirement.load_computer_rules()["requirements"]["game_tiers"][res]
        t = _targets(purpose="game", resolution=res).targets
        assert (t["GPU"]["perf_tier_min"], t["CPU"]["perf_tier_min"], t["GPU"]["vram_gb_min"]) == (
            tier["gpu"], tier["cpu"], tier["vram_gb"])


# ── 프로필 값이 코드 수정 없이 반영된다 ───────────────────────────────────────

def test_changed_profile_changes_requirement_without_code_edit(tmp_path, monkeypatch):
    def mutate(rules):
        rules["requirements"]["purpose_profiles"]["office"].update(
            tier={"gpu": 2, "cpu": 3, "ram_gb": 64, "vram_gb": 2},
            ram_type="DDR4", storage_capacity_gb_min=2000, psu_efficiency_min="Silver")

    _with_rules(tmp_path, monkeypatch, mutate)
    t = _targets(purpose="office").targets
    assert (t["CPU"]["perf_tier_min"], t["GPU"]["perf_tier_min"]) == (3, 2)
    assert (t["RAM"]["type"], t["RAM"]["capacity_gb_min"]) == ("DDR4", 64)
    assert t["저장장치"]["capacity_gb_min"] == 2000
    assert t["파워"]["plus_rating_min"] == "Silver"


# ── 랭킹의 이상 티어: 해상도 없는 용도는 default ─────────────────────────────

def _ideal_tier(slot, **values):
    cand = Candidate(product_key="k", slot=slot, name="k", price=1000, specs={"perf_tier": 5})
    spec = RequirementSpec(list_id="r", category="computer", mode="build", targets={slot: {}}, budget={"total": 0})
    rank = stage3b_rank.run(HardFilterResult(slots={slot: [cand]}), spec, _slots(**values), lambda _: None)
    return rank.slots[slot]["ideal_tier"]


def test_ideal_tier_uses_the_purpose_default_and_keeps_game_by_resolution():
    ideal = stage2_requirement.load_computer_rules()["ranking"]["ideal_tiers"]
    assert _ideal_tier("CPU", purpose="office") == ideal["office"]["default"]["CPU"]
    assert _ideal_tier("GPU", purpose="creation", resolution="4K") == ideal["creation"]["default"]["GPU"]
    assert _ideal_tier("GPU", purpose="game", resolution="QHD_165") == ideal["game"]["QHD_165"]["GPU"]


# ── 잘못된 프로필은 로드 시점에 거부한다 ─────────────────────────────────────

@pytest.mark.parametrize("label, mutate", [
    ("알 수 없는 키", lambda p: p.update(unknown_key=1)),
    ("tier 누락", lambda p: p["tier"].pop("vram_gb")),
    ("tier 가 숫자 아님", lambda p: p["tier"].update(cpu="high")),
    ("예산 배분 합계", lambda p: p["budget_allocation"].update(GPU=0.9)),
    ("알 수 없는 파워 등급", lambda p: p.update(psu_efficiency_min="Diamond")),
    ("브랜드 소켓 누락", lambda p: p["sockets_by_brand"].pop("none")),
    ("전력이 표준 용량 초과", lambda p: p.update(estimated_power_w={"cpu": 900, "gpu": 900, "other": 900})),
])
def test_invalid_profile_is_rejected(tmp_path, monkeypatch, label, mutate):
    _with_rules(tmp_path, monkeypatch, lambda rules: mutate(rules["requirements"]["purpose_profiles"]["office"]))
    with pytest.raises(stage2_requirement.RequirementRuleError, match="용도 프로필 office"):
        stage2_requirement.load_computer_rules(stage2_requirement._COMPUTER_RULES_PATH)
