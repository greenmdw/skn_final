"""실시간 검색 값 표시·이름 정리·비부품 줄 제외 (2026-10-07).

- 쇼핑몰의 "[DDR5 32G] … x 2EA 듀얼채널" 표기가 이름 확인 가드(모델 번호)에 걸려 항상 "못 찾음"이 되던 문제.
- "별도구매"·"CPU 기본 쿨러 장착 (추가선택가능)" 같은 선택 안내 줄이 부품으로 읽혀 검색까지 돌던 문제.
- 검색한 값을 쓴 항목이 화면에서 구분되지 않던 문제(부품 표 value_source, 초안 항목 live_value).
"""
from __future__ import annotations

import os

import pytest

from src.engine.quote_items import is_placeholder_line
from src.services import live_spec_lookup as lsl

APACER = "[DDR5 32G] Apacer DDR5-5600 CL46 (16GB) x 듀얼채널"


# ── 이름 정리와 가드 (DB 없음) ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    APACER,
    "[DDR5 32G] Apacer DDR5-5600 CL46 (16GB) x 2EA 듀얼채널",
    "[DDR5 32G] Apacer DDR5-5600 CL46 (16GB) x 듀얼채널 2개 119,000원",
    "Apacer DDR5-5600 CL46 (16GB)",
])
def test_bundle_label_channel_and_quantity_are_not_part_of_the_name(raw):
    assert lsl.normalize_lookup_key(raw) == "apacer ddr5 5600 cl46 16gb"


def test_the_shop_capacity_label_is_not_an_identity_token_so_the_guard_passes():
    snippet = "Apacer DDR5-5600 U-DIMM 16GB CL46-45-45. Kit 2 x 16GB = 32GB dual channel."
    assert lsl._identity_tokens(APACER) == {"5600", "cl46"}
    assert lsl.snippet_mentions_the_product(APACER, snippet) is True


def test_capacity_shorthand_is_skipped_but_four_digit_models_with_g_are_kept():
    # 32G·8G 는 용량 표기라 모델 번호가 아니다. 5600G(APU)는 모델이라 가드에 남는다 — 5600 과 섞이면 안 된다.
    assert lsl._identity_tokens("Corsair Vengeance 32G 6000") == {"6000"}
    assert "5600g" in lsl._identity_tokens("AMD Ryzen 5 5600G")


def test_the_guard_still_rejects_a_snippet_without_the_real_model_number():
    assert lsl.snippet_mentions_the_product(APACER, "Samsung DRAM DDR5 overview") is False


def test_model_names_that_look_like_quantities_are_not_cut():
    assert "x3d" in lsl.normalize_lookup_key("라이젠7 5800X3D 2개")
    assert lsl.normalize_lookup_key("MSI MAG B650 TOMAHAWK WIFI") == "msi mag b650 tomahawk wifi"


# ── 비부품 줄 ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "별도구매 (추가선택가능)",
    "CPU 기본 쿨러 장착 (추가선택가능)",
    "선택안함",
    "추가선택가능",
])
def test_selection_placeholders_are_not_parts(text):
    assert is_placeholder_line(text) is True


@pytest.mark.parametrize("text", [
    "AMD 라이젠5-5세대 7500F (라파엘) (멀티팩 정품)",
    "Thermalright Assassin X 120 (추가선택가능 팬 2개)",       # 모델·숫자가 있으면 제품의 옵션 안내로 본다
    "ASUS PRIME A620AM-K 대원씨티에스",
    "",
])
def test_real_products_are_not_placeholders(text):
    assert is_placeholder_line(text) is False


# ── DB 필요: 초안·분석 ─────────────────────────────────────────────────────────────────────
DSN = os.getenv("DATABASE_URL")
db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.db import get_conn
    from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo

TEXT = (
    "CPU: AMD Ryzen 5 7500F\n"
    "쿨러: CPU 기본 쿨러 장착 (추가선택가능)\n"
    "메인보드: MSI B650 TOMAHAWK\n"
    "메모리: " + APACER + "\n"
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: False)
    ratelimit.reset_all()
    with TestClient(app) as c:
        yield c
    ratelimit.reset_all()


def _seed(name: str, fields: dict, *, relevant: bool = True) -> None:
    with get_conn() as conn:
        LiveSpecLookupRepo(conn).upsert(
            lookup_key=lsl.normalize_lookup_key(name), query_text=name, brand=None, model=None, relevant=relevant,
            supported_fields=fields, source_url="https://example.com/seed")


@db
def test_draft_drops_selection_placeholder_lines(client):
    r = client.post("/pc/review-drafts", data={"text": TEXT})
    assert r.status_code == 201, r.text
    items = r.json()["items"]
    assert "쿨러" not in {i["category"] for i in items}
    assert not any("기본 쿨러" in i["normalized_name"] for i in items)
    assert {i["category"] for i in items} >= {"CPU", "메인보드"}


@db
def test_owned_parts_preview_drops_selection_placeholder_lines(client):
    r = client.post("/pc/owned-parts/preview", json={"text": TEXT})
    assert r.status_code == 200, r.text
    assert "쿨러" not in {row["part"] for row in r.json()["rows"]}


@db
def test_draft_items_mark_a_stored_live_value_and_nothing_else(client):
    name = "Obscure Brand Tower Cooler OBX-9000"
    first = client.post("/pc/review-drafts", data={"text": f"쿨러: {name}\nCPU: AMD Ryzen 5 7500F"})
    assert first.status_code == 201, first.text
    assert not any(i["live_value"] for i in first.json()["items"])          # 검색 전에는 표시가 없다

    _seed(name, {"cooling_type": "공랭", "height_mm": 155})
    again = client.post("/pc/review-drafts", data={"text": f"쿨러: {name}\nCPU: AMD Ryzen 5 7500F"})
    marked = {i["category"]: i["live_value"] for i in again.json()["items"]}
    assert marked["쿨러"] is True
    assert marked["CPU"] is False                                           # 저장소에 없는 다른 항목은 그대로

    got = client.get(f"/pc/review-drafts/{again.json()['draft_id']}")
    assert {i["category"]: i["live_value"] for i in got.json()["items"]}["쿨러"] is True


@db
def test_a_not_found_row_is_not_marked_as_a_live_value(client):
    name = "Phantom Cooler ZZ-12345"
    _seed(name, {}, relevant=False)
    r = client.post("/pc/review-drafts", data={"text": f"쿨러: {name}"})
    assert [i["live_value"] for i in r.json()["items"]] == [False]


@db
def test_analysis_part_row_says_the_value_came_from_a_live_search(client):
    name = "Obscure Brand Board OB-B999"
    _seed(name, {"socket": "AM5", "mem_type": "DDR5", "form_factor": "ATX"})
    draft = client.post("/pc/review-drafts", data={"text": f"메인보드: {name}\nCPU: AMD Ryzen 5 7500F"}).json()
    analysis = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={})
    assert analysis.status_code == 200, analysis.text
    row = next(p for p in analysis.json()["parts"] if p["part"] == "메인보드")
    assert row["value_source"] == "live"
    assert row["state"] == "warn" and row["match_status"] in ("inferred", "unmatched")     # 검색 값은 제품 확정이 아니다
    assert "실시간 검색" in row["matched_note"]
    cpu = next(p for p in analysis.json()["parts"] if p["part"] == "CPU")
    assert cpu["value_source"] is None


# ── RAM: 검색 값은 낱개 기준, 개수는 견적 수량 ────────────────────────────────────────────────
from src.engine.owned_parts import _ram_specs, merge_live_lookup  # noqa: E402


@pytest.mark.parametrize("configured,capacity,expected", [
    ("단품", 16, (16, "16GB × 1")),
    ("Single module", 16, (16, "16GB × 1")),
    ("2 x 16GB kit", 16, (32, "16GB × 2")),
    ("16GB x 2", None, (32, "16GB × 2")),
    ("듀얼 채널 킷", 32, (32, None)),            # 읽을 수 없는 문장은 구성만 버린다 — 용량은 그대로
    ("단품", None, (None, None)),                 # 용량을 모르면 낱개 표기를 만들 수 없다
])
def test_live_ram_module_config_becomes_the_catalog_notation(configured, capacity, expected):
    assert lsl._ram_module_config(capacity, configured) == expected


def test_normalize_fields_rewrites_ram_config_and_leaves_the_psu_module_config_alone():
    out = lsl.normalize_fields("RAM", {"capacity_gb": 16, "module_config": "단품", "mem_type": "DDR5"})
    assert out["module_config"] == "16GB × 1" and out["capacity_gb"] == 16
    assert lsl.normalize_fields("파워", {"module_config": "풀모듈러"})["module_config"] == "풀모듈러"


def test_text_ram_total_is_each_times_quantity_and_ignores_the_shop_bundle_label():
    out = _ram_specs("[DDR5 32G] Apacer DDR5-5600 CL46 (16GB) x 듀얼채널 2개")
    assert out["capacity_gb"] == 32 and out["module_config"] == "16GB × 2" and out["speed_mts"] == 5600
    # 수량이 1이면 낱개 그대로(예전 동작)
    one = _ram_specs("Apacer DDR5-5600 CL46 (16GB)")
    assert one["capacity_gb"] == 16 and "module_config" not in one


def _owned(slot, source, specs=None):
    return {slot: {"name": "x", "specs": dict(specs or {}), "source": source}}


def test_live_ram_uses_the_quote_quantity_for_the_total_and_keeps_one_per_unit():
    cached = {"RAM": {"relevant": True, "source_url": "u",
                      "supported_fields": {"mem_type": "DDR5", "speed_mts": 5600, "capacity_gb": 16, "module_config": "16GB × 1"}}}
    for quantity, total in ((1, 16), (2, 32), (4, 64)):
        owned = _owned("RAM", "unverified")
        merge_live_lookup(owned, {"RAM": f"Obscure DDR5-5600 16GB {quantity}개"}, cached)
        specs = owned["RAM"]["specs"]
        assert owned["RAM"]["source"] == "live"
        assert (specs["capacity_gb"], specs["module_config"]) == (total, f"16GB × {quantity}")


def test_live_ram_fill_does_not_override_what_the_quote_text_already_says():
    cached = {"RAM": {"relevant": True, "source_url": "u",
                      "supported_fields": {"capacity_gb": 16, "module_config": "16GB × 1", "speed_mts": 6000}}}
    owned = _owned("RAM", "text", {"capacity_gb": 32, "module_config": "16GB × 2"})
    merge_live_lookup(owned, {"RAM": "Obscure 16GB x2"}, cached)
    specs = owned["RAM"]["specs"]
    assert (specs["capacity_gb"], specs["module_config"]) == (32, "16GB × 2")     # 글에 적힌 값 유지
    assert specs["speed_mts"] == 6000 and owned["RAM"]["live_filled"] == ["speed_mts"]


@pytest.mark.parametrize("raw", [
    "메모리: " + APACER,
    "RAM: " + APACER,
    "메모리：" + APACER,            # 전각 콜론
    APACER,
])
def test_a_leading_part_label_does_not_change_the_lookup_key(raw):
    assert lsl.normalize_lookup_key(raw) == "apacer ddr5 5600 cl46 16gb"


def test_a_colon_inside_a_product_name_is_not_treated_as_a_label():
    assert lsl.normalize_lookup_key("Corsair K70: RGB TKL") == "corsair k70 rgb tkl"
