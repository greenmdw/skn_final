"""catalog_repo.py의 실제 PC 카탈로그 경로(0015_pc_parts_category_specs.sql) 관련
순수 함수 — "8 / 16" 같은 라인업 표기 파싱과, DB 행 -> Candidate.specs 매핑이
stage4_optimize.py/stage3a_hardfilter.py가 기대하는 키 이름과 맞는지 확인한다.
DB 접속이 필요 없는 순수 함수만 테스트한다(load_candidates_by_slot_from_db 자체는
conn이 필요해 여기서 다루지 않는다)."""
from __future__ import annotations

import pytest

from src.repo.catalog_repo import _parse_max_capacity_gb, _parse_max_number, _specs_from_row


@pytest.mark.parametrize("raw, expected", [
    ("8 / 16", 16), ("4 / 8", 8), ("16", 16), (None, None), ("", None), (24, 24),
])
def test_parse_max_number_picks_the_largest_value_in_a_lineup_label(raw, expected):
    assert _parse_max_number(raw) == expected


@pytest.mark.parametrize("raw, expected_gb", [
    ("1TB / 2TB / 4TB", 4000), ("512GB", 512), ("2TB", 2000), (None, None), ("", None),
])
def test_parse_max_capacity_gb_converts_tb_to_gb_and_takes_the_max(raw, expected_gb):
    assert _parse_max_capacity_gb(raw) == expected_gb


def test_specs_from_row_cpu_maps_socket_tdp_and_memory_type():
    row = {"socket": "AM5", "tdp_w": 65, "memory_type": "DDR5"}
    specs = _specs_from_row("cpu", row)
    assert specs == {"socket": "AM5", "tdp_w": 65, "mem_type": "DDR5"}


def test_specs_from_row_gpu_parses_lineup_vram_to_a_single_max_number():
    row = {"length_mm": 304, "power_w": 320, "vram_gb": "8 / 16"}
    specs = _specs_from_row("gpu", row)
    assert specs["vram_gb"] == 16
    assert specs["length_mm"] == 304 and specs["power_w"] == 320


def test_specs_from_row_case_splits_supported_motherboard_into_a_list():
    row = {"gpu_max_length_mm": 400, "cpu_cooler_height_mm": 170, "supported_motherboard": "ATX / mATX"}
    specs = _specs_from_row("case", row)
    assert specs["max_gpu_len_mm"] == 400
    assert specs["max_cooler_height_mm"] == 170
    assert specs["supports_form_factors"] == ["ATX", "mATX"]


def test_specs_from_row_ssd_uses_protocol_not_interface_for_nvme_check():
    # 인터페이스(PCIe 세대)와 프로토콜(NVMe/SATA)은 원본 데이터에서 서로 다른
    # 컬럼이다 — stage3a_hardfilter가 target["interface"]("NVMe")를 비교할 때
    # 이 protocol 값을 봐야 한다(회귀: 예전엔 interface 컬럼만 옮기고 있었다).
    row = {"interface": "PCIe 4.0 x4", "protocol": "NVMe", "form_factor": "M.2 2280",
           "capacity_options": "1TB / 2TB"}
    specs = _specs_from_row("ssd", row)
    assert specs["protocol"] == "NVMe"
    assert specs["interface"] == "PCIe 4.0 x4"
    assert specs["capacity_gb"] == 2000


def test_specs_from_row_missing_values_are_simply_absent_not_none():
    # "정보 없음"은 빈 dict 항목 부재로 표현한다 — None을 넣지 않는다. 그래야
    # stage3a/stage4가 .get(key)로 조회했을 때 "값이 None"과 "키가 없음"을 굳이
    # 구분할 필요 없이 둘 다 falsy/None으로 자연스럽게 처리된다.
    specs = _specs_from_row("psu", {"wattage_w": None, "efficiency_rating": None})
    assert specs == {}
