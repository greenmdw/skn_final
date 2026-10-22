"""RAM 2개 구성 변환 (정책 §2.5).

추천 후보는 모듈 2개 구성 전체를 한 후보로 본다. 2개 키트는 상품 1개(가격·용량 그대로),
낱개 단품은 상품 2개(가격·용량 2배)다. 키트에 2를 곱하지 않는다(가격·용량 중복 합산 금지).
다른 개수(1개·3개 이상)로 자동 전환하지 않는다.
"""
from __future__ import annotations

from typing import Any

from src.dto import Candidate
from src.engine.compat_parse import parse_module_count

PAIR = 2
_MISSING_MODULE = "PENDING_SPEC_MISSING:module_config"
_MISSING_CAPACITY = "PENDING_SPEC_MISSING:capacity_gb"


def _gb(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return value


def pair_qty(specs: dict[str, Any]) -> int | None:
    """2개 구성에 필요한 상품 개수 — 모듈 2개 키트 1, 단품 2. 읽을 수 없거나 3개 이상이면 None."""
    count = parse_module_count((specs or {}).get("module_config"))
    if count == PAIR:
        return 1
    if count == 1:
        return PAIR
    return None


def as_pair(cand: Candidate) -> tuple[Candidate | None, str | None]:
    """후보를 2개 구성으로 바꾼다 -> (사본, None) 또는 (None, 제외·보류 사유 코드).
    원본 specs·provenance는 변형하지 않는다. 이미 구성으로 바뀐 후보(unit_price 가 채워진 것)는 그대로 돌려준다
    — 단품을 바꾼 결과는 모듈 2개로 보이므로 다시 바꾸면 가격·용량이 중복 합산된다."""
    if cand.unit_price is not None:
        return cand, None
    count = parse_module_count(cand.specs.get("module_config"))
    if count is None or count < 1:
        return None, _MISSING_MODULE
    if count > PAIR:
        return None, f"EXCLUDED_RAM_NOT_PAIR:{count}"
    if count == PAIR:
        return cand.model_copy(update={"purchase_qty": 1, "unit_price": cand.price, "specs": dict(cand.specs),
                                       "provenance": dict(cand.provenance)}), None
    capacity = _number(cand.specs.get("capacity_gb"))
    if capacity is None:
        return None, _MISSING_CAPACITY
    specs = dict(cand.specs)
    specs["capacity_gb"] = capacity * PAIR
    specs["module_config"] = f"{_gb(capacity)}GB × {PAIR}"
    return cand.model_copy(update={
        "purchase_qty": PAIR, "unit_price": cand.price, "price": cand.price * PAIR, "specs": specs,
        "provenance": dict(cand.provenance), "flags": [*cand.flags, "ram_pair_from_single"],
    }), None


def pair_price(cand: Candidate) -> int | None:
    """2개 구성 가격 — 키트는 가격, 단품은 가격×2, 구성할 수 없으면 None."""
    qty = pair_qty(cand.specs)
    return cand.price * qty if qty is not None and cand.price else None


def with_purchase_qty(cand: Candidate, qty: int) -> Candidate:
    """카탈로그 원본 상품을 qty개 산 실제 구성의 사본 — 총용량 = 상품 총용량 × qty, 모듈 수 = 상품 모듈 수 × qty.
    모듈 수·용량을 읽을 수 없으면 원본 그대로(호환 검사가 '정보 없음'으로 처리한다)."""
    if not qty or qty <= 1:
        return cand
    count = parse_module_count(cand.specs.get("module_config"))
    capacity = _number(cand.specs.get("capacity_gb"))
    if count is None or count < 1 or capacity is None:
        return cand
    specs = dict(cand.specs)
    specs["capacity_gb"] = capacity * qty
    specs["module_config"] = f"{_gb(capacity / count)}GB × {count * qty}"
    return cand.model_copy(update={"specs": specs, "purchase_qty": qty})
