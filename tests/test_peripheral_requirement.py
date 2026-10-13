"""주변기기 요구사양 룩업(E10) 테스트 — src/engine/peripheral_requirement.py.

DB 불필요(마지막 두 절의 "전체 CSV" 테스트만 data/peripherals/*_processed.csv 원본을
읽는다 — DB 접속은 아니다). 계획 §3.3 E10의 완료 기준: QHD_165 하드 조건, 해상도 미지정 시
기본값(FHD_144)+assumed, 4K의 용도별 주사율 하한, 목적·상황 풀이 선호와 직접 말한 조건의 거르기,
요청하지 않은 종류 배제, 잘못된 설정에서 PeripheralRuleError, C6(기본 조건에서 모니터 0건) 사실 고정,
마우스 블루투스⊆무선 사실 고정(코디네이터 리뷰 반영 — 아래 참고).
"""
from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.config import ROOT
from src.engine import peripheral_intent
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


def test_missing_resolution_defaults_to_qhd_with_assumed_and_note():
    """해상도를 말하지 않으면 주변기기 기본값(QHD_165)을 쓴다. PC 규칙의 기본(FHD_144)은 카탈로그에
    맞는 모니터가 없어 첫 요청이 항상 비었기 때문에 쓰지 않는다."""
    reqs = build_requirements({}, ["monitor"])
    req = reqs["monitor"]
    assert req.hard == {"resolution_class": ["QHD"], "refresh_min_hz": 165}
    assert req.assumed == ["resolution"]
    assert len(req.notes) == 1
    assert "해상도" in req.notes[0] and "기본값" in req.notes[0] and "QHD" in req.notes[0]


def test_4k_refresh_min_hz_depends_on_purpose():
    game = build_requirements({"resolution": "4K", "purpose": "game"}, ["monitor"])["monitor"]
    office = build_requirements({"resolution": "4K", "purpose": "office"}, ["monitor"])["monitor"]
    assert game.hard == {"resolution_class": ["UHD"], "refresh_min_hz": 120}
    assert office.hard == {"resolution_class": ["UHD"], "refresh_min_hz": 60}


# ── 선호와 거르기: 목적 풀이(peripheral_intent.resolve)가 만든 값을 옮겨 담는다 ─────────────────
def _req(raw_input: dict, kinds: list[str], **values) -> dict:
    interp = peripheral_intent.sanitize({"kinds": kinds, **raw_input})
    return build_requirements(
        {"peripheral_resolved": peripheral_intent.resolve(interp), **values}, kinds,
    )


def test_quiet_situation_prefers_non_clicky_keyboard_switch():
    req = _req({"situations": ["quiet_place"]}, ["keyboard"])["keyboard"]
    assert {"key": "switch_clicky", "op": "equals", "value": False} in req.soft["preferences"]


def test_fps_prefers_magnetic_and_rapid_trigger_keyboard():
    req = _req({"purposes": ["fps"]}, ["keyboard"])["keyboard"]
    prefs = req.soft["preferences"]
    assert {"key": "switch_magnetic", "op": "equals", "value": True} in prefs
    assert {"key": "rapid_trigger", "op": "equals", "value": True} in prefs
    assert req.filters == []          # 목적에서 풀린 조건은 거르지 않는다


def test_fps_prefers_light_high_polling_mouse():
    prefs = _req({"purposes": ["fps"]}, ["mouse"])["mouse"].soft["preferences"]
    assert {"key": "polling_hz_max", "op": "min", "value": 4000} in prefs
    assert {"key": "weight_g", "op": "max", "value": 80} in prefs


def test_general_game_does_not_narrow_mouse_specs():
    """"게임용"이라고만 하면 게임(일반)이고 스펙을 좁히지 않는다(견적 입력 설계 5.1)."""
    req = _req({"purposes": ["game"]}, ["mouse"])["mouse"]
    assert req.soft == {} and req.filters == []


def test_office_prefers_only_wireless_mouse():
    """무선만 선호로 둔다(블루투스는 별도 pref 없음) — 아래 전체 카탈로그 고정 테스트가 이유(블루투스는 항상
    무선의 부분집합으로 관측됨)를 증명한다."""
    prefs = _req({"purposes": ["office"]}, ["mouse"])["mouse"].soft["preferences"]
    assert prefs == [{"key": "connectivity_wireless", "op": "equals", "value": True}]


def test_desk_casual_prefers_small_usb_powered_speaker():
    prefs = _req({"purposes": ["desk_casual"]}, ["speaker"])["speaker"].soft["preferences"]
    assert {"key": "power_source_raw", "op": "contains_any", "value": ["USB"]} in prefs
    assert {"key": "size_longest_mm", "op": "max", "value": 200} in prefs


def test_creative_prefers_ips_and_high_resolution_monitor():
    prefs = _req({"purposes": ["creative"]}, ["monitor"], resolution="QHD_165")["monitor"].soft["preferences"]
    assert {"key": "panel_raw", "op": "contains_any", "value": ["IPS"]} in prefs
    assert {"key": "resolution_h", "op": "min", "value": 2160} in prefs


def test_purpose_missing_from_a_kind_table_does_nothing_for_that_kind():
    """같은 코드가 표에 없는 종류에는 아무 일도 하지 않는다(종류를 가리지 않은 말은 있는 종류에만 적용)."""
    reqs = _req({"purposes": ["office"]}, ["mouse", "speaker"])
    assert reqs["mouse"].soft != {}
    assert reqs["speaker"].soft == {}


def test_stated_filterable_condition_filters_and_is_not_a_preference():
    req = _req({"stated": {"mouse": ["wireless"]}}, ["mouse"])["mouse"]
    assert req.filters == [{"key": "connectivity_wireless", "op": "equals", "value": True}]
    assert req.soft == {}


def test_stated_threshold_condition_is_only_a_preference():
    """임계값이 잠정인 조건(가벼운 무게)은 직접 말해도 거르지 않는다 — 거르면 제품이 사라진다."""
    req = _req({"stated": {"mouse": ["lightweight"]}}, ["mouse"])["mouse"]
    assert req.filters == []
    assert req.soft["preferences"] == [{"key": "weight_g", "op": "max", "value": 80}]


def test_condition_in_filters_is_not_repeated_as_preference():
    req = _req({"purposes": ["portable"], "stated": {"mouse": ["wireless"]}}, ["mouse"])["mouse"]
    assert {"key": "connectivity_wireless", "op": "equals", "value": True} not in req.soft["preferences"]
    assert {"key": "connectivity_bluetooth", "op": "equals", "value": True} in req.soft["preferences"]


def test_no_resolved_input_gives_empty_soft_and_filters():
    req = build_requirements({}, ["speaker"])["speaker"]
    assert req.soft == {} and req.filters == []


# ── 요청하지 않은 종류는 결과에 없음 ────────────────────────────────────────
def test_unrequested_kind_not_in_result():
    reqs = _req({"purposes": ["fps"]}, ["keyboard"])
    assert set(reqs) == {"keyboard"}


def test_empty_kinds_list_gives_empty_result():
    assert build_requirements({"resolution": "QHD_165"}, []) == {}


# ── 잘못된 설정은 PeripheralRuleError ──────────────────────────────────────
def test_unknown_spec_key_in_spec_conditions_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["spec_conditions"]["mouse"]["wireless"]["prefs"][0]["key"] = "totally_made_up_key"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="spec 키"):
        pr.load_peripheral_rules(path)


def test_unknown_operator_in_spec_conditions_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["spec_conditions"]["mouse"]["wireless"]["prefs"][0]["op"] = "greater_than_maybe"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="연산자"):
        pr.load_peripheral_rules(path)


def test_min_op_with_non_numeric_value_raises(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["spec_conditions"]["mouse"]["lightweight"]["prefs"][0].update(op="min", value="not-a-number")
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="숫자"):
        pr.load_peripheral_rules(path)


def test_purpose_prefer_must_name_an_existing_condition(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["purposes"]["mouse"]["office"]["prefer"] = ["no_such_condition"]
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="spec_conditions 에 없는 이름"):
        pr.load_peripheral_rules(path)


def test_spec_condition_filter_must_be_boolean(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["spec_conditions"]["mouse"]["wireless"]["filter"] = "yes"
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="true/false"):
        pr.load_peripheral_rules(path)


def test_pc_purpose_map_must_name_existing_purposes(tmp_path):
    rules = deepcopy(pr.load_peripheral_rules())
    rules["pc_purpose_map"]["game"] = ["not_a_purpose"]
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="purposes 에 없는 이름"):
        pr.load_peripheral_rules(path)


def test_removed_requirements_soft_section_is_rejected(tmp_path):
    """요구사양의 소프트 선호(when/prefs)는 목적 풀이 표로 대체됐다. 남아 있으면 조용히 무시하지 않고 오류다."""
    rules = deepcopy(pr.load_peripheral_rules())
    rules["requirements"]["keyboard"] = {"soft": [{"when": {"purpose": "game"}, "prefs": []}]}
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="monitor 하나만"):
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
    rules["requirements"]["keyboard"] = {"hard": {"resolution_class_by_res": {}}}
    path = _write(tmp_path, rules)
    with pytest.raises(pr.PeripheralRuleError, match="monitor 하나만"):
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
