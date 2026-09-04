"""
Buyer 자연어 요청(P.list) 파싱 — 명세서 §2-2 "Buyer 요청리스트는 텍스트 기반", §8/§9 우선순위 2.

parse_buyer_text(text) : 자유 서술 → BuyerRequest 필드 dict
  - NEGOTIATOR_MODE=llm + 키 있으면 LLM 구조화 출력
  - 아니면 정규식/키워드 폴백 (rule 모드 데모도 동작)
  - 반환 dict에 _missing(필수 필드 중 못 뽑은 것), _raw(원문) 포함

스펙 문자열은 그대로 spec으로 넘긴다 — 실제 속성 추출은 spec_match.extract_spec_tags가 담당.
"""

from __future__ import annotations
import re
from typing import Any

from .schemas import Item

ESSENTIAL = ("item", "qty", "cap_price")

# 부분 문자열(소문자) → Item
_ITEM_ALIASES: list[tuple[str, Item]] = [
    ("h100", Item.H100_NVL),
    ("a100", Item.A100_80GB_PCIe),
    ("l40s", Item.L40S),
    ("rtx pro 6000", Item.RTX_PRO_6000_Blackwell),
    ("pro 6000", Item.RTX_PRO_6000_Blackwell),
    ("blackwell", Item.RTX_PRO_6000_Blackwell),
    ("rtx 6000 ada", Item.RTX_6000_Ada),
    ("6000 ada", Item.RTX_6000_Ada),
    ("ada generation", Item.RTX_6000_Ada),
]


def parse_buyer_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"_raw": "", "_missing": list(ESSENTIAL)}

    import os
    use_llm = (
        os.environ.get("NEGOTIATOR_MODE", "rule").lower() == "llm"
        and bool(os.environ.get("OPENAI_API_KEY"))
    )
    parsed = _parse_llm(text) if use_llm else None
    if parsed is None:
        parsed = _parse_rule(text)

    parsed["_raw"] = text
    parsed["_missing"] = [k for k in ESSENTIAL if not parsed.get(k)]
    return parsed


# ────────────────────────── 정규식 폴백 ──────────────────────────

def _won(num: float, unit: str) -> int:
    unit = unit.strip()
    if "억" in unit:
        return int(num * 100_000_000)
    if "천만" in unit:
        return int(num * 10_000_000)
    if "백만" in unit:
        return int(num * 1_000_000)
    if "만" in unit:
        return int(num * 10_000)
    return int(num)


def _parse_rule(text: str) -> dict[str, Any]:
    t = text.lower()
    out: dict[str, Any] = {}

    # 품목
    for alias, item in _ITEM_ALIASES:
        if alias in t:
            out["item"] = item.value
            break
    else:
        for item in Item:
            if item.value.lower() in t:
                out["item"] = item.value
                break

    # 수량: "5대", "수량 5", "5개/장/ea"
    m = re.search(r"(?:수량\D{0,4})?(\d+)\s*(?:대|장|개|ea|units?|unit)\b", t) or re.search(r"수량\s*[:=]?\s*(\d+)", t)
    if m:
        out["qty"] = int(m.group(1))

    # 예산/상한가: "예산 대당 4천만원", "상한 40000000", "4,000만원 이하"
    m = re.search(r"(?:예산|상한가?|대당|가격|최대)\D{0,6}([\d,]+(?:\.\d+)?)\s*(억|천만|백만|만)?\s*원?", t)
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*(억|천만|백만|만)?\s*원\s*(?:이하|이내|까지|미만)", t)
    if m:
        out["cap_price"] = _won(float(m.group(1).replace(",", "")), m.group(2) or "")

    # 납기: "납기 30일", "30일 이내", "한 달"
    m = re.search(r"(\d+)\s*일", t)
    if m:
        out["max_lead_time_days"] = int(m.group(1))
    elif "한 달" in t or "한달" in t:
        out["max_lead_time_days"] = 30

    # 셀러 신뢰도 요구
    m = re.search(r"신뢰도?\s*(\d+)\s*(?:이상|이상이|점)?", t)
    if m:
        out["seller_trust_min"] = int(m.group(1))

    # 우선순위
    if re.search(r"(스펙|사양|성능)\s*(우선|중시|최우선)", t):
        out["priority"] = "spec_max"
    elif re.search(r"(가격|최저가|저렴|싼)\s*(우선|중시|최우선)?", t):
        out["priority"] = "price_min"

    out.setdefault("priority", "price_min")
    # 스펙: 원문 전체를 넘김 (extract_spec_tags가 GDDR/PCIe/W 등을 뽑아냄)
    out["spec"] = text
    return out


# ────────────────────────── LLM 파서 ──────────────────────────

def _parse_llm(text: str) -> dict[str, Any] | None:
    try:
        from .llm_agents import _get_client, MODEL
    except Exception:
        return None

    schema = {
        "type": "object",
        "properties": {
            "item": {"type": ["string", "null"], "enum": [i.value for i in Item] + [None]},
            "qty": {"type": ["integer", "null"]},
            "cap_price": {"type": ["integer", "null"], "description": "원 단위 정수 (대당 상한가)"},
            "spec": {"type": "string", "description": "요구 사양 문구 (메모리/인터페이스/전력 등). 없으면 빈 문자열"},
            "max_lead_time_days": {"type": ["integer", "null"]},
            "seller_trust_min": {"type": ["integer", "null"], "description": "0~100"},
            "priority": {"type": "string", "enum": ["price_min", "spec_max"]},
        },
        "required": ["item", "qty", "cap_price", "spec", "max_lead_time_days", "seller_trust_min", "priority"],
        "additionalProperties": False,
    }
    prompt = (
        "다음 B2B GPU 구매 요청(자연어)에서 필드를 뽑아 JSON으로 정규화하세요.\n"
        "item은 반드시 목록 중 하나거나 null. 가격은 '4천만원'=40000000 처럼 원 단위 정수로. "
        "우선순위 문구가 없으면 price_min.\n\n"
        f"요청: {text}"
    )
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "buyer_rfq", "schema": schema, "strict": True},
            },
        )
        import json
        raw = json.loads(resp.choices[0].message.content)
    except Exception:
        return None

    out: dict[str, Any] = {}
    if raw.get("item"):
        out["item"] = raw["item"]
    for k in ("qty", "cap_price", "max_lead_time_days", "seller_trust_min"):
        if isinstance(raw.get(k), int):
            out[k] = raw[k]
    out["spec"] = raw.get("spec") or text
    out["priority"] = raw.get("priority") or "price_min"
    return out
