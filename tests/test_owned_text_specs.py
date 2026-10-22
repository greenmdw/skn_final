"""견적 글에서 스펙 더 읽기 — 카탈로그에 없는 부품도 글에 적힌 표기에서 호환 검사용 값을 얻는다.

글에 그대로 적힌 값은 확정("글에서 읽음"), 이름의 관례로 짐작한 값은 추정으로 표시된다. 못 읽으면 비워 둔다 —
호환 검사가 비호환으로 단정하지 않고 "확인 못 함"으로 넘긴다.
"""
from __future__ import annotations

import pytest

from src.engine.owned_parts import _specs_from_text, resolve_owned_parts
from src.services import quote_review_service as qrs


def read(slot: str, text: str) -> dict:
    return _specs_from_text(slot, text)[0]


def inferred(slot: str, text: str) -> set[str]:
    return _specs_from_text(slot, text)[1]


# ── RAM ────────────────────────────────────────────────────────────────────────────
def test_ram_speed_capacity_and_kit_are_read():
    spec = read("RAM", "G.SKILL DDR5-6000 CL30 16GB x2")
    assert spec == {"mem_type": "DDR5", "speed_mts": 6000, "capacity_gb": 32, "module_config": "16GB × 2"}


def test_ram_single_stick_and_mhz_notation():
    spec = read("RAM", "삼성전자 DDR4 3200MHz 8GB")
    assert spec == {"mem_type": "DDR4", "speed_mts": 3200, "capacity_gb": 8}


def test_ram_kit_written_in_parentheses():
    assert read("RAM", "DDR5 32GB (16Gx2)")["module_config"] == "16GB × 2"


def test_ram_without_a_speed_or_capacity_is_not_guessed():
    assert read("RAM", "DDR5 램") == {"mem_type": "DDR5"}


# ── 메인보드 ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,form,guessed", [
    ("ASUS ROG STRIX Z790-E GAMING ATX", "ATX", False),
    ("MSI MPG Z790 EDGE M-ATX", "mATX", False),
    ("ASRock X870E Taichi E-ATX", "E-ATX", False),
    ("GIGABYTE B650I AORUS Mini-ITX", "Mini-ITX", False),
    ("어떤회사 PRO B760M-P DDR4", "mATX", True),       # 칩셋 뒤의 M = mATX 관례
    ("어떤회사 H610M-K", "mATX", True),
])
def test_board_form_factor_is_read_or_marked_as_a_guess(text, form, guessed):
    assert read("메인보드", text)["form_factor"] == form
    assert ("form_factor" in inferred("메인보드", text)) is guessed


def test_a_board_without_size_hints_gets_no_form_factor():
    assert "form_factor" not in read("메인보드", "ASUS ROG STRIX X870-A")     # 칩셋에 M 이 없다 → 모른다
    assert "form_factor" not in read("메인보드", "어떤회사 B650 PRO")


# ── 파워 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,form,guessed", [
    ("Corsair SF750 SFX-L 750W", "SFX-L", False),
    ("Corsair SF750 SFX 750W", "SFX", False),
    ("잘만 700W ATX 3.0", "ATX", True),                # ATX 3.0 은 규격 이름 — 폼팩터는 추정
])
def test_psu_form_factor(text, form, guessed):
    assert read("파워", text)["form_factor"] == form
    assert ("form_factor" in inferred("파워", text)) is guessed


def test_psu_wattage_is_still_read_and_not_overwritten():
    assert read("파워", "SFX-L 750W")["wattage_w"] == 750


# ── 케이스 ─────────────────────────────────────────────────────────────────────────
def test_case_listed_forms_are_read_and_tower_size_is_a_guess():
    assert read("케이스", "어떤 케이스 ATX / mATX 지원") == {"supports_form_factors": ["ATX", "mATX"]}
    assert read("케이스", "미들타워 게이밍 케이스") == {"supports_form_factors": ["ATX"]}
    assert inferred("케이스", "미들타워 게이밍 케이스") == {"supports_form_factors"}
    assert inferred("케이스", "어떤 케이스 ATX 지원") == set()
    assert read("케이스", "그냥 케이스") == {}


# ── 쿨러 ───────────────────────────────────────────────────────────────────────────
def test_cooler_liquid_with_radiator_size_and_air_with_height():
    liquid = read("쿨러", "NZXT Kraken 240 수랭 쿨러")
    assert liquid == {"cooling_type": "Liquid (AIO)", "radiator_mm": 240}
    assert "radiator_mm" in inferred("쿨러", "NZXT Kraken 240 수랭 쿨러")
    assert read("쿨러", "공랭 쿨러 높이 155mm") == {"cooling_type": "Air", "height_mm": 155}


def test_a_cooler_name_with_airflow_is_not_read_as_air_cooled():
    assert "cooling_type" not in read("쿨러", "그냥 쿨러 AIRFLOW 모델")


# ── 저장장치 ───────────────────────────────────────────────────────────────────────
def test_storage_form_and_pcie_generation():
    assert read("저장장치", "WD SN770 1TB M.2 NVMe Gen4") == {
        "form_factor": "M.2", "interface": "PCIe 4.0 x4", "capacity_gb": 1000}
    assert read("저장장치", "삼성 990 PRO 500GB")["capacity_gb"] == 500
    assert read("저장장치", "Crucial P3 Plus 2TB")["capacity_gb"] == 2000
    assert read("저장장치", "삼성 M.2 2280 NVMe PCIe 5.0")["form_factor"] == "M.2 2280"
    assert read("저장장치", "SATA SSD 500GB") == {"form_factor": "2.5-inch SATA", "capacity_gb": 500}


# ── 호환 검사에 이어진다 ──────────────────────────────────────────────────────────
def _check(quote: dict, axis: str) -> dict:
    review = qrs.analyze(quote, by_slot={})                # 카탈로그 대응 없이 글만으로
    return next(c for c in review["compat"]["checks"] if c["axis"] == axis)


def test_written_sizes_drive_the_board_case_check_without_a_catalog_match():
    fail = _check({"메인보드": "어떤회사 X870E E-ATX", "케이스": "미니타워 케이스"}, "motherboard_case")
    assert fail["state"] == "fail" and "E-ATX" in fail["detail"]
    ok = _check({"메인보드": "어떤회사 B760M-P", "케이스": "미들타워 케이스"}, "motherboard_case")
    assert ok["state"] == "ok"


def test_ram_speed_and_capacity_drive_the_ram_checks_only_when_the_board_data_exists():
    """글에서 읽은 RAM 값은 채워지지만 보드 쪽 값(최대 속도·용량)을 모르면 여전히 "확인 못 함"이다."""
    row = _check({"RAM": "DDR5-6000 16GB x2", "메인보드": "어떤회사 B650M"}, "ram_speed")
    assert row["state"] == "unknown" and "6000" not in row["detail"].split("—")[-1]


def test_liquid_cooler_radiator_and_case_support_are_compared_when_both_are_known():
    """이 검사는 카탈로그 스펙이 있어야 비교되고, 글만으로는 케이스의 라디에이터 지원을 모르니 확인 못 함으로 남는다."""
    row = _check({"쿨러": "NZXT Kraken 360 수랭", "케이스": "미들타워 케이스"}, "radiator")
    assert row["state"] == "unknown"


def test_read_values_are_reported_as_read_or_inferred_in_the_resolved_parts():
    owned = resolve_owned_parts({"메인보드": "어떤회사 B760M-P DDR4"}, {}, ["메인보드"])["메인보드"]
    assert owned["source"] == "inferred" and {"socket", "form_factor"} <= set(owned["inferred"])
    assert owned["specs"]["mem_type"] == "DDR4"
