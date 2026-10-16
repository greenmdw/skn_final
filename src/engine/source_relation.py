"""올린 사진 여러 장이 "한 견적을 나눠 찍은 것"인지 "서로 다른 견적"인지 읽은 결과로 판정한다(재기획: 업로드에서 묻지 않고 읽은 뒤 알린다).

사진이 읽힌 뒤의 항목(부품군·제품·어느 사진에서 읽혔는지)과 사진별 총액만 본다. DB·LLM 없이 도는 순수 함수다.
틀렸을 때 비용이 비대칭이다 — 서로 다른 견적을 한 견적으로 합치면 조용히 틀린 분석이 나오고, 한 견적을 나누면 비교 화면이 나와 바로 알아챈다.
그래서 근거가 약하면 `confidence="low"` 로 돌려 화면이 사용자에게 확인을 받게 한다.

근거 신호(임계값은 실제 사진으로 측정하며 조정한다):
- 겹치는 부품군이 없다(사진마다 다른 부품군만 보인다)      → 한 견적(강함)
- 두 사진에서 같은 부품이 겹쳐 있다                         → 한 견적(1개 약함, 2개 이상 강함)
- 같은 부품군에 서로 다른 제품이 있다                       → 서로 다른 견적(1개 약함, 2개 이상 강함)
- 사진마다 총액이 따로 있다 / 총액이 한 사진에만 있다       → 서로 다른 견적 / 한 견적(약함)
- 부품군이 5개 이상 보이는 사진이 둘 이상이다               → 서로 다른 견적(약함)"""
from __future__ import annotations

from typing import Any

FULL_BUILD_CATEGORIES = 5          # 사진 한 장에 이만큼의 부품군이 보이면 그 사진은 한 대 분량의 견적이다
_STRONG = 2


def judge(sources: list[dict[str, Any]], items: list[dict[str, Any]], choice: str | None = None) -> dict[str, Any]:
    """{applies, mode('single'|'separate'), confidence('high'|'low'), confirmed, reasons(고른 쪽을 받치는 근거), doubts(반대쪽 근거)}.
    `choice` 는 사용자가 확인한 값 — 있으면 그대로 따르고 `confirmed=True`."""
    images = [s["id"] for s in sources if s.get("type") == "image" and s.get("status") == "completed"]
    ids = set(images)
    if len(ids) < 2:
        return {"applies": False, "mode": "single", "confidence": "high", "confirmed": False, "reasons": [], "doubts": []}
    if choice in ("single", "separate"):
        return {"applies": True, "mode": choice, "confidence": "high", "confirmed": True, "reasons": ["사용자가 직접 확인했어요."], "doubts": []}

    seen: dict[str, dict[str, list[dict]]] = {}                    # 부품군 → 사진 → 그 사진에서 읽힌 항목
    cats_per_source: dict[str, set[str]] = {sid: set() for sid in ids}
    shared_items = 0
    for item in items:
        in_images = [sid for sid in item.get("source_ids") or [] if sid in ids]
        if len(in_images) >= 2:
            shared_items += 1
        for sid in in_images:
            seen.setdefault(item["category"], {}).setdefault(sid, []).append(item)
            cats_per_source[sid].add(item["category"])

    overlap = [c for c, per in seen.items() if len(per) >= 2]
    conflicts = []
    for category in overlap:
        covered = {sid for sid in seen[category] for item in seen[category][sid] if len({*item["source_ids"]} & ids) >= 2}
        if not covered:                                              # 같은 부품군을 두 사진 모두 읽었는데 같은 제품이 하나도 없다
            conflicts.append(category)

    single: list[tuple[int, str]] = []
    separate: list[tuple[int, str]] = []
    if not overlap:
        single.append((_STRONG, "사진마다 서로 다른 부품군만 보여요(겹치는 부품군이 없어요)."))
    if shared_items >= 2:
        single.append((_STRONG, f"두 사진에서 같은 부품 {shared_items}개가 겹쳐 있어요."))
    elif shared_items == 1:
        single.append((1, "두 사진에서 같은 부품 1개가 겹쳐 있어요."))
    if len(conflicts) >= 2:
        separate.append((_STRONG, f"같은 부품군에 서로 다른 제품이 있어요({', '.join(conflicts[:4])})."))
    elif len(conflicts) == 1:
        separate.append((1, f"같은 부품군에 서로 다른 제품이 있어요({conflicts[0]})."))
    totals = [s for s in sources if s.get("id") in ids and s.get("quote_total")]
    if len(totals) >= 2:
        separate.append((1, "각 사진에 견적 총액이 따로 적혀 있어요."))
    elif len(totals) == 1:
        single.append((1, "총액이 한 사진에만 적혀 있어요."))
    full = [sid for sid, cats in cats_per_source.items() if len(cats) >= FULL_BUILD_CATEGORIES]
    if len(full) >= 2:
        separate.append((1, f"부품군이 {FULL_BUILD_CATEGORIES}개 이상 보이는 사진이 둘 이상이에요."))

    single_score, separate_score = sum(w for w, _ in single), sum(w for w, _ in separate)
    mode = "separate" if separate_score > single_score else "single"
    confidence = "high" if abs(separate_score - single_score) >= _STRONG else "low"
    reasons, doubts = (separate, single) if mode == "separate" else (single, separate)
    return {"applies": True, "mode": mode, "confidence": confidence, "confirmed": False,
            "reasons": [t for _, t in reasons], "doubts": [t for _, t in doubts]}
