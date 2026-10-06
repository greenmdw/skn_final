"""받은 견적 점검 초안의 항목(item) 규칙 — 견적 한 줄을 이름·상품코드·수량·가격으로 가르고, 같은 제품만 합친다.

DB·LLM 없이 도는 순수 함수다. 줄을 읽는 규칙은 기존 `quote_price`(가격·수량)를 그대로 쓰고 표기 규칙을 새로 만들지 않는다.
이름에는 상품코드와 가격을 넣지 않는다(요청서 BE-03). 가격이 적혀 있는데 수량이 2개 이상이면 그 금액을 품목 합계로
본다 — 가격 비교(`quote_review_service._price_row`)가 이미 같은 가정으로 카탈로그 가격에 수량을 곱해 견주기 때문이다."""
from __future__ import annotations

import re
from typing import Any

from src.engine.quote_price import line_quantity, parse_price, strip_price

# 쇼핑몰 상품코드(다나와 pcode 등) — 6~10자리 숫자. 가격은 먼저 걷어 낸 뒤라 가격 숫자와 겹치지 않는다.
_PRODUCT_CODE = re.compile(r"(?<![\d,.])(\d{6,10})(?![\d,.])")
_DOLLAR_PRICE = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?")      # "$368.99" — 원 가격이 아니라 읽지 않고, 이름에도 남기지 않는다
_COUNT_TOKEN = re.compile(r"(?<![\d.])\d{1,2}\s*(?:개|ea\b)|수량\s*:?\s*\d{1,2}", re.IGNORECASE)


def split_line(raw_text: str) -> dict[str, Any]:
    """견적 한 줄 → {normalized_name, product_code, quantity, quote_unit_price, quote_line_total, quote_price_type}."""
    raw = str(raw_text or "").strip()
    line_total = parse_price(raw)
    body = _DOLLAR_PRICE.sub(" ", strip_price(raw))
    code_match = _PRODUCT_CODE.search(body)
    code = code_match.group(1) if code_match else None
    quantity = line_quantity(raw)
    if code_match:
        tail = re.fullmatch(r"\s*(\d{1,2})\s*", body[code_match.end():])
        if tail and quantity == 1:
            # 쇼핑몰 표는 "제품명 -상품코드 | 판매가 | 수량 | 합계" 순이라 코드 뒤에 수량 열의 숫자가 이름 끝에 남는다 — 수량이다
            quantity = max(1, min(int(tail.group(1)), 20))
            body = body[:code_match.start()]
        else:
            body = body[:code_match.start()] + " " + body[code_match.end():]
    body = _COUNT_TOKEN.sub(" ", body)              # "2개"·"수량 2"는 수량 필드로 — 이름에서 뺀다("16GB x2"는 구성이라 둔다)
    name = re.sub(r"\s{2,}", " ", body).strip(" \t-–—:/|,·")
    return {
        "normalized_name": name, "product_code": code, "quantity": quantity,
        "quote_unit_price": round(line_total / quantity) if line_total else None,
        "quote_line_total": line_total,
        "quote_price_type": "unknown" if line_total is None else "unit" if quantity == 1 else "line_total",
    }


def spec_text(item: dict[str, Any]) -> str:
    """분석(점검)에 넘길 한 줄 — 수정된 이름·수량·품목 합계로 다시 만든다. 점검은 이 글에서 수량·가격을 읽는다."""
    name = str(item.get("normalized_name") or "").strip()
    quantity = int(item.get("quantity") or 1)
    parts = [name]
    if quantity > 1 and line_quantity(name) != quantity:
        parts.append(f"{quantity}개")
    total = item.get("quote_line_total")
    if total:
        parts.append(f"{int(total):,}원")
    return " ".join(p for p in parts if p)


def merge_same_products(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 카탈로그 제품으로 **확정된**(confirmed) 항목만 합친다 — 출처만 모으고 수량·가격은 먼저 온 것을 쓴다(같은
    견적이 두 장에 겹쳐 찍힌 경우 수량이 두 배가 되면 안 된다). 같은 부품군의 다른 모델·확정 안 된 항목은 모두 그대로 둔다."""
    out: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        product_id = item.get("matched_product_id")
        if item.get("match_status") == "confirmed" and product_id:
            key = (item["category"], product_id)
            if key in seen:
                kept = seen[key]
                kept["source_ids"] = sorted(set(kept["source_ids"]) | set(item["source_ids"]))
                continue
            seen[key] = item
        out.append(item)
    return out


def default_selection(items: list[dict[str, Any]]) -> dict[str, str]:
    """부품군마다 분석 기준 제품 1개 — 사용자가 고르기 전 기본값은 그 부품군의 첫 항목(읽힌 순서)."""
    chosen: dict[str, str] = {}
    for item in items:
        chosen.setdefault(item["category"], item["id"])
    return chosen
