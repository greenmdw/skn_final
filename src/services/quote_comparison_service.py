"""받은 견적 점검 — 저장 견적과의 서버 기준 비교 + 그 비교에 대한 질문의 구조화 자료 (개발요청서 BE-09·10·11).

비교는 제품 ID로 한다(문자열이 아니라 카탈로그 제품 키가 같은지) — 수량과 품목 합계 기준으로 가격 차이를 계산하고, 첫 요약
문장은 LLM 없이 계산 결과에서 만든다. 질문에 곁들이는 시각 자료(`visuals`)와 가이드(`guide_refs`)는 **서버 코드가** 조립한다 —
LLM은 `reply`의 일반 문장만 쓰고 가격·제품 ID·이미지 URL·호환 상태를 만들지 못한다(요청서 §7).

비교 결과는 조건 `quote_saved_comparisons`에 비교 시점의 제품 ID·수량·가격 snapshot으로 저장한다(스키마 변경 없음)."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.auth.deps import Principal
from src.engine.stage3_0_candidates import load_pc_catalog
from src.engine.stage3c_verify import AXIS_SLOTS
from src.errors import NotFound, TruefitError, ValidationFailed
from src.repo.plan_repo import QUOTE_DRAFT_KEY, QUOTE_REVIEW_KEY, QUOTE_SAVED_COMPARISONS_KEY, PlanRepo
from src.services import list_service, quote_review_service, session_service

log = logging.getLogger(__name__)

SLOTS = ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러")


class ComparisonNotFound(NotFound):
    code = "COMPARISON_NOT_FOUND"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _won(amount: int) -> str:
    return f"{amount:,}원"


# ── 받은 견적 쪽 ─────────────────────────────────────────────────────────────
def _received_side(repo: PlanRepo, revision: dict, review: dict, by_slot: dict) -> dict[str, dict]:
    """부품군 → 받은 견적의 제품 하나. 초안(여러 장 업로드)이 있으면 분석 기준으로 고른 항목, 없으면 점검 입력에서 읽는다."""
    from src.services import quote_draft_service

    out: dict[str, dict] = {}
    draft_row = repo.active_condition(revision["id"], QUOTE_DRAFT_KEY)
    if draft_row is not None:
        draft = draft_row["value"]["value"]
        chosen = set(draft["selected_item_by_category"].values())
        items = [i for i in draft["items"] if i["id"] in chosen]
    else:
        specs = (review.get("input") or {}).get("current_specs") or {}
        items = [quote_draft_service._make_item(slot, text, "review", by_slot) for slot, text in specs.items() if slot in SLOTS]
    for item in items:
        out[item["category"]] = {
            "product_id": item.get("matched_product_id"), "product_key": item.get("matched_product_key"),
            "name": item.get("matched_name") or item["normalized_name"], "image_url": item.get("image_url"),
            "quantity": item["quantity"], "line_total": item["quote_line_total"],
        }
    return out


# ── 저장 견적 쪽 ─────────────────────────────────────────────────────────────
def _saved_side(report: dict, by_slot: dict) -> dict[str, dict]:
    by_key = {c.product_key: c for cands in by_slot.values() for c in cands}
    out: dict[str, dict] = {}
    for item in report["items"]:
        slot, product = item.get("slot"), item.get("product") or {}
        if slot not in SLOTS:
            continue
        cand = by_key.get(product.get("product_key"))
        out[slot] = {
            "product_id": cand.product_id if cand else None, "product_key": product.get("product_key"),
            "name": product.get("name"), "image_url": product.get("image_url") or None,
            "quantity": item["qty"], "line_total": item["price"] * item["qty"],
        }
    return out


# ── BE-09 ────────────────────────────────────────────────────────────────────
def _summary_text(changed: int, total_diff: int, comparable_count: int, row_count: int) -> str:
    if not changed:
        return "두 견적의 부품이 모두 같습니다."
    base = f"{changed}개 부품이 다릅니다"
    if comparable_count == 0:
        return base + ". 가격이 양쪽에 모두 있는 부품이 없어 총액 차이는 비교하지 않았습니다."
    scope = "" if comparable_count == row_count else f"가격이 양쪽에 있는 {comparable_count}개 부품 기준 "
    if total_diff == 0:
        return f"{base}. {scope}총액은 같습니다."
    return f"{base}. {scope}저장 견적이 {_won(abs(total_diff))} 더 {'비쌉니다' if total_diff > 0 else '저렴합니다'}."


def build_comparison(received: dict[str, dict], saved: dict[str, dict]) -> dict:
    rows = []
    for category in SLOTS:
        r, s = received.get(category), saved.get(category)
        if r is None and s is None:
            continue
        same = bool(r and s and r.get("product_key") and r["product_key"] == s.get("product_key"))
        diff = s["line_total"] - r["line_total"] if r and s and r["line_total"] is not None and s["line_total"] is not None else None
        rows.append({"category": category, "same_product": same, "received": r, "saved": s, "price_diff": diff})
    received_total = sum(r["received"]["line_total"] for r in rows if r["received"] and r["received"]["line_total"] is not None)
    saved_total = sum(r["saved"]["line_total"] for r in rows if r["saved"] and r["saved"]["line_total"] is not None)
    excluded = [r["category"] for r in rows if r["received"] and r["received"]["line_total"] is None]
    # 총액 차이는 가격이 **양쪽에 모두** 있는 부품만으로 낸다 — 한쪽에 가격이 없는 부품·한쪽에만 있는 부품을 끼우면
    # "저장 견적이 179만 원 더 저렴"처럼 가격 없는 쪽이 0원인 것처럼 계산된다(사진 시험에서 확인).
    both = [r for r in rows if r["received"] and r["saved"] and r["received"]["line_total"] is not None and r["saved"]["line_total"] is not None]
    comparable_diff = sum(r["saved"]["line_total"] for r in both) - sum(r["received"]["line_total"] for r in both)
    changed = [r for r in rows if not r["same_product"]]
    priced = [r for r in rows if r["price_diff"] is not None and not r["same_product"]]
    largest = max(priced, key=lambda r: abs(r["price_diff"]))["category"] if priced else None
    return {
        "received_total": received_total, "saved_total": saved_total, "total_diff": comparable_diff,
        "comparable_categories": [r["category"] for r in both],
        "excluded_received_categories": excluded, "rows": rows,
        "brief_summary": {"changed_count": len(changed), "largest_price_difference_category": largest,
                          "text": _summary_text(len(changed), comparable_diff, len(both), len(rows))},
    }


def _comparisons(repo: PlanRepo, revision_id: UUID) -> dict[str, dict]:
    row = repo.active_condition(revision_id, QUOTE_SAVED_COMPARISONS_KEY)
    return dict(row["value"]["value"]) if row else {}


def create_comparison(conn, list_id: UUID, principal: Principal, saved_list_id: UUID, saved_revision_no: int | None) -> dict:
    """받은 견적(list_id)과 저장한 견적(확정 견적서)을 제품 ID 기준으로 비교한다. 양쪽 소유권·revision 을 검증한다."""
    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    row = repo.active_condition(revision["id"], QUOTE_REVIEW_KEY)
    if row is None:
        raise NotFound("이 목록에는 견적 점검 결과가 없습니다.")
    report = list_service.get_report(conn, saved_list_id, principal, saved_revision_no)       # 로그인·소유·확정 여부 검증
    by_slot = load_pc_catalog(lambda _msg: None)
    comparison = {
        "comparison_id": str(uuid.uuid4()), **build_comparison(_received_side(repo, revision, row["value"]["value"], by_slot),
                                                               _saved_side(report, by_slot)),
        "saved": {"list_id": str(saved_list_id), "revision_no": report["revision_no"], "name": report["name"]},
        "computed_at": _now(),
    }
    repo.lock_revision(revision["id"])
    stored = _comparisons(repo, revision["id"])
    stored[comparison["comparison_id"]] = comparison
    repo.upsert_condition(revision["id"], QUOTE_SAVED_COMPARISONS_KEY, {"value": stored}, "extracted", bump_version=False)
    return comparison


def _side_from_items(items: list[dict]) -> dict[str, dict]:
    return {i["category"]: {"product_id": i.get("matched_product_id"), "product_key": i.get("matched_product_key"),
                            "name": i.get("matched_name") or i["normalized_name"], "image_url": i.get("image_url"),
                            "quantity": i["quantity"], "line_total": i["quote_line_total"]} for i in items}


def _side_info(items: list[dict], by_slot: dict) -> dict:
    """견적 하나의 요약 — 합계와 같은 호환 검사(점검과 같은 함수) 결과."""
    from src.engine.owned_parts import resolve_owned_parts
    from src.engine.quote_items import spec_text

    specs = {i["category"]: spec_text(i) for i in items}
    owned = resolve_owned_parts(specs, by_slot, list(SLOTS))
    compat = quote_review_service.compat_for_quote(specs, by_slot, list(SLOTS), owned)
    priced = [i for i in items if i["quote_line_total"] is not None]
    return {"total": sum(i["quote_line_total"] for i in priced), "item_count": len(items),
            "missing_price_categories": [i["category"] for i in items if i["quote_line_total"] is None],
            "compat_summary": compat["summary"], "incompatible": compat["incompatible"]}


def compare_quotes(conn, list_id: UUID, principal: Principal, a_source_ids: list[str], b_source_ids: list[str]) -> dict:
    """한 초안에 올린 **서로 다른 두 견적**(예: 쇼핑몰 A안·B안 캡처)을 제품 ID 기준으로 비교한다. 저장 견적 비교와 같은 모양이고
    결과도 같은 곳에 저장해 `context`(comparison_id)로 이어서 질문할 수 있다. 질문은 분석(`analysis`)이 끝난 세션에서 된다."""
    from src.services import quote_draft_service as qds

    repo, revision, draft = qds._revision_and_draft(conn, list_id, principal, lock=True)
    if set(a_source_ids) & set(b_source_ids):
        raise ValidationFailed("두 견적은 서로 다른 이미지여야 합니다.", field="b_source_ids")
    a_items, b_items = qds.items_for_sources(draft, a_source_ids), qds.items_for_sources(draft, b_source_ids)
    names = {g["id"]: g["name"] for g in qds.groups(draft)}
    label = lambda ids: " + ".join(names.get(i, i) for i in ids)          # noqa: E731
    by_slot = load_pc_catalog(lambda _msg: None)
    comparison = {
        "comparison_id": str(uuid.uuid4()), **build_comparison(_side_from_items(a_items), _side_from_items(b_items)),
        "labels": {"received": label(a_source_ids), "saved": label(b_source_ids)},
        "sides": {"received": _side_info(a_items, by_slot), "saved": _side_info(b_items, by_slot)},
        "saved": {"source_ids": list(b_source_ids), "name": label(b_source_ids)},
        "kind": "draft_quotes", "computed_at": _now(),
    }
    stored = _comparisons(repo, revision["id"])
    stored[comparison["comparison_id"]] = comparison
    repo.upsert_condition(revision["id"], QUOTE_SAVED_COMPARISONS_KEY, {"value": stored}, "extracted", bump_version=False)
    return comparison


def get_comparison(conn, list_id: UUID, principal: Principal, comparison_id: str) -> dict:
    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    found = _comparisons(repo, revision["id"]).get(str(comparison_id))
    if found is None:
        raise ComparisonNotFound("그 비교를 찾을 수 없습니다.", field="comparison_id")
    return found


# ── 질문 해석(코드) ──────────────────────────────────────────────────────────
_SLOT_WORDS = {
    "CPU": ("cpu", "프로세서", "씨피유"), "GPU": ("gpu", "그래픽", "지피유", "vga"), "RAM": ("ram", "램", "메모리"),
    "메인보드": ("메인보드", "보드", "mainboard"), "저장장치": ("ssd", "저장", "스토리지", "nvme"),
    "파워": ("파워", "psu"), "케이스": ("케이스", "case"), "쿨러": ("쿨러", "cooler", "수랭", "공랭"),
}
_PRICE_WORDS = ("가격", "비싸", "싸", "얼마", "값", "비용", "차액", "총액", "합계")
_COMPAT_WORDS = ("호환", "맞아", "맞나", "맞는", "들어가", "장착", "소켓", "전력", "충분", "문제", "연결", "길이", "높이", "크기", "커넥터")
_INSTALL_WORDS = ("설치", "조립", "끼우", "꽂")
_AXIS_WORDS = {"소켓": "socket", "전력": "power", "충분": "power", "파워": "power", "메모리": "memory", "길이": "gpu_len",
               "높이": "cooler_height", "m.2": "m2", "커넥터": "gpu_connector"}
_AXIS_GUIDE_SLOT = {"socket": "CPU", "power": "GPU", "gpu_len": "GPU", "cooler_height": "쿨러", "memory": "RAM", "m2": "저장장치",
                    "gpu_connector": "GPU"}


def normalize_question(text: str) -> str:
    """같은 질문 판정용 — 앞뒤·연속 공백 정리, 영문 소문자, 문장 끝 ? ! . 제거(BE-12)."""
    t = re.sub(r"\s+", " ", (text or "").strip()).lower()
    return re.sub(r"[?!.？！。]+$", "", t).strip()


def match_slots(text: str) -> list[str]:
    low = text.lower()
    return [slot for slot, words in _SLOT_WORDS.items() if any(w in low for w in words)]


def classify(text: str) -> dict:
    """질문이 무엇을 묻는지 — 부품군(여럿 가능)·가격·호환·설치. 판정은 코드가 한다."""
    low = text.lower()
    slots = match_slots(low)
    axes = [axis for word, axis in _AXIS_WORDS.items() if word in low]
    return {"slots": slots, "price": any(w in low for w in _PRICE_WORDS),
            "compat": any(w in low for w in _COMPAT_WORDS), "install": any(w in low for w in _INSTALL_WORDS), "axes": axes}


# ── 시각 자료·가이드 조립(서버 코드) ─────────────────────────────────────────
def _side_card(side: str, p: dict | None) -> dict | None:
    if p is None:
        return None
    return {"side": side, "product_id": p.get("product_id"), "name": p.get("name"), "image_url": p.get("image_url"),
            "price": p.get("line_total")}


DEFAULT_LABELS = {"received": "받은 견적", "saved": "저장 견적"}


def _labels(comparison: dict) -> dict[str, str]:
    return {**DEFAULT_LABELS, **(comparison.get("labels") or {})}


def _spec_table(category: str, row: dict, by_key: dict, labels: dict) -> dict | None:
    from src.services.quote_alternatives import SPEC_ROWS

    specs = {}
    for side in ("received", "saved"):
        p = row.get(side)
        cand = by_key.get(p.get("product_key")) if p else None
        specs[side] = dict(cand.specs) if cand else {}
    if not specs["received"] and not specs["saved"]:
        return None
    rows = [[label + (f"({unit})" if unit else ""), specs["received"].get(key), specs["saved"].get(key)]
            for key, label, unit in SPEC_ROWS.get(category, [])]
    return {"type": "table", "category": category, "title": f"{category} 사양 비교",
            "columns": ["항목", labels["received"], labels["saved"]], "rows": rows}


def _price_table(rows: list[dict], categories: list[str] | None, labels: dict) -> dict:
    shown = [r for r in rows if categories is None or r["category"] in categories]
    return {"type": "table", "category": categories[0] if categories and len(categories) == 1 else None, "title": "가격 비교",
            "columns": ["부품군", labels["received"], labels["saved"], "차이"],
            "rows": [[r["category"], (r["received"] or {}).get("line_total"), (r["saved"] or {}).get("line_total"), r["price_diff"]]
                     for r in shown]}


def _compat_visuals(review: dict, comparison: dict, by_slot: dict, intent: dict) -> list[dict]:
    """호환 자료 — 받은 견적은 저장된 점검 결과에서, 저장 견적은 같은 검사로 다시 계산해서."""
    wanted_axes = set(intent["axes"]) | {a for a, slots in AXIS_SLOTS.items() if set(slots) & set(intent["slots"])} if (intent["axes"] or intent["slots"]) else None
    items = [{"side": "received", **c} for c in (review.get("compat") or {}).get("checks", []) if wanted_axes is None or c["axis"] in wanted_axes]
    by_key = {c.product_key: c for cands in by_slot.values() for c in cands}
    owned = {}
    for row in comparison["rows"]:
        p = row.get("saved")
        cand = by_key.get(p.get("product_key")) if p else None
        if cand is not None:
            owned[row["category"]] = {"name": cand.name, "specs": dict(cand.specs), "source": "catalog"}
    if owned:
        saved_checks = quote_review_service.compat_for_quote({}, by_slot, list(SLOTS), owned)["checks"]
        items += [{"side": "saved", **c} for c in saved_checks if wanted_axes is None or c["axis"] in wanted_axes]
    items = [{k: i[k] for k in ("side", "axis", "label", "state", "detail")} for i in items]
    return [{"type": "compatibility_check", "title": "호환 확인", "items": items}] if items else []


def guide_refs_for(text: str, intent: dict, search=None) -> list[dict]:
    """관련 질문에만, 올바른 슬롯의 가이드만(BE-11). 가격 질문엔 가이드를 붙이지 않는다. 개별 제품의 확정 사양처럼 쓰지 않는다."""
    if search is None:
        from src.rag.care_guides import search_care_guide as search
    wants_install = intent["install"]
    if not (intent["compat"] or wants_install):
        return []
    slots = list(intent["slots"]) or [_AXIS_GUIDE_SLOT[a] for a in intent["axes"] if a in _AXIS_GUIDE_SLOT]
    slots = list(dict.fromkeys(slots))[:2]
    kind = "install" if wants_install else "care"        # 설치를 명시적으로 물었을 때만 install
    refs = []
    for slot in slots:
        try:
            hits = search(text, k=1, slot=slot, kind=kind)
        except Exception:  # noqa: BLE001 — 가이드 검색이 실패해도 답은 나간다
            log.warning("care guide search failed for %s", slot, exc_info=True)
            continue
        for h in hits:
            refs.append({"id": h["id"], "slot": slot, "kind": h.get("kind", kind), "text": h["text"], "score": h.get("score")})
    return refs


def answer_extras(comparison: dict, review: dict, text: str, by_slot: dict, search=None) -> dict:
    """질문에 맞는 visuals·guide_refs·intent. CPU 질문엔 CPU 자료만, GPU 질문엔 GPU 자료만 — 부품군마다 객체를 따로 만든다."""
    intent = classify(text)
    rows = {r["category"]: r for r in comparison["rows"]}
    by_key = {c.product_key: c for cands in by_slot.values() for c in cands}
    visuals: list[dict] = []
    slots = [s for s in intent["slots"] if s in rows]
    for slot in slots:
        row = rows[slot]
        cards = [c for c in (_side_card("received", row["received"]), _side_card("saved", row["saved"])) if c]
        visuals.append({"type": "product_comparison", "category": slot, "title": f"{slot} 제품 비교", "items": cards})
        table = _spec_table(slot, row, by_key, _labels(comparison))
        if table:
            visuals.append(table)
    if intent["price"]:
        visuals.append(_price_table(comparison["rows"], slots or None, _labels(comparison)))
    if intent["compat"]:
        visuals += _compat_visuals(review, comparison, by_slot, intent)
    return {"intent": intent, "visuals": visuals, "guide_refs": guide_refs_for(text, intent, search)}


# ── LLM·규칙 답변의 근거 문장(사실만) ────────────────────────────────────────
def facts_text(comparison: dict, categories: list[str]) -> str:
    lab = _labels(comparison)
    rows = [r for r in comparison["rows"] if not categories or r["category"] in categories]
    lines = [comparison["brief_summary"]["text"],
             f"{lab['received']} 가격 합계 {_won(comparison['received_total'])}, {lab['saved']} 가격 합계 {_won(comparison['saved_total'])}."]
    if comparison.get("comparable_categories"):
        lines.append(f"가격이 양쪽에 있는 부품({', '.join(comparison['comparable_categories'])}) 기준으로 {lab['saved']}이(가) "
                     f"{_won(abs(comparison['total_diff']))} {'더 비쌈' if comparison['total_diff'] > 0 else '더 저렴' if comparison['total_diff'] < 0 else '같음'}.")
    if comparison["excluded_received_categories"]:
        lines.append(f"{lab['received']}에 가격이 없어 합계에서 뺀 부품: " + ", ".join(comparison["excluded_received_categories"]) + ".")
    for r in rows:
        rec, sav = r["received"], r["saved"]
        if r["same_product"]:
            lines.append(f"{r['category']}: 두 견적이 같은 제품({rec['name']})입니다.")
            continue
        left = f"{lab['received']} {rec['name']}" + (f"({_won(rec['line_total'])})" if rec and rec["line_total"] is not None else "") if rec else f"{lab['received']}에 없음"
        right = f"{lab['saved']} {sav['name']}" + (f"({_won(sav['line_total'])})" if sav and sav["line_total"] is not None else "") if sav else f"{lab['saved']}에 없음"
        diff = f", {lab['saved']}이(가) {_won(abs(r['price_diff']))} {'비쌈' if r['price_diff'] > 0 else '저렴' if r['price_diff'] < 0 else '같음'}" \
            if r["price_diff"] is not None else ""
        lines.append(f"{r['category']}: {left} ↔ {right}{diff}.")
    return "\n".join(lines)
