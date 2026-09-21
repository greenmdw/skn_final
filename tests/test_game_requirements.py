"""games 조건 — 게임 제목의 권장 사양이 요구 등급을 올리고, 모르는 게임은 안내로 남는다."""
from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from src.dto import RequirementSpec, Slots
from src.engine import stage2_requirement as s2
from src.services import recommendation_service as svc

_noop = lambda _m: None  # noqa: E731


def _spec(**values) -> RequirementSpec:
    slots = Slots(category="computer", mode="build", objective_text="", values=values)
    return s2.run(slots, {}, _noop)


def test_heavy_game_raises_tier_above_resolution_default():
    base = _spec(purpose="game", resolution="FHD_144")
    heavy = _spec(purpose="game", resolution="FHD_144", games=["사이버펑크 2077"])
    assert base.targets["GPU"]["perf_tier_min"] == 6
    assert heavy.targets["GPU"]["perf_tier_min"] == 7
    assert heavy.targets["CPU"]["perf_tier_min"] == base.targets["CPU"]["perf_tier_min"]   # cpu 6 == 6, 안 내려간다
    assert "games_applied" in heavy.flags


def test_light_game_never_lowers_the_resolution_requirement():
    base = _spec(purpose="game", resolution="QHD_165")
    light = _spec(purpose="game", resolution="QHD_165", games=["발로란트", "롤"])
    assert light.targets["GPU"] == base.targets["GPU"] and light.targets["RAM"] == base.targets["RAM"]
    # 발로란트는 GPU 가 가벼워도 높은 프레임을 위해 CPU 등급 6 을 요구 — 해상도 기본(5)보다 올라가는 건 CPU 뿐이다.
    assert light.targets["CPU"]["perf_tier_min"] == 6 > base.targets["CPU"]["perf_tier_min"]
    assert "games_applied" in light.flags and not light.unresolved


def test_max_is_taken_per_element_across_several_games():
    spec = _spec(purpose="game", resolution="FHD_144", games=["스타필드", "발로란트"])
    assert spec.targets["CPU"]["perf_tier_min"] == 7        # 스타필드 cpu 7 > 해상도 6
    assert spec.targets["GPU"]["perf_tier_min"] == 7


def test_unknown_game_is_reported_and_changes_nothing():
    base = _spec(purpose="game")
    spec = _spec(purpose="game", games=["듣도보도못한게임"])
    assert spec.targets == base.targets
    assert spec.unresolved == [{"key": "games", "value": "듣도보도못한게임", "reason": "요구사양 표에 없는 게임"}]
    assert "games_applied" not in spec.flags


def test_games_are_ignored_for_non_game_purposes():
    base = _spec(purpose="office")
    spec = _spec(purpose="office", games=["사이버펑크 2077"])
    assert spec.targets == base.targets and not spec.unresolved and "games_applied" not in spec.flags


def test_upgrade_mode_only_keeps_requested_slots_but_still_applies_games():
    slots = Slots(category="computer", mode="upgrade", objective_text="",
                  values={"purpose": "game", "resolution": "FHD_144", "games": ["사이버펑크"], "upgrade_parts": ["GPU"]})
    spec = s2.run(slots, {}, _noop)
    assert set(spec.targets) == {"GPU"} and spec.targets["GPU"]["perf_tier_min"] == 7


@pytest.mark.parametrize("raw, keys, unknown", [
    ("배그, 엘든 링", ["pubg", "eldenring"], []),
    ("엘든링 하고 싶어요", ["eldenring"], []),
    (["Cyberpunk 2077", "cyberpunk"], ["cyberpunk"], []),        # 같은 게임은 한 번만
    (["LoL", "롤러코스터 타이쿤"], ["lol"], ["롤러코스터 타이쿤"]),   # 2글자 이하 별칭은 완전 일치만
    ("", [], []),
    (None, [], []),
])
def test_match_games(raw, keys, unknown):
    got_keys, _tiers, got_unknown = s2.match_games(raw)
    assert got_keys == keys and got_unknown == unknown


def test_alias_collision_or_bad_table_is_rejected(tmp_path, monkeypatch):
    rules = deepcopy(s2.load_computer_rules())
    rules["requirements"]["game_titles"]["lol"]["aliases"].append("발로란트")
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(s2.RequirementRuleError, match="별칭 중복"):
        s2.load_computer_rules(path)

    rules = deepcopy(s2.load_computer_rules())
    del rules["requirements"]["game_titles"]["lol"]["tier"]["vram_gb"]
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(s2.RequirementRuleError, match="게임 요구사양 오류"):
        s2.load_computer_rules(path)


def test_service_surfaces_unknown_games_and_trace_row():
    spec = _spec(purpose="game", resolution="FHD_144", games=["사이버펑크 2077", "별게임"])
    extras = svc._explanation_extras(spec)
    assert len(extras["extra_caveats"]) == 1 and "'별게임'" in extras["extra_caveats"][0]
    assert "scope_note" not in extras                       # 신규 조립엔 견적 범위 문장이 없다
    step, detail = svc._games_trace_row(spec)
    assert step == "게임 요구사양" and "GPU 등급 7 이상" in detail and "별게임" in detail
    assert svc._games_trace_row(_spec(purpose="game")) is None
    assert svc._explanation_extras(_spec(purpose="game")) == {}
