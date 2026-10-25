"""견적 가격 읽기와 카탈로그 가격 비교 (CHK-05).

가격 읽기·비교는 순수 함수, 부품별 비교 행은 명시한 카탈로그로, 저장·조회는 HTTP(일회용 DB)로 본다.
원칙: 견적에 가격이 없으면 비교하지 않고(P10), 같은 제품으로 확정된 부품만 비교한다.
"""
from __future__ import annotations

import os

import pytest

from src.dto import Candidate
from src.engine.quote_price import compare_price, parse_price, strip_price
from src.services import quote_review_service as qrs

# ── 가격 읽기 ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,price", [
    ("RTX 4060 Ti 520,000원", 520_000),
    ("라이젠 7 7800X3D ₩389,000", 389_000),
    ("i5-14400F 250000원", 250_000),
    ("Ryzen 5 7600 25만원", 250_000),
    ("Ryzen 5 7600 25만 5천원", 255_000),
    ("Ryzen 5 7600 25.5만원", 255_000),
    ("삼성전자 990 PRO 1TB 189,000", 189_000),          # 원 없이 천 단위 쉼표만
    ("정가 300,000원 → 250,000원", 250_000),              # 여러 금액이면 마지막(할인가)
    ("케이스 5천원", 5_000),
])
def test_prices_written_in_common_korean_formats_are_read(text, price):
    assert parse_price(text) == price


@pytest.mark.parametrize("text", [
    "RTX 4060 Ti",
    "i5-14400F",                    # 모델 번호는 가격이 아니다
    "삼성전자 DDR5-5600 16GB",
    "Micronics Classic II 700W",
    "1,000W 풀모듈러 파워",           # 쉼표가 있어도 단위가 붙으면 가격이 아니다
    "980 PRO 1TB",
    "",
    None,
])
def test_text_without_a_price_gives_none(text):
    assert parse_price(text) is None


def test_implausible_amounts_are_not_prices():
    assert parse_price("무료 0원") is None
    assert parse_price("9,999,999,999원") is None


def test_stripping_the_price_leaves_the_part_text_clean():
    assert strip_price("RTX 4060 Ti 520,000원") == "RTX 4060 Ti"
    assert strip_price("Ryzen 5 7600 25만 5천원") == "Ryzen 5 7600"
    assert strip_price("₩389,000 라이젠 7 7800X3D") == "라이젠 7 7800X3D"
    assert strip_price("i5-14400F") == "i5-14400F"


# ── 비교 ────────────────────────────────────────────────────────────────────────────


def test_compare_marks_pricier_cheaper_and_similar_with_the_difference():
    assert compare_price(260_000, 239_000) == {"state": "pricier", "diff": 21_000, "diff_pct": 8.8}
    assert compare_price(200_000, 239_000) == {"state": "cheaper", "diff": -39_000, "diff_pct": -16.3}
    assert compare_price(242_000, 239_000)["state"] == "similar"          # ±5% 안
    assert compare_price(239_000, 239_000) == {"state": "similar", "diff": 0, "diff_pct": 0.0}


def test_compare_does_nothing_without_both_prices():
    assert compare_price(None, 239_000)["state"] == "no_quote_price"
    assert compare_price(250_000, None)["state"] == "no_catalog"
    assert compare_price(250_000, 0)["state"] == "no_catalog"


# ── 견적 분석에 이어진다 ─────────────────────────────────────────────────────────────

POOL = {
    "CPU": [Candidate(product_key="c1", slot="CPU", name="AMD Ryzen 7 7800X3D", price=390_000, specs={"socket": "AM5"}),
            Candidate(product_key="c2", slot="CPU", name="AMD Ryzen 7 5800X3D", price=300_000, specs={"socket": "AM4"})],
    "GPU": [Candidate(product_key="g1", slot="GPU", name="NVIDIA GeForce RTX 4060 Ti", price=500_000)],
    "RAM": [Candidate(product_key="r1", slot="RAM", name="삼성전자 DDR5-5600 (16GB)", price=60_000, specs={"mem_type": "DDR5"}),
            Candidate(product_key="r2", slot="RAM", name="삼성전자 DDR5-5600 (32GB)", price=110_000, specs={"mem_type": "DDR5"})],
}


def rows_by_part(quote: dict) -> dict[str, dict]:
    review = qrs.analyze(quote, by_slot=POOL)
    return {r["part"]: r for r in review["prices"]["rows"]}


def test_prices_are_compared_per_part_against_the_catalog():
    rows = rows_by_part({"CPU": "라이젠 7 7800X3D 389,000원", "GPU": "지포스 RTX 4060 Ti 8GB 560,000원"})
    assert rows["CPU"]["state"] == "similar" and rows["CPU"]["catalog"] == 390_000 and rows["CPU"]["diff"] == -1_000
    assert rows["GPU"]["state"] == "pricier" and rows["GPU"]["diff"] == 60_000
    assert "560,000원" in rows["GPU"]["detail"] and "500,000원" in rows["GPU"]["detail"] and "+12.0%" in rows["GPU"]["detail"]


def test_a_quote_without_any_price_is_not_compared():
    """P10 — 견적에 가격이 없으면 비교하지 않는다."""
    prices = qrs.analyze({"CPU": "라이젠 7 7800X3D", "GPU": "RTX 4060 Ti"}, by_slot=POOL)["prices"]
    assert prices["available"] is False and prices["rows"] == [] and "가격이 적혀 있지 않아" in prices["reason"]


def test_a_part_without_a_price_is_listed_but_not_compared():
    rows = rows_by_part({"CPU": "라이젠 7 7800X3D 389,000원", "GPU": "RTX 4060 Ti"})
    assert rows["GPU"]["state"] == "no_quote_price" and rows["GPU"]["quoted"] is None


def test_a_part_the_catalog_does_not_have_is_not_compared():
    rows = rows_by_part({"CPU": "라이젠 5 7500F 200,000원"})
    assert rows["CPU"]["state"] == "no_catalog" and rows["CPU"]["catalog"] is None and "찾지 못해" in rows["CPU"]["detail"]


def test_a_shortened_name_confirmed_by_its_model_number_is_compared_and_a_wrong_model_is_not():
    """"5800X3D"처럼 제조사·시리즈를 줄여 써도 모델 번호가 카탈로그에서 유일하면 같은 제품으로 확정해 가격을 비교한다.
    모델이 다르면("5800") 확정하지 않아 비교하지 않는다."""
    rows = rows_by_part({"CPU": "5800X3D 290,000원"})
    assert rows["CPU"]["state"] != "no_catalog" and rows["CPU"]["catalog"] is not None
    rows = rows_by_part({"CPU": "5800 290,000원"})
    assert rows["CPU"]["state"] == "no_catalog"


def test_the_capacity_written_in_the_text_picks_the_catalog_price():
    rows = rows_by_part({"RAM": "삼성전자 DDR5-5600 32GB 120,000원"})
    assert rows["RAM"]["catalog"] == 110_000 and rows["RAM"]["state"] == "pricier"


def test_the_summary_totals_only_the_parts_that_were_compared_on_both_sides():
    prices = qrs.analyze({"CPU": "라이젠 7 7800X3D 389,000원", "GPU": "RTX 4060 Ti 560,000원", "RAM": "DDR5 32GB 100,000원"},
                         by_slot=POOL)["prices"]
    s = prices["summary"]
    assert s["compared"] == 2 and s["not_compared"] == 1                       # RAM 은 카탈로그 대응 없음
    assert s["quoted_total"] == 389_000 + 560_000 and s["catalog_total"] == 390_000 + 500_000
    assert s["diff"] == 59_000 and s["diff_pct"] == 6.6
    assert s["quote_total_complete"] is True and (s["pricier"], s["similar"], s["cheaper"]) == (1, 1, 0)


def test_prices_do_not_disturb_matching_or_the_compatibility_check():
    """가격 표기가 붙어도 매칭·호환 검사는 가격이 없을 때와 같다."""
    with_price = qrs.analyze({"CPU": "라이젠 7 7800X3D 389,000원"}, by_slot=POOL)
    without = qrs.analyze({"CPU": "라이젠 7 7800X3D"}, by_slot=POOL)
    assert with_price["parts"][0]["matched"] == without["parts"][0]["matched"] == "AMD Ryzen 7 7800X3D"
    assert with_price["compat"] == without["compat"]


# ── 저장·조회 (HTTP, 일회용 DB) ──────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")


@pytest.mark.skipif(not DSN, reason="requires disposable test database")
def test_the_price_comparison_is_saved_with_the_review_and_read_back(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    with TestClient(app) as client:
        from tests.quote_review_helpers import create_review
        created = create_review(client, {"CPU": "i5-14400F 250,000원"})
        assert created["prices"]["available"] is True
        assert created["prices"]["rows"][0]["quoted"] == 250_000
        assert client.get(f"/pc/reviews/{created['list_id']}").json()["prices"] == created["prices"]


# ── 개수(한 줄에 여러 개) ────────────────────────────────────────────────────────────

def test_line_quantity_reads_kits_and_counts():
    from src.engine.quote_price import line_quantity
    assert line_quantity("삼성전자 DDR5-5600 16GB x2 120,000원") == 2
    assert line_quantity("DDR5 16Gx2") == 2
    assert line_quantity("램 16GB 2개 120,000원") == 2
    assert line_quantity("수량 3 SSD") == 3
    assert line_quantity("RTX 4060 Ti 560,000원") == 1
    assert line_quantity("DDR5-5600 16GB") == 1


def test_a_kit_written_as_two_sticks_is_compared_against_two_catalog_sticks():
    """"16GB x2 120,000원"을 낱개 카탈로그 가격 60,000원과 그대로 비교하면 +100% 로 잘못 나온다 — 2장분과 견준다."""
    rows = rows_by_part({"RAM": "삼성전자 DDR5-5600 (16GB) x2 120,000원"})
    assert rows["RAM"]["quantity"] == 2 and rows["RAM"]["catalog"] == 120_000 and rows["RAM"]["state"] == "similar"
    assert "2개 기준" in rows["RAM"]["detail"]


def test_a_single_stick_is_compared_as_it_is():
    rows = rows_by_part({"RAM": "삼성전자 DDR5-5600 16GB 62,000원"})
    assert rows["RAM"]["quantity"] == 1 and rows["RAM"]["catalog"] == 60_000 and "개 기준" not in rows["RAM"]["detail"]


def test_only_the_quote_total_is_reported_when_no_part_has_a_price():
    """부품별 가격이 없고 총액만 읽혔으면 부품별 비교는 하지 않고 총액과 카탈로그로 확인된 부품의 합계를 알린다."""
    prices = qrs.analyze({"CPU": "라이젠 7 7800X3D", "GPU": "RTX 4060 Ti", "RAM": "DDR5 32GB"}, by_slot=POOL, quote_total=1_000_000)["prices"]
    assert prices["available"] is False and prices["rows"] == []
    note = prices["quote_total"]
    assert note["quote_total"] == 1_000_000 and note["parts"] == 3 and note["catalog_parts"] == 2
    assert note["catalog_total"] == 390_000 + 500_000
    assert "견적 총액 1,000,000원" in prices["reason"] and "합계에 빠졌으니" in prices["reason"]


def test_without_a_quote_total_the_old_no_price_message_is_unchanged():
    prices = qrs.analyze({"CPU": "라이젠 7 7800X3D"}, by_slot=POOL)["prices"]
    assert "가격이 적혀 있지 않아" in prices["reason"] and "quote_total" not in prices


# ── "개당 N원"은 줄 합계가 아니다 (2026-10-25 시나리오 견적서) ──────────────────────────

@pytest.mark.parametrize("text, total", [
    ("삼성전자 DDR5-5600 (8GB) × 2 2 365,160원 개당 182,580원 × 2", 365_160),          # 합계 뒤에 개당 가격
    ("마이크론 Crucial DDR5-5600 CL46 (16GB) × 2 2 700,000원 개당 350,000원 × 2", 700_000),
    ("ESSENCORE KLEVV DDR4-3200 CL22 (8GB) × 2 2 185,000원 개당 92,500원 × 2", 185_000),
    ("삼성전자 DDR4-3200 (8GB) × 2 2 159,800원 개당 79,900원 × 2", 159_800),
    ("RAM 16GB 단가 79,900원 2개 159,800원", 159_800),                                   # 단가가 앞, 합계가 뒤
])
def test_a_per_unit_price_is_not_taken_as_the_line_total(text, total):
    assert parse_price(text) == total


def test_a_lone_per_unit_price_is_still_read_and_discount_order_is_unchanged():
    assert parse_price("개당 79,900원") == 79_900                 # 합계가 없으면 그 값(읽을 수 있는 유일한 금액)
    assert parse_price("정가 300,000원 → 250,000원") == 250_000      # 할인가가 뒤에 오는 관례는 그대로


def test_the_unit_price_is_derived_from_the_line_total_and_the_name_has_no_doubled_quantity():
    from src.engine.quote_items import split_line

    parts = split_line("삼성전자 DDR5-5600 (8GB) × 2 2 365,160원 개당 182,580원 × 2")
    assert parts["quote_line_total"] == 365_160 and parts["quantity"] == 2 and parts["quote_unit_price"] == 182_580
    assert parts["normalized_name"].count("× 2") == 1


def test_two_single_sticks_are_compared_against_two_times_the_catalog_price():
    """"(8GB) × 2 | 365,160원"은 낱개 8GB 두 장이다 — 카탈로그 낱개 가격(182,580원)의 2배와 견줘야 한다.
    견적 장수에 맞춰 키운 module_config("8GB × 2")로 나누면 이미 2장짜리 상품으로 보여 카탈로그 가격이 곱해지지 않았다(2026-10-25)."""
    from src.engine.owned_parts import resolve_owned_parts

    ram = Candidate(slot="RAM", product_key="ram:samsung:ddr5-5600-8", name="삼성전자 DDR5-5600 (8GB)", price=182_580,
                    specs={"mem_type": "DDR5", "capacity_gb": 8, "module_config": "8GB × 1", "speed_mts": 5600})
    text = "삼성전자 DDR5-5600 (8GB) × 2 365,160원"
    owned = resolve_owned_parts({"RAM": text}, {"RAM": [ram]}, ["RAM"])
    info = owned["RAM"]
    assert info["source"] == "catalog" and info["catalog_modules"] == 1
    row = qrs._price_row("RAM", text, info)
    assert row["quoted"] == 365_160 and row["catalog"] == 365_160 and row["state"] == "similar" and row["quantity"] == 2


def test_a_kit_product_in_the_catalog_is_not_multiplied_again():
    from src.engine.owned_parts import resolve_owned_parts

    kit = Candidate(slot="RAM", product_key="ram:kit", name="TEAMGROUP DDR5-6000 (16GB×2)", price=300_000,
                    specs={"mem_type": "DDR5", "capacity_gb": 32, "module_config": "16GB × 2", "speed_mts": 6000})
    text = "TEAMGROUP DDR5-6000 (16GB×2) 300,000원"
    info = resolve_owned_parts({"RAM": text}, {"RAM": [kit]}, ["RAM"])["RAM"]
    row = qrs._price_row("RAM", text, info)
    assert row["catalog"] == 300_000 and row["state"] == "similar"
