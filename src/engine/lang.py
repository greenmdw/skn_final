"""금액 표시 — 저장·계산은 원(KRW)이고 사용자에게도 원화로 낸다."""
from __future__ import annotations


def fmt_money(krw: int | float | None, signed: bool = False) -> str:
    """저장 금액(원)을 표시 문자열로. signed 면 부호(+/-)를 붙인다."""
    if krw is None:
        return "-"
    n = int(krw)
    return f"{n:+,}원" if signed else f"{n:,}원"
