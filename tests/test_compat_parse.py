"""호환 표기 해석(compat_parse) + 쿨러 소켓·BIOS 축 회귀.

회귀 배경(2026-09-21): 쿨러의 지원 소켓 "LGA1851/1700/1200"을 문자열 포함으로 비교해서 LGA1700 CPU 와 맞는 쿨러가
비호환으로 판정됐다(LGA1700 CPU 15종 × 쿨러 40종 = 600쌍 중 150쌍 오판). BIOS 축은 데이터가 있는데도 항상 "ok (근사)"였다.
"""
from __future__ import annotations

import pytest

from src.dto import Candidate, RequirementSpec
from src.engine.compat_parse import cpu_family, cpu_supported, parse_socket_list, socket_supported, supported_families
from src.engine.stage2_requirement import load_computer_rules
from src.engine.stage4_optimize import _pc_known_failures, pc_link_check

RULES = load_computer_rules()["verification"]


# ── 소켓 표기 ────────────────────────────────────────────────────────────────
def test_abbreviated_sockets_inherit_the_prefix_and_wildcards_expand():
    assert parse_socket_list("LGA1851/1700/1200/115x, AM5/AM4") == ["LGA1851", "LGA1700", "LGA1200", "LGA115.", "AM5", "AM4"]
    assert parse_socket_list("LGA1851/1700,AM5/AM4") == ["LGA1851", "LGA1700", "AM5", "AM4"]      # 쉼표 뒤 공백 없음
    assert parse_socket_list(["LGA1700", "AM5/AM4"]) == ["LGA1700", "AM5", "AM4"]                # 리스트도 받는다


@pytest.mark.parametrize("cpu, listed, expected", [
    ("LGA1700", "LGA1851/1700/1200/115x, AM5/AM4", True),    # 이게 오판되던 것
    ("LGA1851", "LGA1851/1700", True),
    ("LGA1151", "LGA1700/1200/115x, AM5/AM4", True),         # 115x = 1150·1151·1155·1156
    ("LGA1700", "AM5/AM4", False),
    ("AM5", "LGA1700/1200/115x, AM5/AM4", True),
    ("AM4", "AM5", False),                                    # AM4 는 AM5 가 아니다(접두 일치 오판 방지)
    ("LGA 1700", "LGA-1700", True),                           # 공백·하이픈 무시
    ("LGA1700", "", None), (None, "AM5", None), ("LGA1700", None, None),
])
def test_socket_supported(cpu, listed, expected):
    assert socket_supported(cpu, listed) is expected


# ── CPU 계열 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, family", [
    ("AMD Ryzen 7 7800X3D", "ryzen:7000"), ("AMD Ryzen 9 9950X3D2", "ryzen:9000"), ("AMD Ryzen 5 3600", "ryzen:3000"),
    ("Ryzen 5 1600", "ryzen:1000"), ("AMD Ryzen 5 8600G", "ryzen:8000G"), ("Ryzen 5 4600G", "ryzen:4000G"),
    ("Ryzen 5 5600G", "ryzen:5000"),                                   # 5000 번대의 G 는 별도 계열이 아니다
    ("Intel Core i5-14600K", "core:14"), ("i7-9700K", "core:9"), ("Intel Core i3-12100F", "core:12"),
    ("Intel Core Ultra 7 265K", "ultra:200S"), ("Intel Core Ultra 5 250K Plus", "ultra:PLUS"),
    ("Pentium G4560", None), ("옛날 CPU", None), ("", None), (None, None),
])
def test_cpu_family_from_name(name, family):
    assert cpu_family(name) == family


def test_board_family_lists():
    assert supported_families("Ryzen 7000 / 8000G / 9000 계열") == {"ryzen:7000", "ryzen:8000G", "ryzen:9000"}
    assert supported_families("Ryzen 3000 / 4000G / 5000 계열") == {"ryzen:3000", "ryzen:4000G", "ryzen:5000"}
    assert supported_families("Intel Core 12 / 13 / 14세대") == {"core:12", "core:13", "core:14"}
    assert supported_families("Intel Core Ultra 200S / Plus 계열") == {"ultra:200S", "ultra:PLUS"}
    assert supported_families("") == supported_families(None) == set()


def test_cpu_supported_is_three_valued():
    am4 = "Ryzen 3000 / 4000G / 5000 계열"
    assert cpu_supported("AMD Ryzen 7 5800X3D", am4) is True
    assert cpu_supported("AMD Ryzen 5 2600", am4) is False           # 2000 번대는 이 보드의 지원 목록에 없다
    assert cpu_supported("알 수 없는 CPU", am4) is None              # 모르면 단정하지 않는다
    assert cpu_supported("AMD Ryzen 7 5800X3D", None) is None


def test_every_catalog_cpu_family_is_read_and_listed_by_its_boards():
    """실제 카탈로그의 CPU 이름 형식을 전부 읽고, 같은 소켓 보드의 지원 목록과 맞는다(오판 0)."""

    import psycopg
    from src.config import DATABASE_URL
    try:
        conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다")
    with conn:
        if not conn.execute("SELECT to_regclass('catalog.cpu_spec') IS NOT NULL").fetchone()[0]:
            pytest.skip("카탈로그가 없습니다")
        cpus = conn.execute("SELECT p.name, s.socket FROM catalog.product p JOIN catalog.cpu_spec s ON s.product_id=p.id").fetchall()
        boards = conn.execute("SELECT s.socket, s.supported_cpu_family FROM catalog.mainboard_spec s").fetchall()
    if not cpus or not boards:
        pytest.skip("PC 카탈로그가 seed 되지 않았습니다")
    assert [n for n, _ in cpus if cpu_family(n) is None] == [], "이름에서 계열을 못 읽는 CPU"
    for name, socket in cpus:
        for b_socket, listed in boards:
            if b_socket == socket:
                assert cpu_supported(name, listed) is True, (name, listed)


# ── 엔진 연결 ────────────────────────────────────────────────────────────────
def _cand(slot, name, **specs):
    return Candidate(slot=slot, product_key=name, name=name, price=1, specs=specs)


def _spec(**kw):
    return RequirementSpec(list_id="t", category="computer", mode=kw.pop("mode", "build"), **kw)


AM4_BOARD = _cand("메인보드", "B550", socket="AM4", mem_type="DDR4", supported_cpu_family="Ryzen 3000 / 4000G / 5000 계열")


def test_cooler_socket_no_longer_rejects_lga1700_for_abbreviated_lists():
    cpu = _cand("CPU", "Intel Core i5-14600K", socket="LGA1700")
    cooler = _cand("쿨러", "aio", supported_socket="LGA1851/1700/1200/115x, AM5/AM4")
    assert "cooler_socket" not in _pc_known_failures({"CPU": cpu, "쿨러": cooler}, _spec(), RULES)
    amd_only = _cand("쿨러", "am", supported_socket="AM5/AM4")
    assert "cooler_socket" in _pc_known_failures({"CPU": cpu, "쿨러": amd_only}, _spec(), RULES)


def test_bios_axis_is_ok_when_the_family_is_listed_and_approximate_when_unreadable():
    cpu = _cand("CPU", "AMD Ryzen 7 5800X3D", socket="AM4")
    assert pc_link_check({"CPU": cpu, "메인보드": AM4_BOARD}, _spec(), RULES)["bios"] == "ok"
    unknown = _cand("CPU", "미확인 CPU", socket="AM4")
    assert pc_link_check({"CPU": unknown, "메인보드": AM4_BOARD}, _spec(), RULES)["bios"] == "ok (근사)"
    no_list = _cand("메인보드", "old", socket="AM4", mem_type="DDR4")
    assert pc_link_check({"CPU": cpu, "메인보드": no_list}, _spec(), RULES)["bios"] == "ok (근사)"


def test_bios_axis_fails_for_an_unsupported_family_on_the_same_socket():
    old = _cand("CPU", "AMD Ryzen 5 2600", socket="AM4")                # AM4 이지만 2000 번대
    chosen = {"CPU": old, "메인보드": AM4_BOARD}
    assert "bios" in _pc_known_failures(chosen, _spec(), RULES)
    assert pc_link_check(chosen, _spec(), RULES)["bios"] == "fail"


def test_bios_uses_the_owned_cpu_name_in_upgrades():
    """업그레이드에서 CPU 를 그대로 쓰면 견적에는 메인보드만 들어간다 — 사용자가 적은 CPU 이름으로 판정한다."""
    spec = _spec(mode="upgrade", owned={"CPU": {"name": "Ryzen 5 2600", "specs": {"socket": "AM4"}, "source": "inferred"}})
    assert "bios" in _pc_known_failures({"메인보드": AM4_BOARD}, spec, RULES)
    fine = _spec(mode="upgrade", owned={"CPU": {"name": "Ryzen 5 5600", "specs": {"socket": "AM4"}, "source": "inferred"}})
    assert pc_link_check({"메인보드": AM4_BOARD}, fine, RULES)["bios"] == "ok"


def test_socket_mismatch_is_not_double_counted_as_a_bios_problem():
    cpu = _cand("CPU", "AMD Ryzen 7 7800X3D", socket="AM5")
    lga_board = _cand("메인보드", "B760", socket="LGA1700", mem_type="DDR5", supported_cpu_family="Intel Core 12 / 13 / 14세대")
    chosen = {"CPU": cpu, "메인보드": lga_board}
    failures = _pc_known_failures(chosen, _spec(), RULES)
    assert "socket" in failures and "bios" not in failures
    check = pc_link_check(chosen, _spec(), RULES)
    assert check["socket"] == "fail" and "bios" not in check


# ── 파워 폼팩터 · GPU 전원 커넥터 ─────────────────────────────────────────────────
from src.engine.compat_parse import gpu_connector_fit, parse_psu_forms, psu_fits_case  # noqa: E402
from src.engine.stage4_optimize import pc_compat_details  # noqa: E402


def test_psu_forms_are_parsed_from_the_catalog_notation():
    assert parse_psu_forms("SFX / SFX-L") == ("SFX", "SFX-L")
    assert parse_psu_forms("ATX / SFX-L 확인") == ("ATX", "SFX-L")
    assert parse_psu_forms("sfx l") == ("SFX-L",)
    assert parse_psu_forms("") == parse_psu_forms(None) == ()


@pytest.mark.parametrize("psu, case, expected", [
    ("ATX", "ATX", "ok"), ("SFX-L", "SFX / SFX-L", "ok"),
    ("ATX", "SFX / SFX-L", "fail"),          # 이게 통과되던 것 — ATX 파워는 SFX 전용 케이스에 안 들어간다
    ("SFX-L", "ATX", "adapter"), ("SFX", "SFX-L", "adapter"),
    ("ATX", "", None), (None, "ATX", None), ("ATX / SFX", "ATX", None),   # 파워 표기가 하나로 정해지지 않으면 모름
])
def test_psu_fits_case(psu, case, expected):
    assert psu_fits_case(psu, case) == expected


@pytest.mark.parametrize("gpu, aux, psu, expected", [
    ("2× 8-pin", "O", "PCIe 8-pin", "ok"),
    ("1× 16-pin (12VHPWR)", "O", "PCIe 8-pin", "adapter"),             # 16핀 GPU + 8핀 파워 → 동봉 어댑터
    ("1× 16-pin (12V-2x6)", "O", "12V-2x6 / 16-pin", "ok"),
    ("1× 16-pin (12V-2x6)", "O", "Side Connectors, 12V-2x6", "ok"),
    ("1× 8-pin", "O", "12V-2x6 / 16-pin 포함", "ok"),                   # 16핀 파워도 8핀을 함께 제공한다고 본다
    ("슬롯 전력", "X", "PCIe 8-pin", "ok"), ("1× 8-pin", "X", "", "ok"),   # 보조 전원이 필요 없다
    ("2× 8-pin", "O", "", None), ("", "O", "PCIe 8-pin", None), (None, None, None, None),
])
def test_gpu_connector_fit(gpu, aux, psu, expected):
    assert gpu_connector_fit(gpu, aux, psu) == expected


ATX_PSU = _cand("파워", "atx-psu", wattage_w=850, form_factor="ATX", gpu_power_connector="PCIe 8-pin")
SFX_CASE = _cand("케이스", "sff", psu_form_factor="SFX / SFX-L", max_gpu_len_mm=330)
ATX_CASE = _cand("케이스", "tower", psu_form_factor="ATX", max_gpu_len_mm=400)


def test_atx_psu_in_an_sfx_only_case_is_a_confirmed_incompatibility():
    assert "psu_form" in _pc_known_failures({"파워": ATX_PSU, "케이스": SFX_CASE}, _spec(), RULES)
    assert "psu_form" not in _pc_known_failures({"파워": ATX_PSU, "케이스": ATX_CASE}, _spec(), RULES)
    assert pc_link_check({"파워": ATX_PSU, "케이스": SFX_CASE}, _spec(), RULES)["psu_form"] == "fail"


def test_details_report_each_check_with_the_values_compared():
    gpu = _cand("GPU", "RTX", length_mm=300, power_w=285, power_connector="1× 16-pin (12VHPWR)", aux_power="O")
    rows = {r["axis"]: r for r in pc_compat_details({"GPU": gpu, "파워": ATX_PSU, "케이스": ATX_CASE}, _spec(), RULES)}
    assert rows["gpu_len"]["state"] == "ok" and "300mm ≤ 케이스 허용 400mm" in rows["gpu_len"]["detail"]
    assert rows["psu_form"]["state"] == "ok" and "ATX" in rows["psu_form"]["detail"]
    # 16핀 GPU + 8핀 파워는 실패가 아니라 "어댑터 필요" — 확인 필요(unknown)로 보이고 이유를 말한다
    assert rows["gpu_connector"]["state"] == "unknown" and "어댑터" in rows["gpu_connector"]["detail"]
    assert rows["power"]["state"] == "unknown" and "CPU 전력" in rows["power"]["detail"]
    assert all(r["label"] and r["detail"] for r in rows.values())


def test_checks_for_parts_that_are_not_in_the_quote_are_skipped():
    """GPU 만 바꾸는 업그레이드: 견적에 없는 CPU·보드·쿨러 사이의 검사(소켓·BIOS·쿨러 …)는 묻지 않는다."""
    gpu = _cand("GPU", "RTX", length_mm=300, power_w=285)
    spec = _spec(mode="upgrade")
    rows = {r["axis"]: r["state"] for r in pc_compat_details({"GPU": gpu}, spec, RULES)}
    assert rows["socket"] == rows["bios"] == rows["cooler_height"] == rows["memory"] == rows["psu_form"] == "skipped"
    assert rows["gpu_len"] == "unknown"            # 케이스 정보가 없다 — 바뀌는 GPU 와 관련된 검사라 남는다
    link = pc_link_check({"GPU": gpu}, spec, RULES)
    assert "socket" not in link and "bios" not in link and link["gpu_len"] == "ok (근사)"


def test_aio_cooler_height_is_explained_not_just_missing():
    cooler = _cand("쿨러", "aio", cooling_type="Liquid (AIO)", supported_socket="AM5")
    rows = {r["axis"]: r for r in pc_compat_details({"쿨러": cooler, "케이스": ATX_CASE}, _spec(), RULES)}
    assert rows["cooler_height"]["state"] == "unknown" and "라디에이터" in rows["cooler_height"]["detail"]
