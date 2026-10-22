"""0018 확장 열 검사 — GPU 케이블 개수·파워 길이·GPU 두께·수랭 라디에이터·RAM 슬롯/속도·M.2, 그리고 CPU 최대 전력(PL2).

값이 비어 있으면 "확인 못 함"이고 감점·이슈로 세지 않는다(값이 채워지는 만큼 켜진다). 실제 카탈로그에서는 값이 있는 만큼만 판정한다.
"""
from __future__ import annotations

import pytest

from src.dto import Candidate, RequirementSpec
from src.engine.compat_parse import (gpu_power_count_fit, gpu_power_options, parse_module_count, parse_pcie_gens,
                                     parse_size_list, slots_needed)
from src.engine.stage2_requirement import load_computer_rules
from src.engine.stage4_optimize import _pc_known_failures, pc_compat_details, pc_link_check

RULES = load_computer_rules()["verification"]


def _cand(slot, name="x", **specs):
    return Candidate(slot=slot, product_key=name, name=name, price=1, specs=specs)


def _spec(**kw):
    return RequirementSpec(list_id="t", category="computer", mode="build", **kw)


def _rows(chosen):
    return {r["axis"]: r for r in pc_compat_details(chosen, _spec(), RULES)}


def _fails(chosen):
    return _pc_known_failures(chosen, _spec(), RULES)


# ── 파서 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("2× 8-pin", ((2, 0),)), ("1× 8-pin + 1× 6-pin", ((2, 0),)), ("1× 16-pin (12V-2x6)", ((0, 1),)),
    ("1× 16-pin 또는 2× 8-pin", ((0, 1), (2, 0))), ("1× 8-pin 또는 16-pin", ((1, 0), (0, 1))),
    ("슬롯 전력", None), ("제조사 모델별 상이", None), ("", None), (None, None),
])
def test_gpu_power_options(text, expected):
    assert gpu_power_options(text) == expected


@pytest.mark.parametrize("gpu, aux, pcie, n16, state", [
    ("2× 8-pin", "O", 3, 1, "ok"), ("2× 8-pin", "O", 2, 0, "ok"), ("2× 8-pin", "O", 1, 1, "fail"),
    ("1× 16-pin (12V-2x6)", "O", 4, 1, "ok"), ("1× 16-pin (12V-2x6)", "O", 4, 0, "adapter"),
    ("1× 16-pin (12V-2x6)", "O", 1, 0, "fail"),                # 어댑터로 연결할 PCIe 커넥터도 모자란다
    ("1× 16-pin 또는 2× 8-pin", "O", 3, 0, "ok"),              # 대안 표기: 하나만 채워도 된다
    ("슬롯 전력", "X", 0, 0, "ok"), ("2× 8-pin", "O", None, 1, None),
])
def test_gpu_power_count_fit(gpu, aux, pcie, n16, state):
    assert gpu_power_count_fit(gpu, aux, pcie, n16)[0] == state


def test_unknown_pcie_count_never_becomes_a_failure_for_a_16pin_gpu():
    """회귀: 8핀 개수가 비어 있는 파워(ABKO SETTLER-II)가 16핀 GPU 와 짝지어져 fail 8쌍이 나왔다."""
    assert gpu_power_count_fit("1× 16-pin (12V-2x6)", "O", None, 0)[0] is None


def test_small_parsers():
    assert parse_size_list("120;140;240;280") == (120, 140, 240, 280)
    assert parse_size_list(360) == (360,) and parse_size_list(None) == ()
    assert parse_module_count("16GB × 2") == 2 and parse_module_count("32GB x 1") == 1 and parse_module_count("") is None
    assert parse_pcie_gens("PCIe 4.0 x4 / 5.0 x2") == (4.0, 5.0) and parse_pcie_gens("5;4;4") == (5.0, 4.0, 4.0)
    assert parse_pcie_gens("SATA III 6Gb/s") == ()
    assert slots_needed(2.5) == 3 and slots_needed("2.0") == 2 and slots_needed(None) is None


# ── GPU 전원 커넥터 개수 (엔진) ────────────────────────────────────────────────
def test_cable_count_fails_and_passes_in_the_engine():
    gpu = _cand("GPU", power_connector="2× 8-pin", aux_power="O", power_w=200)
    few = _cand("파워", pcie_8pin_count=1, connector_12v2x6_count=1, gpu_power_connector="12V-2x6 / 16-pin")
    enough = _cand("파워", pcie_8pin_count=3, connector_12v2x6_count=1, gpu_power_connector="12V-2x6 / 16-pin")
    assert "gpu_connector" in _fails({"GPU": gpu, "파워": few})
    assert "gpu_connector" not in _fails({"GPU": gpu, "파워": enough})
    row = _rows({"GPU": gpu, "파워": few})["gpu_connector"]
    assert row["state"] == "fail" and "필요 PCIe 커넥터 2개 > 파워 제공" in row["detail"]
    assert _rows({"GPU": gpu, "파워": enough})["gpu_connector"]["state"] == "ok"


def test_without_counts_it_falls_back_to_the_connector_type():
    gpu = _cand("GPU", power_connector="2× 8-pin", aux_power="O")
    psu = _cand("파워", gpu_power_connector="PCIe 8-pin")                     # 개수 열이 없다
    row = _rows({"GPU": gpu, "파워": psu})["gpu_connector"]
    assert row["state"] == "ok" and "개수는 확인하지 않음" in row["detail"]


# ── 파워 길이 · GPU 두께 · 라디에이터 ──────────────────────────────────────────────
def test_psu_length_and_gpu_slots():
    assert "psu_length" in _fails({"파워": _cand("파워", length_mm=200), "케이스": _cand("케이스", max_psu_length_mm=180)})
    assert "psu_length" not in _fails({"파워": _cand("파워", length_mm=160), "케이스": _cand("케이스", max_psu_length_mm=180)})
    assert "gpu_slots" in _fails({"GPU": _cand("GPU", slot_thickness=3.0), "케이스": _cand("케이스", expansion_slots=2)})
    assert "gpu_slots" not in _fails({"GPU": _cand("GPU", slot_thickness=2.5), "케이스": _cand("케이스", expansion_slots=3)})
    row = _rows({"GPU": _cand("GPU", slot_thickness=2.5), "케이스": _cand("케이스", expansion_slots=2)})["gpu_slots"]
    assert row["state"] == "fail" and "3칸 > 케이스 확장 슬롯 2칸" in row["detail"]


def test_radiator_fits_a_position_or_fails_and_air_coolers_are_skipped():
    case = _cand("케이스", radiator_front_mm="120;140;240;280", radiator_top_mm="120;240", radiator_rear_mm="120")
    aio360 = _cand("쿨러", cooling_type="Liquid (AIO)", radiator_mm=360)
    aio240 = _cand("쿨러", cooling_type="Liquid (AIO)", radiator_mm=240)
    assert "radiator" in _fails({"쿨러": aio360, "케이스": case})
    assert "radiator" not in _fails({"쿨러": aio240, "케이스": case})
    assert "전면·상단" in _rows({"쿨러": aio240, "케이스": case})["radiator"]["detail"]
    air = _cand("쿨러", cooling_type="Air (Single-Tower)", height_mm=150)
    assert _rows({"쿨러": air, "케이스": case})["radiator"]["state"] == "skipped"
    assert "radiator" not in _fails({"쿨러": air, "케이스": case})


# ── RAM · M.2 ───────────────────────────────────────────────────────────────
def test_ram_slots_capacity_and_speed():
    board = _cand("메인보드", dimm_slots=2, max_memory_gb=64, max_memory_speed_mts=6000)
    assert "ram_slots" in _fails({"RAM": _cand("RAM", module_config="16GB × 4", capacity_gb=64), "메인보드": board})
    assert "ram_slots" in _fails({"RAM": _cand("RAM", module_config="64GB × 2", capacity_gb=128), "메인보드": board})
    ok = {"RAM": _cand("RAM", module_config="16GB × 2", capacity_gb=32, speed_mts=6400), "메인보드": board}
    assert "ram_slots" not in _fails(ok)
    speed = _rows(ok)["ram_speed"]                                         # 비호환이 아니라 낮은 속도로 동작
    assert speed["state"] == "unknown" and "낮은 속도" in speed["detail"] and not speed["data_missing"]
    assert "ram_speed" not in _fails(ok)


def test_m2_slot_missing_fails_sata_is_skipped_and_gen_warns():
    board0 = _cand("메인보드", m2_slots=0)
    board = _cand("메인보드", m2_slots=2, m2_pcie_gen="4;4")
    assert "m2" in _fails({"저장장치": _cand("저장장치", form_factor="M.2 2280"), "메인보드": board0})
    assert "m2" not in _fails({"저장장치": _cand("저장장치", form_factor="2.5-inch SATA / M.2 2280"), "메인보드": board0})   # SATA 로도 쓸 수 있다
    assert _rows({"저장장치": _cand("저장장치", form_factor="2.5-inch SATA"), "메인보드": board0})["m2"]["state"] == "skipped"
    warn = _rows({"저장장치": _cand("저장장치", form_factor="M.2 2280", interface="PCIe 5.0 x4"), "메인보드": board})["m2"]
    assert warn["state"] == "unknown" and "낮은 속도" in warn["detail"]


# ── 데이터가 비어 있을 때 ───────────────────────────────────────────────────────
def test_missing_extension_data_is_shown_but_not_scored():
    chosen = {"파워": _cand("파워", length_mm=140), "케이스": _cand("케이스", max_gpu_len_mm=400),
              "RAM": _cand("RAM", module_config="16GB × 2"), "메인보드": _cand("메인보드")}
    rows = _rows(chosen)
    for axis in ("psu_length", "ram_slots", "ram_speed"):
        assert rows[axis]["state"] == "unknown" and rows[axis]["data_missing"] and "정보 없음" in rows[axis]["detail"]
    link = pc_link_check(chosen, _spec(), RULES)
    assert not {"psu_length", "ram_slots", "ram_speed", "m2", "gpu_slots", "radiator"} & set(link)     # 감점·이슈로 세지 않는다


# ── CPU 최대 전력(PL2) ─────────────────────────────────────────────────────────
def test_power_uses_the_cpu_peak_power_when_present():
    gpu = _cand("GPU", power_w=300)
    psu = _cand("파워", wattage_w=700)                                     # 700 × 0.9 = 630
    tdp_only = {"CPU": _cand("CPU", tdp_w=125), "GPU": gpu, "파워": psu}       # 125 + 300 = 425 → 통과
    peak = {"CPU": _cand("CPU", tdp_w=125, max_power_w=350), "GPU": gpu, "파워": psu}   # 350 + 300 = 650 > 630 → 실패
    assert "power" not in _fails(tdp_only) and _rows(tdp_only)["power"]["state"] == "ok"
    assert "power" in _fails(peak)
    row = _rows(peak)["power"]
    assert row["state"] == "fail" and "CPU 최대 350W" in row["detail"]
