"""받은 견적 점검 → 일부 교체 후 확정(재기획 3단계).

유지한 부품은 견적에 적힌 그대로(planning.kept_part_line), 교체한 부품은 카탈로그 제품의 판매 정보와 함께(planning.purchase_line) 얼린다.
점검 요약(호환·균형·게임·가격 변화)은 QUOTE_CONFIRM_KEY 조건에 얼려 리포트가 "받은 견적에서 만든 견적서"임을 안다.
가격은 보조 정보라, 모르는 유지 부품 가격을 0원으로 만들지 않는다 — 합계에 넣지 않고 `total_partial` 로 알린다.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from src.errors import Conflict, NotFound, ValidationFailed
from src.repo.plan_repo import QUOTE_CONFIRM_KEY, PlanRepo
from src.auth.deps import Principal
from src.services import list_service, quote_draft_service as qds, quote_replacement_plan
from src.services.session_service import _owned


def _display_name(item: dict) -> str:
    """견적 한 줄의 이름 — 텍스트 견적의 "CPU: " 같은 부품군 머리말과 가격은 뺀다."""
    name = (item.get("normalized_name") or item.get("raw_text") or "").strip()
    category = str(item.get("category") or "")
    for sep in (":", "："):
        if name.startswith(category + sep):
            return name[len(category) + 1:].strip() or name
    return name


def _freeze_summary(state: dict, kept_unpriced: list[str], total_partial: bool) -> dict:
    """리포트에 보여 줄 점검 요약 — 교체 목록을 적용하기 전/후 비교와 가격 변화."""
    return {
        "compat": state["compat"], "balance": state["balance"], "games": state["games"], "price": state["price"],
        "replacements": [{"slot": r["slot"], "from": r["from"], "to": r["candidate"], "price_delta": r["price_delta"],
                          "warnings": r["warnings"]} for r in state["replacements"]],
        "kept_unpriced_slots": kept_unpriced, "total_partial": total_partial,
    }


def confirm(conn, list_id: UUID, principal: Principal, *, expected_version: int, name: str,
            planned_purchase_at: str | None, target_amount: int | None, memo: str) -> dict:
    user_id = list_service._require_login(conn, principal)
    repo = PlanRepo(conn)
    revision = _owned(repo, list_id, principal)
    if revision["owner_user_id"] != user_id:
        raise NotFound("목록을 찾을 수 없습니다.")
    if revision["state"] == "confirmed":
        return list_service.get_report(conn, list_id, principal)
    repo.lock_revision(revision["id"])
    row = repo.active_condition(revision["id"], qds.QUOTE_DRAFT_KEY)
    if row is None:
        raise NotFound("이 목록에는 견적 초안이 없습니다.")
    draft = row["value"]["value"]
    if draft["version"] != expected_version:
        raise qds.StaleReviewVersion("초안이 다른 곳에서 바뀌었습니다. 새로 불러온 뒤 다시 시도해 주세요.", field="expected_version")
    review = qds._stored_review(conn, list_id, principal)           # 분석하지 않은 견적은 확정할 수 없다(409 analysis_required)
    if qds.analysis_stale(draft):
        raise Conflict("조건이나 부품이 바뀌어 분석이 오래됐어요. 다시 분석한 뒤 확정해 주세요.", code="analysis_stale")

    purchase_at = None
    if planned_purchase_at:
        try:
            purchase_at = datetime.fromisoformat(planned_purchase_at)
        except ValueError:
            raise ValidationFailed("구매 예정일 형식이 올바르지 않습니다.", field="planned_purchase_at") from None

    by_slot = qds.load_pc_catalog(lambda _msg: None)
    replacements = qds._replacement_map(draft, by_slot)
    chosen = qds._selected_items(draft)
    if not chosen:
        raise ValidationFailed("확정할 부품이 없습니다.", code="no_items_selected")
    state = quote_replacement_plan.build_state(review, replacements, by_slot)

    # 교체 부품은 판매 정보가 있어야 purchase_line 으로 얼린다 — 가격 관측이 없으면 확정하지 않는다(0원으로 얼리지 않는다).
    frozen_replacements = []
    for slot, cand in replacements.items():
        if not (cand.offer_observation_id and cand.price):
            raise ValidationFailed(f"{slot} 교체 후보의 가격 정보가 없어 확정할 수 없어요. 다른 제품을 골라 주세요.",
                                   code="replacement_unpriced", field="slot")
        offer_id = repo.offer_for_observation(UUID(cand.offer_observation_id))
        if offer_id is None:
            raise ValidationFailed(f"{slot} 교체 후보의 판매 정보를 찾을 수 없어요.", code="replacement_unpriced", field="slot")
        frozen_replacements.append((slot, cand, offer_id))

    images = qds._image_urls(conn, [c.product_id for _, c, _ in frozen_replacements if c.product_id])
    replaced_slots = {slot for slot, _, _ in frozen_replacements}
    kept = [i for i in chosen if i["category"] not in replaced_slots]
    kept_total = sum(int(i["quote_line_total"]) for i in kept if i.get("quote_line_total") is not None)
    kept_unpriced = [i["category"] for i in kept if i.get("quote_line_total") is None]
    replaced_total = sum(int(c.price) for _, c, _ in frozen_replacements)
    total = kept_total + replaced_total

    summary = _freeze_summary(state, kept_unpriced, total_partial=bool(kept_unpriced))
    repo.upsert_condition(revision["id"], QUOTE_CONFIRM_KEY, {"value": summary}, "extracted", bump_version=False)

    ok = repo.confirm_revision(revision["id"], confirmed_total=total, planned_purchase_at=purchase_at,
                               target_amount=target_amount, memo=memo, name=name)
    if not ok:
        raise Conflict("이미 확정된 목록입니다.")
    repo.rename(list_id, name)

    for slot, cand, offer_id in frozen_replacements:
        snapshot = {
            "slot": slot, "slot_label": slot, "qty": 1, "timing": "now", "review": None, "evidence_text": "", "evidence_source": None,
            "product": {"product_key": cand.product_key, "name": cand.name, "image_url": images.get(cand.product_id),
                        "purchase_url": (cand.provenance or {}).get("product_url")},
        }
        repo.add_purchase_line(revision["id"], offer_id, UUID(cand.offer_observation_id), int(cand.price), snapshot)

    pool_variant = {c.product_id: c.variant_id for cands in by_slot.values() for c in cands if c.product_id}
    for item in kept:
        pid = item.get("matched_product_id") if item.get("match_status") == "confirmed" else None
        variant_id = pool_variant.get(pid)
        quantity = max(int(item.get("quantity") or 1), 1)
        amount = int(item["quote_line_total"]) if item.get("quote_line_total") is not None else None
        snapshot = {
            "slot": item["category"], "slot_label": item["category"], "raw_text": item["raw_text"], "quantity": quantity,
            "display_name": _display_name(item), "match_status": item.get("match_status"), "matched_name": item.get("matched_name") if pid else None,
            "quote_unit_price": item.get("quote_unit_price"), "quote_price_type": item.get("quote_price_type"),
            "image_url": item.get("image_url"),
        }
        repo.add_kept_part_line(revision["id"], item["category"], item["raw_text"], UUID(variant_id) if variant_id else None,
                                amount, snapshot, pack_count=quantity)
    return list_service.get_report(conn, list_id, principal)
