"""견적 글에 적힌 가격 읽기·비교 (CHK-05). DB·LLM 없이 도는 순수 함수.

견적 캡처·붙여 넣은 견적은 부품 문구 끝에 가격을 적는다("RTX 4060 Ti 520,000원", "라이젠 7500F 25만 5천원").
여기서는 그 가격을 읽어 정수(원)로 돌려주고, 부품 이름 매칭에 방해되지 않게 가격 표기를 글에서 걷어 낸다.
가격을 계산하거나 환산하지 않는다 — 글에 적힌 금액만 옮긴다. 읽지 못하면 None(비교하지 않는다).
"""
from __future__ import annotations

import re

MIN_PRICE, MAX_PRICE = 1_000, 50_000_000           # 이 범위를 벗어나면 가격이 아니라 다른 숫자(모델 번호 등)로 본다
SIMILAR_PCT = 5.0                                  # 견적 가격과 카탈로그 가격이 ±5% 안이면 "비슷함"

# "250,000원", "₩250,000", "250000원"
_WON = re.compile(r"(?:₩\s*)?(?<![\d,.$])(\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:원|₩)|₩\s*(\d{1,3}(?:,\d{3})+|\d{4,})")
# "25만원", "25.5만원", "25만 5천원", "25만5천"
_MAN = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*만\s*(?:(\d{1,2})\s*천)?\s*원?")
_CHEON = re.compile(r"(?<![\d.만])(\d{1,2})\s*천\s*원")
# 원·₩ 없이 천 단위 쉼표만 있는 금액("250,000") — 뒤에 W·GB 같은 단위가 붙으면 가격이 아니다("1,000W")
_COMMA = re.compile(r"(?<![\d,.$])(\d{1,3}(?:,\d{3})+)(?![\d,]|\.\d|\s*[A-Za-z])")      # "$1,299.99"는 원 가격이 아니다


def _spans(text: str) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    for m in _WON.finditer(text):
        found.append((m.start(), m.end(), int((m.group(1) or m.group(2)).replace(",", ""))))
    for m in _MAN.finditer(text):
        found.append((m.start(), m.end(), round(float(m.group(1)) * 10_000) + int(m.group(2) or 0) * 1_000))
    for m in _CHEON.finditer(text):
        found.append((m.start(), m.end(), int(m.group(1)) * 1_000))
    for m in _COMMA.finditer(text):
        found.append((m.start(), m.end(), int(m.group(1).replace(",", ""))))
    # 같은 자리를 여러 패턴이 잡으면 더 긴 표기를 남긴다("25만 5천원" 안의 "5천원" 등).
    found.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, int]] = []
    for span in found:
        if not any(span[0] < k[1] and k[0] < span[1] for k in kept) and MIN_PRICE <= span[2] <= MAX_PRICE:
            kept.append(span)
    return kept


def parse_price(text: object) -> int | None:
    """글에 적힌 가격(원). 여러 금액이 있으면 마지막 것 — "정가 30만원 → 25만원"처럼 할인가가 뒤에 오는 게 관례다."""
    spans = _spans(str(text or ""))
    return spans[-1][2] if spans else None


def strip_price(text: object) -> str:
    """가격 표기를 걷어 낸 부품 문구. 가격 숫자가 이름 매칭·스펙 읽기에 섞이지 않게 한다."""
    raw = str(text or "")
    for start, end, _ in reversed(_spans(raw)):
        raw = raw[:start] + " " + raw[end:]
    return re.sub(r"\s{2,}", " ", raw).strip(" \t-–—:/|,·")


def compare_price(quoted: int | None, catalog: int | None) -> dict:
    """견적 가격 대 카탈로그 가격 — 차이(원·%)와 판정. 한쪽이라도 없으면 비교하지 않는다."""
    if quoted is None:
        return {"state": "no_quote_price", "diff": None, "diff_pct": None}
    if catalog is None or catalog <= 0:
        return {"state": "no_catalog", "diff": None, "diff_pct": None}
    diff = quoted - catalog
    pct = round(diff / catalog * 100, 1)
    state = "similar" if abs(pct) <= SIMILAR_PCT else "pricier" if diff > 0 else "cheaper"
    return {"state": state, "diff": diff, "diff_pct": pct}


_KIT = re.compile(r"\d{1,3}\s*G(?:B)?\)?\s*[x×*]\s*(\d)\b", re.IGNORECASE)      # "16GB x2", "(16GB) x2"
_COUNT = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:개|ea\b)|수량\s*:?\s*(\d{1,2})", re.IGNORECASE)      # "2개", "2ea"


def line_quantity(text: object) -> int:
    """한 줄이 몇 개 분인가 — "16GB x2"(RAM 2장), "2개", "수량 2". 카탈로그 가격은 1개 기준이라 이 수만큼 곱해 견줘야 공정하다."""
    raw = str(text or "")
    kit = _KIT.search(raw)
    if kit:
        return max(1, min(int(kit.group(1)), 8))
    count = _COUNT.search(raw)
    return max(1, min(int(count.group(1) or count.group(2)), 20)) if count else 1
