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


def test_only_a_confirmed_same_product_is_compared_not_the_nearest_one():
    """"5800X3D"처럼 짧게 적어 '가장 비슷한 제품'으로만 잡힌 부품은 같은 제품이 확인되지 않아 가격을 비교하지 않는다."""
    rows = rows_by_part({"CPU": "5800X3D 290,000원"})
    assert rows["CPU"]["state"] == "no_catalog" and "확인되지 않아" in rows["CPU"]["detail"]


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
        created = client.post("/pc/reviews", json={"current_specs": {"CPU": "i5-14400F 250,000원"}}).json()
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
