"""견적 한 줄 → 항목 규칙(src/engine/quote_items.py) — DB·LLM 없이 도는 순수 함수."""
from __future__ import annotations

from src.engine.quote_items import default_selection, merge_same_products, spec_text, split_line


def test_name_has_no_code_or_price():
    parts = split_line("인텔 코어 i5-14400F 19996987 238,000원")
    assert parts["normalized_name"] == "인텔 코어 i5-14400F"
    assert parts["product_code"] == "19996987"
    assert parts["quote_line_total"] == 238000 and parts["quote_unit_price"] == 238000
    assert parts["quantity"] == 1 and parts["quote_price_type"] == "unit"


def test_quantity_is_a_field_and_price_is_the_line_total():
    parts = split_line("삼성전자 DDR5-5600 16GB 2개 190,000원")
    assert parts["quantity"] == 2 and "2개" not in parts["normalized_name"]
    assert parts["quote_line_total"] == 190000 and parts["quote_unit_price"] == 95000
    assert parts["quote_price_type"] == "line_total"


def test_ram_kit_notation_stays_in_the_name_because_it_is_the_product_configuration():
    parts = split_line("Kingston FURY Beast DDR4 16GB x2 90,000원")
    assert "x2" in parts["normalized_name"] and parts["quantity"] == 2


def test_no_price_is_unknown_and_not_invented():
    parts = split_line("AMD Ryzen 5 7500F")
    assert parts["quote_line_total"] is None and parts["quote_unit_price"] is None
    assert parts["quote_price_type"] == "unknown"


def test_a_price_looking_number_that_is_a_model_number_is_not_a_price():
    parts = split_line("AMD Ryzen 5 5600")
    assert parts["quote_line_total"] is None and parts["normalized_name"] == "AMD Ryzen 5 5600"


def test_spec_text_rebuilds_name_quantity_and_total_for_the_review():
    text = spec_text({"normalized_name": "삼성전자 DDR5-5600 16GB", "quantity": 2, "quote_line_total": 190000})
    assert text == "삼성전자 DDR5-5600 16GB 2개 190,000원"
    assert spec_text({"normalized_name": "AMD Ryzen 5 7500F", "quantity": 1, "quote_line_total": None}) == "AMD Ryzen 5 7500F"


def _item(i, category, *, status="unmatched", product=None, sources=("source-1",)):
    return {"id": i, "category": category, "match_status": status, "matched_product_id": product, "source_ids": list(sources)}


def test_only_confirmed_same_products_are_merged_and_other_models_are_kept():
    items = [
        _item("a", "GPU", status="confirmed", product="p1", sources=("source-1",)),
        _item("b", "GPU", status="confirmed", product="p1", sources=("source-2",)),      # 같은 제품 — 합친다
        _item("c", "GPU", status="confirmed", product="p2"),                               # 같은 부품군의 다른 모델 — 남긴다
        _item("d", "CPU", status="unmatched"), _item("e", "CPU", status="unmatched"),    # 확정 안 된 것은 합치지 않는다
    ]
    merged = merge_same_products(items)
    assert [i["id"] for i in merged] == ["a", "c", "d", "e"]
    assert merged[0]["source_ids"] == ["source-1", "source-2"]


def test_default_selection_is_the_first_item_of_each_category():
    items = [_item("a", "GPU"), _item("b", "GPU"), _item("c", "CPU")]
    assert default_selection(items) == {"GPU": "a", "CPU": "c"}


def test_english_ea_counts_as_quantity_too():
    parts = split_line("Samsung DDR5-5600 16GB 2ea 190,000원")
    assert parts["quantity"] == 2 and parts["normalized_name"] == "Samsung DDR5-5600 16GB"
    assert parts["quote_price_type"] == "line_total" and parts["quote_unit_price"] == 95000


def test_dollar_prices_are_not_read_as_won():
    from src.engine.quote_price import parse_price

    assert parse_price("AMD Ryzen 7 7800X3D $368.99") is None
    assert parse_price("Asus PRIME OC Radeon RX 9070 XT $1,299.99") is None     # "$1,299.99"의 1,299 를 원 가격으로 읽으면 안 된다
    assert parse_price("RTX 5050 449,000원") == 449000


def test_spec_lines_keep_every_line_of_the_same_slot():
    from src.engine.spec_text import parse_spec_lines

    text = "CPU: 라이젠 5 7500F\nGPU: RTX 5060\nGPU: RX 9060 XT\n메인보드: B650M"
    assert parse_spec_lines(text) == [("CPU", "라이젠 5 7500F"), ("GPU", "RTX 5060"), ("GPU", "RX 9060 XT"), ("메인보드", "B650M")]


def test_dollar_price_is_removed_from_the_name_and_not_read_as_won():
    parts = split_line("AMD Ryzen 7 7800X3D 4.2 GHz 8-Core Processor $368.99")
    assert parts["normalized_name"] == "AMD Ryzen 7 7800X3D 4.2 GHz 8-Core Processor"
    assert parts["quote_line_total"] is None and parts["quote_price_type"] == "unknown"
    assert split_line("Asus PRIME OC Radeon RX 9070 XT $1,299.99")["normalized_name"] == "Asus PRIME OC Radeon RX 9070 XT"


def test_shop_table_row_trailing_quantity_column_is_a_quantity_not_part_of_the_name():
    """쇼핑몰 견적 표 캡처("제품명 -상품코드 | 판매가 | 수량 | 합계")에서 읽은 줄 — 이름 끝에 "- 1"이 남지 않는다."""
    one = split_line("[AMD] 라이젠5 라파엘 7500X3D (6코어/12스레드/4.0GHz/쿨러미포함) 멀티팩 -1313313 1 316,000원")
    assert one["normalized_name"] == "[AMD] 라이젠5 라파엘 7500X3D (6코어/12스레드/4.0GHz/쿨러미포함) 멀티팩"
    assert one["product_code"] == "1313313" and one["quantity"] == 1 and one["quote_line_total"] == 316000
    two = split_line("[삼성] DDR5 16GB -1292405 2 640,000원")
    assert two["quantity"] == 2 and two["normalized_name"] == "[삼성] DDR5 16GB"
    assert two["quote_price_type"] == "line_total" and two["quote_unit_price"] == 320000
    assert split_line("[ABKO] SETTLER 800W -1140804 1개 59,900원")["normalized_name"] == "[ABKO] SETTLER 800W"
