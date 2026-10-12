"""games 조건 — 게임 제목의 권장 사양이 요구 등급을 올리고, 모르는 게임은 안내로 남는다."""
from __future__ import annotations

import re
from copy import deepcopy

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.engine import stage2_requirement as s2
from src.engine import stage3b_rank
from src.services import recommendation_service as svc

_noop = lambda _m: None  # noqa: E731


def _spec(**values) -> RequirementSpec:
    slots = Slots(category="computer", mode="build", objective_text="", values=values)
    return s2.run(slots, {}, _noop)


def test_heavy_game_raises_tier_above_resolution_default():
    base = _spec(purpose="game", resolution="FHD_144")
    heavy = _spec(purpose="game", resolution="FHD_144", games=["사이버펑크 2077"])
    # 2026-10-12: 게임 표를 공식 '권장' 사양(FHD)에서 다시 옮겼다. 사이버펑크의 권장 CPU(Core i7-12700급)만 해상도 기본(6)보다
    # 높고, 권장 GPU(RTX 2060 Super급, 등급 5)는 기본(6)보다 낮아 GPU 요구는 그대로다.
    assert base.targets["CPU"]["perf_tier_min"] == 6
    assert heavy.targets["CPU"]["perf_tier_min"] == 7
    assert heavy.targets["GPU"]["perf_tier_min"] == base.targets["GPU"]["perf_tier_min"] == 6   # 낮은 값은 요구를 내리지 않는다
    assert "games_applied" in heavy.flags


def test_light_game_never_lowers_the_resolution_requirement():
    base = _spec(purpose="game", resolution="QHD_165")
    light = _spec(purpose="game", resolution="QHD_165", games=["발로란트", "롤"])
    # 발로란트·롤의 공식 권장 사양은 QHD 165Hz 해상도 기본보다 모든 요소가 낮다 — 아무 것도 바뀌지 않는다.
    assert light.targets == base.targets
    assert "games_applied" in light.flags and not light.unresolved


def test_max_is_taken_per_element_across_several_games(monkeypatch):
    # 실제 표의 게임은 FHD 기본을 둘 다 넘지 못하므로, 두 게임이 서로 다른 요소를 올리도록 시험용 표를 쓴다.
    rules = deepcopy(s2.load_computer_rules())
    titles = rules["requirements"]["game_titles"]
    titles["starfield"]["tier"] = {"gpu": 8, "cpu": 4, "ram_gb": 16, "vram_gb": 8}
    titles["valorant"]["tier"] = {"gpu": 3, "cpu": 9, "ram_gb": 8, "vram_gb": 2}
    monkeypatch.setattr(s2, "load_computer_rules", lambda *a, **k: rules)
    spec = _spec(purpose="game", resolution="FHD_144", games=["스타필드", "발로란트"])
    assert spec.targets["GPU"]["perf_tier_min"] == 8        # 스타필드(시험값)
    assert spec.targets["CPU"]["perf_tier_min"] == 9        # 발로란트(시험값)


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
                  values={"purpose": "game", "resolution": "FHD_144", "games": ["사이버펑크"], "upgrade_parts": ["CPU"]})
    spec = s2.run(slots, {}, _noop)
    assert set(spec.targets) == {"CPU"} and spec.targets["CPU"]["perf_tier_min"] == 7


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
    # 사이버펑크는 승인(approved)돼 잠정값 caveat 이 없고, 표에 없는 게임("별게임") caveat 만 남는다.
    assert len(extras["extra_caveats"]) == 1
    assert any("'별게임'" in c for c in extras["extra_caveats"])
    assert not any("잠정값" in c for c in extras["extra_caveats"])
    # 아직 provisional 인 게임(오버워치)을 말하면 잠정값 caveat 이 따로 붙는다 — 표에 없는 게임 caveat 과는 별개의 문장이다.
    held = svc._explanation_extras(_spec(purpose="game", resolution="FHD_144", games=["오버워치", "별게임"]))
    assert len(held["extra_caveats"]) == 2 and any("잠정값" in c for c in held["extra_caveats"])
    assert "scope_note" not in extras                       # 신규 조립엔 견적 범위 문장이 없다
    step, detail = svc._games_trace_row(spec)
    assert step == "게임 요구사양" and "CPU 등급 7 이상" in detail and "별게임" in detail
    assert svc._games_trace_row(_spec(purpose="game")) is None
    assert svc._explanation_extras(_spec(purpose="game")) == {}


# ── E6 — games 조건을 [3-B] 랭킹(ideal_tier)에 반영 ──────────────────────────

def _cand(slot, key, price, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=key, price=price, specs=specs)


def _rank(spec: RequirementSpec, slot: str, cands: list[Candidate], **values) -> "stage3b_rank.RankResult":
    slots = Slots(category="computer", mode="build", objective_text="", values=values)
    return stage3b_rank.run(HardFilterResult(slots={slot: cands}), spec, slots, _noop)


def test_heavy_game_raises_the_cpu_ideal_tier_and_logs_the_bump():
    # 게임 표의 권장 CPU 등급(사이버펑크 7)이 FHD_144 의 ideal CPU(6.0)보다 높다. (GPU 쪽은 지금 표의 게임이 기본을 못 넘는다)
    spec = _spec(purpose="game", resolution="FHD_144", games=["사이버펑크 2077"])
    assert spec.targets["CPU"]["perf_tier_min"] == 7 and "games_applied" in spec.flags
    cands = [_cand("CPU", "mid", 200_000, perf_tier=6), _cand("CPU", "high", 300_000, perf_tier=8)]
    rr = _rank(spec, "CPU", cands, purpose="game", resolution="FHD_144", games=["사이버펑크 2077"])
    assert rr.slots["CPU"]["ideal_tier"] == 7.0
    assert "게임 요구 반영: CPU 이상 등급 6→7" in rr.weight_adjustments


def test_light_game_does_not_move_the_ideal_tier_or_add_a_note():
    # 발로란트(gpu tier 3)는 FHD_144 기본 ideal(6.0)보다 가벼워 targets 의 perf_tier_min 도 6에 머문다.
    spec = _spec(purpose="game", resolution="FHD_144", games=["발로란트"])
    assert spec.targets["GPU"]["perf_tier_min"] == 6 and "games_applied" in spec.flags
    cands = [_cand("GPU", "mid", 300_000, perf_tier=6)]
    rr = _rank(spec, "GPU", cands, purpose="game", resolution="FHD_144", games=["발로란트"])
    assert rr.slots["GPU"]["ideal_tier"] == 6.0
    assert rr.weight_adjustments == []


def test_without_games_the_rank_result_is_unchanged_even_if_a_floor_was_raised_some_other_way():
    """games_applied 가 없으면 targets 에 perf_tier_min 이 (업그레이드의 current_tiers 처럼) 높게
    들어 있어도 ideal_tier·score·weight_adjustments 가 조금도 바뀌지 않는다 — E6 은 games 전용이다."""
    cands = [_cand("GPU", "a", 300_000, perf_tier=6), _cand("GPU", "b", 300_000, perf_tier=8)]

    def _spec_without_games(perf_tier_min):
        targets = {"GPU": ({"perf_tier_min": perf_tier_min} if perf_tier_min else {})}
        return RequirementSpec(list_id="r", category="computer", mode="build", targets=targets,
                               budget={"total": 2_000_000, "alloc": {"GPU": 0.4}})

    rr_plain = _rank(_spec_without_games(None), "GPU", cands, purpose="game", resolution="FHD_144")
    rr_high_floor = _rank(_spec_without_games(9), "GPU", cands, purpose="game", resolution="FHD_144")

    assert rr_plain.slots["GPU"]["ideal_tier"] == rr_high_floor.slots["GPU"]["ideal_tier"] == 6.0
    assert rr_plain.weight_adjustments == rr_high_floor.weight_adjustments == []
    assert ([c["score"] for c in rr_plain.slots["GPU"]["ranked"]]
            == [c["score"] for c in rr_high_floor.slots["GPU"]["ranked"]])


def test_raising_the_ideal_tier_relatively_favors_the_higher_tier_candidate():
    """ideal 이 오르면(게임 요구 반영) 그 위쪽 등급 후보의 밸런스 축 점수가 상대적으로 좋아진다."""
    weak = _cand("GPU", "weak", 300_000, perf_tier=6)
    strong = _cand("GPU", "strong", 300_000, perf_tier=9)
    before_weak = stage3b_rank._score(weak, 6.0, 1_000_000, "GPU", {})
    before_strong = stage3b_rank._score(strong, 6.0, 1_000_000, "GPU", {})
    after_weak = stage3b_rank._score(weak, 7.0, 1_000_000, "GPU", {})
    after_strong = stage3b_rank._score(strong, 7.0, 1_000_000, "GPU", {})
    assert after_strong.breakdown["밸런스"] > before_strong.breakdown["밸런스"]
    assert after_weak.breakdown["밸런스"] < before_weak.breakdown["밸런스"]


# ── E7 — game_titles 출처·승인 상태 스키마 (D의 엔진 쪽, R-11은 범위 밖) ──────────

# 2026-10-12 승인 시트(docs/게임요구사양_승인시트_20261012.xlsx)에서 사람이 승인한 게임. 보류한 마인크래프트·오버워치 2 는 provisional.
_APPROVED = {"valorant", "lol", "maplestory", "lostark", "pubg", "eldenring", "diablo4", "warzone", "bg3", "cyberpunk", "wukong",
             "monsterhunter", "starfield"}
_ON_HOLD = {"minecraft", "overwatch2"}


def test_the_15_game_titles_carry_a_source_and_only_the_person_approved_ones_are_approved():
    """공식 권장 사양에서 등급을 다시 옮기고 출처(url·발췌·확인일)를 붙였다. approved 는 사람이 승인 시트에서 승인한 13개뿐이고
    보류한 2개는 provisional 로 남는다(기획서 ENG-05)."""
    rules = s2.load_computer_rules()
    titles = rules["requirements"]["game_titles"]
    assert set(titles) == _APPROVED | _ON_HOLD
    for key in titles:
        got = s2.game_title_status(key, rules)
        assert got["status"] == ("approved" if key in _APPROVED else "provisional"), key
        assert got["source"]["url"].startswith("https://") and got["source"]["excerpt"], key
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", got["source"]["checked_at"]), key


def _rules_with_lol_status(status: str, *, source: dict | None = None) -> dict:
    rules = deepcopy(s2.load_computer_rules())
    entry = rules["requirements"]["game_titles"]["lol"]
    entry["status"] = status
    if source is not None:
        entry["source"] = source
    else:
        entry.pop("source", None)
    return rules


def _write(tmp_path, rules) -> "object":
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_approved_status_without_source_is_rejected(tmp_path):
    path = _write(tmp_path, _rules_with_lol_status("approved"))
    with pytest.raises(s2.RequirementRuleError, match="승인"):
        s2.load_computer_rules(path)


def test_approved_status_with_only_url_is_rejected(tmp_path):
    path = _write(tmp_path, _rules_with_lol_status("approved", source={"url": "https://example.com/lol"}))
    with pytest.raises(s2.RequirementRuleError, match="승인"):
        s2.load_computer_rules(path)


def test_unknown_key_on_a_game_title_entry_is_rejected(tmp_path):
    rules = _rules_with_lol_status("provisional")
    rules["requirements"]["game_titles"]["lol"]["extra_key"] = "x"
    path = _write(tmp_path, rules)
    with pytest.raises(s2.RequirementRuleError, match="게임 요구사양 오류"):
        s2.load_computer_rules(path)


def test_unknown_status_value_is_rejected(tmp_path):
    path = _write(tmp_path, _rules_with_lol_status("확정"))
    with pytest.raises(s2.RequirementRuleError, match="상태"):
        s2.load_computer_rules(path)


def test_unknown_source_key_is_rejected(tmp_path):
    path = _write(tmp_path, _rules_with_lol_status(
        "approved", source={"url": "https://example.com/lol", "checked_at": "2024-01-01", "note": "x"}))
    with pytest.raises(s2.RequirementRuleError, match="출처"):
        s2.load_computer_rules(path)


@pytest.mark.parametrize("checked_at", ["2024/01/01", "24-01-01", "2024-1-1", "확인함", ""])
def test_bad_checked_at_format_is_rejected(tmp_path, checked_at):
    path = _write(tmp_path, _rules_with_lol_status(
        "approved", source={"url": "https://example.com/lol", "checked_at": checked_at}))
    with pytest.raises(s2.RequirementRuleError):
        s2.load_computer_rules(path)


def test_approved_status_with_full_source_loads_successfully(tmp_path):
    rules = _rules_with_lol_status(
        "approved", source={"url": "https://example.com/lol", "checked_at": "2024-01-01", "excerpt": "권장: ..."})
    path = _write(tmp_path, rules)
    loaded = s2.load_computer_rules(path)
    assert s2.game_title_status("lol", loaded) == {
        "status": "approved",
        "source": {"url": "https://example.com/lol", "checked_at": "2024-01-01", "excerpt": "권장: ..."},
    }


def test_game_title_label_prefers_the_first_alias_that_contains_hangul():
    # lol 의 첫 별칭 "리그오브레전드"(한글) — 화면에는 내부 키(lol)가 아니라 이 표시명이 나가야 한다.
    assert s2.game_title_label("lol") == "리그오브레전드"
    assert s2.game_title_label("valorant") == "발로란트"


def test_game_title_label_falls_back_to_the_first_alias_when_none_contain_hangul():
    rules = deepcopy(s2.load_computer_rules())
    rules["requirements"]["game_titles"]["lol"]["aliases"] = ["lol", "leagueoflegends"]
    assert s2.game_title_label("lol", rules) == "lol"


def test_games_provisional_flag_absent_when_all_recognized_titles_are_approved(monkeypatch):
    rules = _rules_with_lol_status("approved", source={"url": "https://example.com/lol", "checked_at": "2024-01-01"})
    monkeypatch.setattr(s2, "load_computer_rules", lambda path=None: rules)
    spec = _spec(purpose="game", games=["롤"])
    assert "games_applied" in spec.flags and "games_provisional" not in spec.flags
    assert spec.games == [{"key": "lol", "label": "리그오브레전드", "status": "approved",
                            "source": {"url": "https://example.com/lol", "checked_at": "2024-01-01"}}]
    assert not any(":" in f for f in spec.flags)   # 제목별 상태는 flags 문자열이 아니라 spec.games 에 싣는다


def test_games_provisional_flag_present_when_any_recognized_title_is_still_provisional():
    # 롤은 승인됐고 오버워치는 보류(provisional)라 섞인 상태다.
    spec = _spec(purpose="game", games=["롤", "오버워치"])
    assert "games_applied" in spec.flags and "games_provisional" in spec.flags
    assert not any(":" in f for f in spec.flags)
    by_key = {g["key"]: g for g in spec.games}
    assert by_key["lol"]["status"] == "approved" and by_key["lol"]["label"] == "리그오브레전드"
    assert by_key["overwatch2"]["status"] == "provisional" and by_key["overwatch2"]["label"] == "오버워치"


def test_games_trace_row_does_not_assert_when_all_recognized_titles_are_provisional():
    spec = _spec(purpose="game", resolution="FHD_144", games=["오버워치"])
    step, detail = svc._games_trace_row(spec)
    assert step == "게임 요구사양"
    assert "잠정" in detail
    assert "반영해 최소 등급을 정했습니다" not in detail   # 옛 단정 문구는 남지 않는다


def test_games_trace_row_distinguishes_status_per_title_when_mixed():
    spec = _spec(purpose="game", games=["롤", "오버워치"])
    step, detail = svc._games_trace_row(spec)
    assert step == "게임 요구사양"
    # 화면에는 내부 키(lol/overwatch2)가 아니라 표시명이 나간다.
    assert "리그오브레전드: 배급사 권장 사양 확인(2026-10-12)" in detail
    assert "오버워치: 잠정값" in detail
    assert "lol" not in detail and "overwatch2" not in detail


def test_games_trace_row_uses_confirmed_wording_when_all_recognized_titles_are_approved(monkeypatch):
    rules = _rules_with_lol_status("approved", source={"url": "https://example.com/lol", "checked_at": "2024-01-01"})
    monkeypatch.setattr(s2, "load_computer_rules", lambda path=None: rules)
    spec = _spec(purpose="game", games=["롤"])
    step, detail = svc._games_trace_row(spec)
    assert step == "게임 요구사양"
    assert "잠정" not in detail
    assert "확인해 최소 등급을 정했습니다" in detail


def test_explanation_extras_has_provisional_caveat_only_when_a_title_is_recognized():
    with_game = svc._explanation_extras(_spec(purpose="game", games=["오버워치"]))
    assert any("잠정값" in c for c in with_game["extra_caveats"])

    without_game = svc._explanation_extras(_spec(purpose="game"))
    assert without_game == {}


def test_explanation_extras_has_no_provisional_caveat_when_all_recognized_titles_are_approved(monkeypatch):
    rules = _rules_with_lol_status("approved", source={"url": "https://example.com/lol", "checked_at": "2024-01-01"})
    monkeypatch.setattr(s2, "load_computer_rules", lambda path=None: rules)
    extras = svc._explanation_extras(_spec(purpose="game", games=["롤"]))
    assert extras == {}
