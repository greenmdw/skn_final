"""주변기기 요구사양 룩업(E10) 테스트 — src/engine/peripheral_requirement.py.

DB 불필요(마지막 두 절의 "전체 CSV" 테스트만 data/peripherals/*_processed.csv 원본을
읽는다 — DB 접속은 아니다). 계획 §3.3 E10의 완료 기준: QHD_165 하드 조건, 해상도 미지정 시
기본값(FHD_144)+assumed, 4K의 용도별 주사율 하한, 소음/게임 소프트 선호, 요청하지 않은
종류 배제, 잘못된 설정에서 PeripheralRuleError, C6(기본 조건에서 모니터 0건) 사실 고정,
마우스 블루투스⊆무선 사실 고정(코디네이터 리뷰 반영 — 아래 참고).
"""
from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.config import ROOT
from src.engine import peripheral_rules as pr
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_requirement import build_requirements

_DATA_MONITOR_CSV = ROOT / "data" / "peripherals" / "monitor_processed.csv"
_DATA_MOUSE_CSV = ROOT / "data" / "peripherals" / "mouse_processed.csv"


def _write(tmp_path: Path, rules: dict, name: str = "peripherals.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ── 모니터 하드 조건 ────────────────────────────────────────────────────────
def test_qhd165_monitor_hard_conditions_and_no_assumed():
    reqs = build_requirements({"resolution": "QHD_165"}, ["monitor"])
    req = reqs["monitor"]
    assert req.hard == {"resolution_class": ["QHD"], "refresh_min_hz": 165}
    assert req.assumed == []
    assert req.notes == []


def test_missing_resolution_defaults_to_fhd_with_assumed_and_note():
    reqs = build_requirements({}, ["monitor"])
    req = reqs["monitor"]
    assert req.hard == {"resolution_class": ["FHD"], "refresh_min_hz": 144}
    assert req.assumed == ["resolution"]
    assert len(req.notes) == 1
    assert "해상도" in req.notes[0] and "기본값" in req.notes[0]


def test_4k_refresh_min_hz_depends_on_purpose():
    game = build_requirements({"resolution": "4K", "purpose": "game"}, ["monitor"])["monitor"]
    office = build_requirements({"resolution": "4K", "purpose": "office"}, ["monitor"])["monitor"]
    assert game.hard == {"resolution_class": ["UHD"], "refresh_min_hz": 120}
    assert office.hard == {"resolution_class": ["UHD"], "refresh_min_hz": 60}


# ── 소프트 선호 ─────────────────────────────────────────────────────────────
def test_quiet_priority_prefers_non_clicky_keyboard_switch():
    req = build_requirements({"priority": "quiet"}, ["keyboard"])["keyboard"]
    assert {"key": "switch_clicky", "op": "equals", "value": False} in req.soft["preferences"]


def test_noise_sensitive_also_prefers_non_clicky_keyboard_switch():
    req = build_requirements({"noise_sensitive": True}, ["keyboard"])["keyboard"]
    assert {"key": "switch_clicky", "op": "equals", "value": False} in req.soft["preferences"]


def test_quiet_and_noise_sensitive_both_match_appends_both_not_overwrite():
    """설계 결정(모듈 docstring): 여러 when 이 같은 판정 키를 겨냥하면 뒤 조건이 앞 조건을
    덮지 않고 둘 다 preferences 목록에 쌓인다."""
    req = build_requirements({"priority": "quiet", "noise_sensitive": True}, ["keyboard"])["keyboard"]
    clicky_false_count = sum(
        1 for p in req.soft["preferences"] if p == {"key": "switch_clicky", "op": "equals", "value": False}
    )
    assert clicky_false_count == 2


def test_game_purpose_prefers_magnetic_and_rapid_trigger_keyboard():
    req = build_requirements({"purpose": "game"}, ["keyboard"])["keyboard"]
    prefs = req.soft["preferences"]
    assert {"key": "switch_magnetic", "op": "equals", "value": True} in prefs
    assert {"key": "rapid_trigger", "op": "equals", "value": True} in prefs


def test_game_purpose_prefers_high_polling_mouse():
    req = build_requirements({"purpose": "game"}, ["mouse"])["mouse"]
    assert {"key": "polling_hz_max", "op": "min", "value": 1000} in req.soft["preferences"]


@pytest.mark.parametrize("purpose", ["office", "study"])
def test_office_or_study_prefers_wireless_mouse(purpose):
    """무선만 선호로 둔다(블루투스는 별도 pref 없음) — 아래 전체 카탈로그 고정 테스트가
    이유(블루투스는 항상 무선의 부분집합으로 관측됨)를 증명한다. 둘 다 넣으면 이중 계산이
    된다(코디네이터 리뷰 지적)."""
    req = build_requirements({"purpose": purpose}, ["mouse"])["mouse"]
    prefs = req.soft["preferences"]
    assert prefs == [{"key": "connectivity_wireless", "op": "equals", "value": True}]


def test_office_prefers_usb_powered_speaker():
    req = build_requirements({"purpose": "office"}, ["speaker"])["speaker"]
    assert {"key": "power_source_raw", "op": "contains_any", "value": ["USB"]} in req.soft["preferences"]


def test_game_prefers_multichannel_speaker():
    req = build_requirements({"purpose": "game"}, ["speaker"])["speaker"]
    assert {"key": "channels", "op": "min", "value": 2} in req.soft["preferences"]


def test_creation_prefers_ips_oled_monitor_panel():
    req = build_requirements({"purpose": "creation"}, ["monitor"])["monitor"]
    assert {"key": "panel_raw", "op": "contains_any", "value": ["IPS", "OLED"]} in req.soft["preferences"]


def test_no_matching_condition_gives_empty_soft():
    req = build_requirements({"purpose": "other"}, ["speaker"])["speaker"]
    assert req.soft == {}


# ── 요청하지 않은 종류는 결과에 없음 ────────────────────────────────────────
def test_unrequested_kind_not_in_result():
    reqs = build_requirements({"purpose": "game"}, ["keyboard"])
    assert set(reqs) == {"keyboard"}
    assert "mouse" not in reqs
    assert "monitor" not in reqs


def test_empty_kinds_list_gives_empty_result():
    assert build_requirements({"resolution": "QHD_165"}, []) == {}


# ── 잘못된 설정은 PeripheralRuleError ──────────────────────────────────────
def test_unknown_condition_key_in_soft_when_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["keyboard"]["soft"][0]["when"] = {"never_heard_of_this": "x"}
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="조건 키"):
        pr.load_peripheral_rules(path)


def test_enum_value_outside_slot_schema_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["keyboard"]["soft"][0]["when"] = {"priority": "ultra_quiet"}
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="조건 값"):
        pr.load_peripheral_rules(path)


def test_unknown_spec_key_in_soft_prefs_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["mouse"]["soft"][0]["prefs"][0]["key"] = "totally_made_up_key"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="spec 키"):
        pr.load_peripheral_rules(path)


def test_unknown_operator_in_soft_prefs_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["mouse"]["soft"][0]["prefs"][0]["op"] = "greater_than_maybe"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="연산자"):
        pr.load_peripheral_rules(path)


def test_min_op_with_non_numeric_value_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["mouse"]["soft"][0]["prefs"][0]["op"] = "min"
    rules["requirements"]["mouse"]["soft"][0]["prefs"][0]["value"] = "not-a-number"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="숫자"):
        pr.load_peripheral_rules(path)


def test_monitor_hard_unknown_resolution_class_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["monitor"]["hard"]["resolution_class_by_res"]["FHD_144"] = "NOT_A_CLASS"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="등급"):
        pr.load_peripheral_rules(path)


def test_monitor_hard_non_positive_refresh_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["monitor"]["hard"]["refresh_min_hz_by_res"]["FHD_144"] = 0
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="양수"):
        pr.load_peripheral_rules(path)


def test_hard_section_outside_monitor_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["keyboard"]["hard"] = {"resolution_class_by_res": {}}
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="monitor 전용"):
        pr.load_peripheral_rules(path)


# ── C6 사실 고정 — 전체 CSV 기준 FHD_144 하드 조건을 만족하는 모니터 0건 ─────
@pytest.fixture(scope="module")
def full_monitor_candidates(tmp_path_factory):
    """data/peripherals/monitor_processed.csv(팀 전달 원본, Git 미추적)를 E9 mock 로더로
    읽는다. 파일이 없는 환경에서는 스킵한다 — tests/test_seed_peripherals.py의 동일 CSV
    부재 처리 방식(파일 존재 여부로 skip)을 그대로 따른다."""
    if not _DATA_MONITOR_CSV.is_file():
        pytest.skip("팀 전달 원본 CSV는 저장소에 포함되지 않습니다.")
    directory = tmp_path_factory.mktemp("full_monitor_csv")
    shutil.copy(_DATA_MONITOR_CSV, directory / "monitor.csv")
    return load_peripheral_candidates_from_csv(directory).get("monitor", [])


def test_fhd144_hard_conditions_match_zero_monitors_in_full_catalog(full_monitor_candidates):
    """계획 C6 고정 사실: 기본 해상도(FHD_144)의 하드 조건(FHD 등급 + 144Hz 이상)을 만족하는
    모니터가 전체 카탈로그(33행)에 0건이다. 1920x1080은 1행뿐이고 75Hz라 하한(144Hz)에
    못 미친다. 이 모듈은 조건을 조용히 완화하지 않으므로 0건이 올바른 결과다(E10).

    **의도된 깨짐**: R-2(데이터 보강)로 FHD 144Hz 이상 모니터가 카탈로그에 들어오면 이
    assert(== [])는 깨진다 — 그때는 이 테스트를 "0건 이상 포함"으로 완화하거나 실측
    행 수에 맞춰 갱신한다. 실패 자체가 데이터 보강이 반영됐다는 신호다.
    """
    req = build_requirements({"resolution": "FHD_144"}, ["monitor"])["monitor"]
    allowed_classes = set(req.hard["resolution_class"])
    refresh_min = req.hard["refresh_min_hz"]
    matches = [
        c for c in full_monitor_candidates
        if c.specs.get("resolution_class") in allowed_classes
        and (c.specs.get("refresh_hz") or 0) >= refresh_min
    ]
    assert matches == []


# ── 마우스 블루투스 ⊆ 무선 사실 고정 (코디네이터 리뷰) ──────────────────────
@pytest.fixture(scope="module")
def full_mouse_candidates(tmp_path_factory):
    """data/peripherals/mouse_processed.csv 를 E9 mock 로더로 읽는다. 없으면 스킵
    (test_seed_peripherals.py 와 같은 방식)."""
    if not _DATA_MOUSE_CSV.is_file():
        pytest.skip("팀 전달 원본 CSV는 저장소에 포함되지 않습니다.")
    directory = tmp_path_factory.mktemp("full_mouse_csv")
    shutil.copy(_DATA_MOUSE_CSV, directory / "mouse.csv")
    return load_peripheral_candidates_from_csv(directory).get("mouse", [])


def test_bluetooth_mice_are_always_also_wireless_in_full_catalog(full_mouse_candidates):
    """config/peripherals.yaml 의 mouse.soft(office/study)가 connectivity_wireless=true
    하나만 두고 connectivity_bluetooth 는 별도 pref 로 두지 않는 근거.

    parse_connectivity 가 만드는 connectivity_bluetooth 는 connectivity_interface 원문에서
    "bluetooth" 를 찾아 매기고, connectivity_wireless 는 connectivity 원문의 "무선" 표기에서
    매긴다 — 서로 다른 원문 컬럼에서 오므로 이론적으로는 독립일 수 있다. 그런데 전체
    카탈로그(84행) 실측으로는 connectivity_bluetooth=true 인 마우스가 전부
    connectivity_wireless=true 도 같이 갖고 있다(블루투스는 무선의 부분집합으로 관측됨).
    그래서 connectivity_wireless=true 선호 하나로 블루투스 마우스까지 이미 포함되고,
    connectivity_bluetooth 를 별도 pref 로 추가하면 "무선 또는 블루투스"가 사실상
    AND 처럼 겹쳐 세어지는 이중 계산이 된다.

    **의도된 깨짐**: 이 가정을 깨는 마우스(블루투스는 있는데 무선이 아니라고 기록된 행)가
    데이터에 들어오면 이 테스트가 실패한다 — 그때는 connectivity_wireless 를 블루투스
    존재 시 true 로 정규화하거나(파서 쪽), 다시 별도 pref 로 나누는 것을 검토한다.
    """
    bluetooth_mice = [c for c in full_mouse_candidates if c.specs.get("connectivity_bluetooth") is True]
    assert bluetooth_mice, "블루투스 마우스가 0건이면 이 사실 확인 자체가 무의미하다"
    assert all(c.specs.get("connectivity_wireless") is True for c in bluetooth_mice)
