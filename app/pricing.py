"""
가격·매칭 공통 규칙 — negotiate.py(중앙집중형)와 seller_service.py(분산형)가 함께 쓴다.
store.py 같은 무거운 모듈을 끌어오지 않도록 여기 따로 둔다.
"""

from __future__ import annotations

from .schemas import SellerRegister

SPEC_MATCH_MIN = 0.3  # 사양 유사도가 이 값 미만이면 후보에서 제외


def apply_bulk_discount(seller: SellerRegister, qty: int, price: int) -> tuple[int, dict | None]:
    """대량구매할인 — 주문 수량이 셀러 기준 이상이면 합의가에 할인율을 적용한다.
    할인 후에도 최저수용가 밑으로는 내려가지 않는다. 반환: (최종가, 할인내역 dict 또는 None)."""
    if seller.bulk_discount_min_qty <= 0 or seller.bulk_discount_rate <= 0:
        return price, None
    if qty < seller.bulk_discount_min_qty:
        return price, None
    discounted = max(seller.floor_price, int(round(price * (1 - seller.bulk_discount_rate))))
    if discounted >= price:
        return price, None
    return discounted, {
        "rate": seller.bulk_discount_rate,
        "min_qty": seller.bulk_discount_min_qty,
        "before": price,
        "after": discounted,
    }
