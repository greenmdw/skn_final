"""PC 견적 점검 — 같은 부품군의 대안 조회 (CHK-10의 뼈대이자 CHAT-04의 "대안 조회" 도구).

견적 속 부품 하나를 카탈로그의 같은 부품군 다른 제품으로 바꿨을 때, 견적의 나머지 부품과 호환되는지와 가격·성능 차이를
나란히 낸다. 호환은 추천엔진 7단계 함수(pc_compat_details)를 그대로 부른다(quote_review_service.compat_for_quote).
조회만 한다 — 견적이나 저장된 결과를 바꾸지 않는다(대안 적용은 CHK-08).
"""
from __future__ import annotations

import logging

from src.categories import load_category
from src.dto import Candidate
from src.engine.owned_parts import _match_catalog, resolve_owned_parts
from src.engine.quote_price import parse_price
from src.services import quote_review_service as qrs

DEFAULT_LIMIT = 5
_NEARBY = 0.35            # 방향을 안 정하면 현재 가격의 ±35% 안 후보를 가까운 순으로 보인다


def _baseline(slot: str, specs: dict, owned: dict) -> dict:
    info = owned.get(slot) or {}
    quoted = parse_price(specs.get(slot)) if specs.get(slot) else None
    price = quoted if quoted is not None else (info.get("catalog_price") if info.get("source") == "catalog" else None)
    tier = (info.get("specs") or {}).get("perf_tier") if info.get("source") == "catalog" else None
    return {"name": info.get("name") or specs.get(slot), "price": price, "perf_tier": tier,
            "confirmed": info.get("source") == "catalog"}


def alternatives(review: dict, slot: str, by_slot: dict[str, list[Candidate]], direction: str | None = None,
                 limit: int = DEFAULT_LIMIT) -> dict:
    """direction: "cheaper"(현재보다 저렴) · "better"(성능 등급이 높거나 더 비싼) · None(가격이 가까운 순)."""
    specs = (review.get("input") or {}).get("current_specs") or {}
    slot_structure = load_category("computer")["slot_structure"]
    if slot not in slot_structure:
        return {"slot": slot, "error": f"'{slot}' 부품군이 아닙니다. 부품군: {', '.join(slot_structure)}"}
    if not by_slot.get(slot):
        return {"slot": slot, "error": f"카탈로그에 {slot} 후보가 없습니다."}
    owned = resolve_owned_parts(specs, by_slot, slot_structure)
    baseline = _baseline(slot, specs, owned)
    base_incompat = set(qrs.compat_for_quote(specs, by_slot, slot_structure, owned)["incompatible"])
    have_tier = baseline["perf_tier"] is not None

    rows = []
    for cand in by_slot[slot]:
        if baseline["confirmed"] and cand.name == baseline["name"]:
            continue
        swapped = dict(owned)
        swapped[slot] = {"name": cand.name, "specs": dict(cand.specs), "source": "catalog"}
        result = qrs.compat_for_quote(specs, by_slot, slot_structure, swapped)
        # 바꾸기 전부터 있던 비호환은 이 후보 탓이 아니다 — 새로 생기는 확정 비호환만 센다.
        new_fail = [a for a in result["incompatible"] if a not in base_incompat]
        delta = cand.price - baseline["price"] if baseline["price"] is not None else None
        tier = cand.specs.get("perf_tier")
        rows.append({"name": cand.name, "price": cand.price, "price_delta": delta, "perf_tier": tier,
                     "incompatible": new_fail, "unknown": result["summary"].get("unknown", 0)})

    if direction == "cheaper" and baseline["price"] is not None:
        rows = [r for r in rows if r["price"] < baseline["price"]]
        rows.sort(key=lambda r: (bool(r["incompatible"]), -r["price"]))          # 현재보다 싸면서 가장 가까운(비싼) 것부터
    elif direction == "better":
        if have_tier:
            rows = [r for r in rows if r["perf_tier"] is not None and r["perf_tier"] > baseline["perf_tier"]]
            rows.sort(key=lambda r: (bool(r["incompatible"]), r["perf_tier"], r["price"]))      # 한 단계 위부터
        elif baseline["price"] is not None:
            rows = [r for r in rows if r["price"] > baseline["price"]]
            rows.sort(key=lambda r: (bool(r["incompatible"]), r["price"]))
    elif baseline["price"] is not None:
        near = [r for r in rows if abs(r["price"] - baseline["price"]) <= baseline["price"] * _NEARBY]
        rows = near or rows
        rows.sort(key=lambda r: (bool(r["incompatible"]), abs(r["price"] - baseline["price"])))
    else:
        rows.sort(key=lambda r: (bool(r["incompatible"]), r["price"]))
    # 확정된 비호환이 없는 후보를 먼저 보이되, 비호환 후보도 이유와 함께 남긴다(사용자가 이유를 알 수 있게).
    rows = rows[:limit]
    notes = []
    if baseline["price"] is None:
        notes.append("견적에 이 부품의 가격이 없어 가격 차이는 계산하지 않았습니다.")
    if direction == "better" and not have_tier:
        notes.append("현재 부품의 성능 등급을 확인하지 못해 더 비싼 순으로 보였습니다.")
    return {"slot": slot, "baseline": baseline, "candidates": rows, "note": " ".join(notes) or None}


# ── 부품 비교 (CHK-10) ─────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)
COMPARE_LIMIT = 3

# 부품군별로 나란히 보일 스펙 — (키, 라벨, 단위). 카탈로그 스펙 키 그대로이고 값이 없으면 "정보 없음"이다.
SPEC_ROWS: dict[str, list[tuple[str, str, str]]] = {
    "CPU": [("perf_tier", "성능 등급", ""), ("socket", "소켓", ""), ("tdp_w", "기본 전력", "W"), ("max_power_w", "최대 전력", "W"),
            ("mem_type", "메모리 규격", ""), ("family", "계열", "")],
    "GPU": [("perf_tier", "성능 등급", ""), ("vram_gb", "VRAM", "GB"), ("power_w", "전력", "W"), ("length_mm", "길이", "mm"),
            ("slot_thickness", "두께", "슬롯"), ("power_connector", "전원 커넥터", "")],
    "RAM": [("mem_type", "규격", ""), ("capacity_gb", "용량", "GB"), ("speed_mts", "속도", "MT/s"), ("module_config", "구성", "")],
    "메인보드": [("socket", "소켓", ""), ("form_factor", "크기", ""), ("mem_type", "메모리 규격", ""), ("dimm_slots", "DIMM 슬롯", "개"),
              ("m2_slots", "M.2 슬롯", "개"), ("max_memory_gb", "최대 메모리", "GB")],
    "저장장치": [("capacity_gb", "용량", "GB"), ("form_factor", "폼팩터", ""), ("interface", "인터페이스", "")],
    "파워": [("wattage_w", "정격 용량", "W"), ("form_factor", "크기", ""), ("efficiency_rating", "효율 등급", ""), ("length_mm", "길이", "mm")],
    "케이스": [("supports_form_factors", "지원 보드 크기", ""), ("max_gpu_len_mm", "GPU 최대 길이", "mm"),
            ("max_cooler_height_mm", "쿨러 최대 높이", "mm"), ("expansion_slots", "확장 슬롯", "개")],
    "쿨러": [("cooling_type", "방식", ""), ("height_mm", "높이", "mm"), ("radiator_mm", "라디에이터", "mm"), ("supported_socket", "지원 소켓", "")],
}


def _spec_rows(slot: str, base_specs: dict, cand_specs: dict) -> list[dict]:
    rows = []
    for key, label, unit in SPEC_ROWS.get(slot, []):
        base, cand = base_specs.get(key), cand_specs.get(key)
        diff = None
        if isinstance(base, (int, float)) and isinstance(cand, (int, float)) and not isinstance(base, bool):
            diff = round(cand - base, 2)
        rows.append({"key": key, "label": label, "unit": unit, "baseline": base, "candidate": cand, "diff": diff})
    return rows


def _review_brief(product_key: str | None) -> dict | None:
    """추천 결과와 같은 리뷰 배지(review_service.review_brief) — 관측된 신호와 리뷰 수만 옮긴다. 합성 데모값은 싣지 않는다."""
    if not product_key:
        return None
    try:
        from src.services import review_service
        brief = review_service.review_brief(product_key)
    except Exception:  # noqa: BLE001 — 리뷰 조회 실패가 부품 비교를 막으면 안 된다
        log.warning("review brief failed for %s", product_key, exc_info=True)
        return None
    if not brief:
        return None
    plain = brief.get("plain") or {}
    return {"total_count": brief.get("total_count"), "headline": plain.get("headline"), "points": plain.get("points") or [],
            "reason": plain.get("reason")}


def _compat_changes(base_checks: list[dict], new_checks: list[dict]) -> list[dict]:
    """바꿨을 때 상태가 달라지는 검사만 — 통과→비호환, 확인 못 함→통과 처럼 이 후보 때문에 생기는 변화."""
    before = {c["axis"]: c for c in base_checks}
    out = []
    for c in new_checks:
        old = before.get(c["axis"])
        if old is not None and old["state"] != c["state"]:
            out.append({"axis": c["axis"], "label": c["label"], "from": old["state"], "to": c["state"], "detail": c["detail"]})
    return out


def _resolve_targets(targets: list[str], pool: list[Candidate]) -> tuple[list[Candidate], list[str]]:
    """사용자가 적은 비교 대상(이름·모델명) → 카탈로그 후보. 못 찾은 것은 따로 돌려준다(지어내지 않는다)."""
    found: list[Candidate] = []
    missing: list[str] = []
    for text in targets:
        hits = _match_catalog(text, pool)
        if not hits:
            low = text.lower().strip()
            hits = [c for c in pool if low and low in c.name.lower()]
        if len(hits) == 1 or (hits and len({c.name for c in hits}) == 1):
            if hits[0] not in found:
                found.append(hits[0])
        elif hits:
            missing.append(f"{text} (후보가 여러 개: {', '.join(c.name for c in hits[:4])})")
        else:
            missing.append(text)
    return found, missing


def compare_parts(review: dict, slot: str, by_slot: dict[str, list[Candidate]], targets: list[str] | None = None,
                  direction: str | None = None, limit: int = COMPARE_LIMIT) -> dict:
    """견적 속 부품 하나와 같은 부품군의 다른 제품을 스펙·가격·리뷰로 나란히 — 견적의 나머지 부품과 호환되는지 함께.

    targets 를 주면 그 제품들과, 안 주면 대안 조회(alternatives)가 고른 후보와 비교한다. 조회만 한다."""
    picked = alternatives(review, slot, by_slot, direction, limit=limit if not targets else 40)
    if picked.get("error"):
        return picked
    specs = (review.get("input") or {}).get("current_specs") or {}
    slot_structure = load_category("computer")["slot_structure"]
    owned = resolve_owned_parts(specs, by_slot, slot_structure)
    info = owned.get(slot) or {}
    base_compat = qrs.compat_for_quote(specs, by_slot, slot_structure, owned)
    base_checks, base_incompat = base_compat["checks"], set(base_compat["incompatible"])
    base_specs = dict(info.get("specs") or {})
    baseline = {**picked["baseline"], "specs_known": bool(base_specs), "review": _review_brief(info.get("product_key"))}

    unmatched: list[str] = []
    if targets:
        cands, unmatched = _resolve_targets(targets, by_slot[slot])
        chosen = cands[:limit + 2]
    else:
        pool = {c.name: c for c in by_slot[slot]}
        chosen = [pool[c["name"]] for c in picked["candidates"] if c["name"] in pool]

    rows = []
    for cand in chosen:
        swapped = dict(owned)
        swapped[slot] = {"name": cand.name, "specs": dict(cand.specs), "source": "catalog"}
        result = qrs.compat_for_quote(specs, by_slot, slot_structure, swapped)
        base_price = baseline.get("price")
        rows.append({
            "name": cand.name, "price": cand.price,
            "price_delta": cand.price - base_price if base_price is not None else None,
            "perf_tier": cand.specs.get("perf_tier"),
            "specs": _spec_rows(slot, base_specs, dict(cand.specs)),
            "incompatible": [a for a in result["incompatible"] if a not in base_incompat],      # 이 후보 때문에 새로 생기는 확정 비호환
            "compat_changes": _compat_changes(base_checks, result["checks"]),
            "review": _review_brief(cand.product_key),
        })
    notes = [picked["note"]] if picked.get("note") else []
    if not baseline["confirmed"]:
        notes.append("견적의 이 부품이 카탈로그의 같은 제품으로 확인되지 않아 스펙 비교의 기준(견적 쪽) 값은 글에서 읽은 것만 있습니다.")
    return {"slot": slot, "baseline": baseline, "candidates": rows, "unmatched_targets": unmatched,
            "note": " ".join(notes) or None}
