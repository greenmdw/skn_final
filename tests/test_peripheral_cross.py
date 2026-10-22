"""모니터↔PC 교차 검사(E12) 테스트 — src/engine/peripheral_cross.py.

DB 불필요. 다룬다: parse_port_version(버전 형식 다양성) · mode_row(버전 하한 탐색) ·
monitor_resolution(ok/fail/unknown) · monitor_gpu_port(GPU 데이터 없음/있음, ok/fail/unknown,
QHD_WIDE 미지원 등급) · monitor_usb_c(해당/비해당, ok/fail/unknown) · cross_issues(판정·감점·
판정어 금지) · run_peripherals의 pc_context 유무에 따른 확장/불변.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import CONFIDENCE_THRESHOLD
from src.dto import Candidate
from src.engine import peripheral_cross as pc
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import run_peripherals
from src.engine.stage3c_verify import _BANNED_KOREAN_VERDICTS

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_NOLOG = lambda _m: None  # noqa: E731


def _rules():
    return load_peripheral_rules()


def _monitor_candidates() -> dict[str, Candidate]:
    cands = load_peripheral_candidates_from_csv(_FIXTURES, _rules())
    return {c.name: c for c in cands["monitor"]}


def _monitor(specs: dict, **kwargs) -> Candidate:
    return Candidate(product_key=kwargs.pop("product_key", "m1"), slot="monitor",
                     name=kwargs.pop("name", "monitor"), price=kwargs.pop("price", 100000),
                     specs=specs, **kwargs)


# ── parse_port_version ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("2", (2, 0)),
    ("2.0b", (2, 0)),
    ("1.2a", (1, 2)),
    ("1.4", (1, 4)),
    (2, (2, 0)),
    (2.1, (2, 1)),
])
def test_parse_port_version_recognized_formats(raw, expected):
    assert pc.parse_port_version(raw) == expected


@pytest.mark.parametrize("raw", ["없음"])
def test_parse_port_version_absent(raw):
    assert pc.parse_port_version(raw) == "absent"


@pytest.mark.parametrize("raw", ["미표기", "", None, "   ", "abc"])
def test_parse_port_version_unknown(raw):
    assert pc.parse_port_version(raw) is None


# ── mode_row ─────────────────────────────────────────────────────────────
def test_mode_row_picks_highest_version_at_or_below():
    rules = _rules()
    # 2.0b 는 표에 없다 -> 2.0 이하 중 가장 높은 버전(2.0) 행을 쓴다.
    assert pc.mode_row("hdmi", (2, 0), rules) == rules["verify"]["port_modes"]["hdmi"]["2.0"]


def test_mode_row_none_when_below_all_versions():
    rules = _rules()
    assert pc.mode_row("dp", (1, 0), rules) is None


# ── monitor_resolution ───────────────────────────────────────────────────
def test_monitor_resolution_ok_when_class_matches_pc_target():
    rules = _rules()
    mon = _monitor_candidates()["LG UltraGear 27GP850"]   # QHD
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=None,
                                      target_refresh_hz=None, rules=rules)
    res_check = next(c for c in checks if c["axis"] == "monitor_resolution")
    assert res_check["state"] == "ok"


def test_monitor_resolution_fail_when_class_differs():
    rules = _rules()
    mon = _monitor_candidates()["LG UltraGear 27GP850"]   # QHD monitor
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs=None,
                                      target_refresh_hz=None, rules=rules)
    res_check = next(c for c in checks if c["axis"] == "monitor_resolution")
    assert res_check["state"] == "fail"


def test_monitor_resolution_unknown_when_monitor_class_missing():
    rules = _rules()
    mon = _monitor(specs={})   # resolution_class 없음(파싱 실패/공란)
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=None,
                                      target_refresh_hz=None, rules=rules)
    res_check = next(c for c in checks if c["axis"] == "monitor_resolution")
    assert res_check["state"] == "unknown"


# ── monitor_gpu_port ─────────────────────────────────────────────────────
def test_monitor_gpu_port_unknown_when_no_gpu_data():
    rules = _rules()
    mon = _monitor_candidates()["LG UltraGear 27GP850"]
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=None,
                                      target_refresh_hz=165, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "unknown"
    assert port_check["detail"] == "그래픽카드 출력 단자 정보가 없어 확인하지 못했습니다"


def test_monitor_gpu_port_unknown_when_gpu_specs_lack_keys():
    rules = _rules()
    mon = _monitor_candidates()["LG UltraGear 27GP850"]
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs={"unrelated": 1},
                                      target_refresh_hz=165, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "unknown"
    assert port_check["detail"] == "그래픽카드 출력 단자 정보가 없어 확인하지 못했습니다"


def test_monitor_gpu_port_ok_qhd_165_via_dp():
    """QHD 165Hz 목표 — Samsung(HDMI2/DP1.2)은 DP1.2 쪽이 QHD 165Hz를 지원해 ok가 된다."""
    rules = _rules()
    mon = _monitor_candidates()["Samsung Odyssey G5 G50F LS27FG504"]
    gpu = {"hdmi_version": "2.1", "hdmi_ports": 1, "dp_version": "1.4", "dp_ports": 1,
          "usb_c_video_out": True}
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=gpu,
                                      target_refresh_hz=165, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "ok"


def test_monitor_gpu_port_fail_uhd_144_hdmi_only_and_gpu_missing_dp():
    """UHD 144Hz 목표 — 양쪽 다 HDMI 2.0뿐이면 대역폭이 모자라고(UHD 60Hz뿐),
    GPU dp_ports=0 이라 DP 쪽은 아예 없다 — 두 단자 모두 판정 가능한데 어느 쪽도 안 돼 fail."""
    rules = _rules()
    mon = _monitor(specs={
        "resolution_class": "UHD", "refresh_hz": 60.0,
        "hdmi_version_raw": "2.0", "hdmi_ports": 1,
        "dp_version_raw": "1.4", "dp_ports": 1,
    })
    gpu = {"hdmi_version": "2.0", "hdmi_ports": 1, "dp_version": "1.4", "dp_ports": 0,
          "usb_c_video_out": True}
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs=gpu,
                                      target_refresh_hz=144, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "fail"


def test_monitor_gpu_port_unknown_for_qhd_wide_not_in_table():
    rules = _rules()
    mon = _monitor_candidates()["ASUS ProArt PA34VCNV"]   # QHD_WIDE
    gpu = {"hdmi_version": "2.1", "hdmi_ports": 1, "dp_version": "1.4", "dp_ports": 1,
          "usb_c_video_out": True}
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=gpu,
                                      target_refresh_hz=165, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "unknown"


def test_monitor_gpu_port_unknown_when_version_below_table_and_other_absent():
    """HDMI 1.0처럼 표의 가장 낮은 버전(1.4)보다 낮은 버전은 fail이 아니라 unknown이다 —
    잠정 표의 빈 구간일 뿐, 실제로 대역폭이 부족하다고 확인된 게 아니다(계획 §4 원칙 2).
    DP 쪽은 모니터에 단자가 없어(absent) 전체 판정도 fail로 단정하지 않고 unknown이 된다."""
    rules = _rules()
    mon = _monitor(specs={
        "resolution_class": "FHD", "refresh_hz": 60.0,
        "hdmi_version_raw": "1.0", "hdmi_ports": 1,
        "dp_version_raw": "없음", "dp_ports": 0,
    })
    gpu = {"hdmi_version": "2.1", "hdmi_ports": 1, "dp_version": "2.1", "dp_ports": 1,
          "usb_c_video_out": True}
    checks = pc.monitor_cross_checks(mon, pc_resolution="FHD_144", gpu_specs=gpu,
                                      target_refresh_hz=60, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "unknown"
    assert "HDMI: 1.0 버전은 단자 대역폭 표에 없어 확인하지 못했습니다" in port_check["detail"]


def test_mode_row_none_below_table_yields_unknown_not_fail_directly():
    """mode_row 자체는 여전히 None을 내지만(표에 없다는 사실 그대로), 그 None을 fail로
    바꾸던 예전 동작이 없어졌다는 것을 _iface_state 경유로 재확인한다."""
    rules = _rules()
    assert pc.mode_row("hdmi", (1, 0), rules) is None   # 표는 "1.4"부터 시작한다


def test_monitor_gpu_port_never_fails_when_one_interface_unknown():
    """HDMI 쪽은 부족(fail)해도 DP 쪽 GPU 정보가 아예 없으면(모름) 전체를 fail로 단정하지
    않는다(계획 §4 원칙 2 — 모르는 것은 Pending)."""
    rules = _rules()
    mon = _monitor(specs={
        "resolution_class": "UHD", "refresh_hz": 60.0,
        "hdmi_version_raw": "2.0", "hdmi_ports": 1,
        "dp_version_raw": "1.4", "dp_ports": 1,
    })
    gpu = {"hdmi_version": "2.0", "hdmi_ports": 1}   # dp_version/dp_ports 키 자체가 없음
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs=gpu,
                                      target_refresh_hz=144, rules=rules)
    port_check = next(c for c in checks if c["axis"] == "monitor_gpu_port")
    assert port_check["state"] == "unknown"


# ── monitor_usb_c ────────────────────────────────────────────────────────
def test_monitor_usb_c_not_applicable_when_hdmi_or_dp_present():
    rules = _rules()
    mon = _monitor_candidates()["LG UltraGear 27GP850"]   # HDMI/DP 있음
    checks = pc.monitor_cross_checks(mon, pc_resolution="QHD_165", gpu_specs=None,
                                      target_refresh_hz=165, rules=rules)
    assert all(c["axis"] != "monitor_usb_c" for c in checks)


def test_monitor_usb_c_applicable_ok_when_gpu_supports():
    rules = _rules()
    mon = _monitor_candidates()["Apple Studio Display (2026)"]   # Thunderbolt만, HDMI/DP 없음
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs={"usb_c_video_out": True},
                                      target_refresh_hz=60, rules=rules)
    usb_check = next(c for c in checks if c["axis"] == "monitor_usb_c")
    assert usb_check["state"] == "ok"


def test_monitor_usb_c_applicable_fail_when_gpu_does_not_support():
    rules = _rules()
    mon = _monitor_candidates()["Apple Studio Display (2026)"]
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs={"usb_c_video_out": False},
                                      target_refresh_hz=60, rules=rules)
    usb_check = next(c for c in checks if c["axis"] == "monitor_usb_c")
    assert usb_check["state"] == "fail"


def test_monitor_usb_c_applicable_unknown_when_gpu_data_missing():
    rules = _rules()
    mon = _monitor_candidates()["Apple Studio Display (2026)"]
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs=None,
                                      target_refresh_hz=60, rules=rules)
    usb_check = next(c for c in checks if c["axis"] == "monitor_usb_c")
    assert usb_check["state"] == "unknown"
    assert usb_check["detail"] == "그래픽카드 출력 단자 정보가 없어 확인하지 못했습니다"


# ── cross_issues ─────────────────────────────────────────────────────────
def test_cross_issues_ok_makes_no_issue():
    checks = [{"axis": "monitor_resolution", "label": "라벨", "state": "ok", "detail": "d"}]
    assert pc.cross_issues(checks) == []


def test_cross_issues_unknown_penalty_and_judge():
    checks = [{"axis": "monitor_gpu_port", "label": "라벨", "state": "unknown", "detail": "확인 안 됨"}]
    issues = pc.cross_issues(checks)
    assert len(issues) == 1
    assert issues[0].judge == "확인 필요"
    assert issues[0].penalty == 6


def test_cross_issues_fail_penalty_and_judge():
    checks = [{"axis": "monitor_gpu_port", "label": "라벨", "state": "fail", "detail": "부족함"}]
    issues = pc.cross_issues(checks)
    assert len(issues) == 1
    assert issues[0].judge == "위반"
    assert issues[0].penalty == 20


def test_cross_issues_text_has_no_verdict_words():
    rules = _rules()
    mon = _monitor(specs={
        "resolution_class": "UHD", "refresh_hz": 60.0,
        "hdmi_version_raw": "2.0", "hdmi_ports": 1,
        "dp_version_raw": "1.4", "dp_ports": 1,
    })
    gpu = {"hdmi_version": "2.0", "hdmi_ports": 1, "dp_version": "1.4", "dp_ports": 0,
          "usb_c_video_out": True}
    checks = pc.monitor_cross_checks(mon, pc_resolution="4K", gpu_specs=gpu,
                                      target_refresh_hz=144, rules=rules)
    issues = pc.cross_issues(checks)
    assert issues   # 이 시나리오는 fail 쟁점이 최소 1건 나온다
    for issue in issues:
        assert not any(word in issue.text for word in _BANNED_KOREAN_VERDICTS)


# ── run_peripherals(pc_context) ───────────────────────────────────────────
def test_run_peripherals_without_pc_context_is_unchanged():
    values = {"peripherals": ["monitor"], "resolution": "QHD_165"}
    cands = load_peripheral_candidates_from_csv(_FIXTURES, _rules())
    result = run_peripherals(values, cands, _NOLOG)
    pick = next(p for p in result.picks if p.kind == "monitor")
    assert pick.checks == []


def test_run_peripherals_with_pc_context_adds_monitor_checks_and_issue():
    values = {"peripherals": ["monitor"], "resolution": "QHD_165"}
    cands = load_peripheral_candidates_from_csv(_FIXTURES, _rules())
    pc_context = {"resolution": "QHD_165", "gpu_specs": None}   # GPU 데이터 없음 -> 단자축 unknown
    result = run_peripherals(values, cands, _NOLOG, pc_context=pc_context)
    pick = next(p for p in result.picks if p.kind == "monitor")
    assert pick.checks   # 비지 않음 — E12 검사가 실제로 돌았다
    assert any(c["axis"] == "monitor_gpu_port" and c["state"] == "unknown" for c in pick.checks)

    target = next(t for t in result.verification.targets if t.subject == "모니터")
    assert any(i.axis == "monitor_gpu_port" for i in target.issues)
    assert target.confidence <= 100 - 6
    assert target.passed is (target.confidence >= CONFIDENCE_THRESHOLD)


def test_run_peripherals_pc_context_without_monitor_pick_is_noop():
    """모니터를 요청하지 않았으면 pc_context가 있어도 아무 효과가 없다."""
    values = {"peripherals": ["mouse"], "purpose": "game"}
    cands = load_peripheral_candidates_from_csv(_FIXTURES, _rules())
    pc_context = {"resolution": "QHD_165", "gpu_specs": {"hdmi_version": "2.1"}}
    result = run_peripherals(values, cands, _NOLOG, pc_context=pc_context)
    assert all(p.checks == [] for p in result.picks)
