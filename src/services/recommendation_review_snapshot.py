"""Immutable review scoring inputs carried in the run's existing JSON trace.

Snapshot entries are machine-readable; readers never parse explanatory strings or
re-query current review aggregates. Legacy runs explicitly have unavailable detail.
"""
from __future__ import annotations

from pydantic import ValidationError

from src.dto import ReviewScoreDetail
from src.schemas import RecommendationReviewOut

SNAPSHOT_STEP = "리뷰 계산 snapshot"
SNAPSHOT_VERSION = "recommendation-review-snapshot-v1"


def snapshot_step(rank, build, run_id, conditions: dict) -> dict:
    candidates = {}
    weight = float(rank.weights_used.get("리뷰", 0))
    for slot, group in rank.slots.items():
        for candidate in group.get("pool") or group.get("ranked") or []:
            variant_id, product_id = candidate.get("variant_id"), candidate.get("product_id")
            if not variant_id or not product_id or not candidate.get("review_detail"):
                raise ValueError("ranked candidate has no immutable review identity/detail")
            detail = ReviewScoreDetail.model_validate(candidate["review_detail"])
            if candidate.get("breakdown", {}).get("리뷰") != detail.value:
                raise ValueError("ranked review score differs from its detail")
            candidates[str(variant_id)] = {
                "slot": slot, "product_id": str(product_id), "variant_id": str(variant_id),
                "rank_weight": weight, "rank_contribution": weight * detail.value,
                "rank_score": candidate["score"], "detail": detail.model_dump(mode="json"),
            }
    selected = {item.slot: str(item.variant_id) for item in build.items}
    if any(variant not in candidates for variant in selected.values()):
        raise ValueError("selected candidate is absent from its review snapshot")
    return {
        "step": SNAPSHOT_STEP, "title": "추천 당시 리뷰 계산 근거", "detail": "",
        "review_snapshot": {
            "version": SNAPSHOT_VERSION, "source_run_id": str(run_id),
            "request_conditions": conditions, "selected": selected, "candidates": candidates,
        },
    }


def snapshot_from_run(run: dict) -> dict | None:
    entries = [step.get("review_snapshot") for step in run.get("reasoning_log") or []
               if isinstance(step, dict) and step.get("step") == SNAPSHOT_STEP]
    if len(entries) != 1 or not isinstance(entries[0], dict):
        return None
    return entries[0] if entries[0].get("version") == SNAPSHOT_VERSION else None


def review_for_candidate(snapshot, *, variant_id, product_id, slot,
                         selection_source="automatic") -> dict:
    base = RecommendationReviewOut(
        product_id=str(product_id) if product_id else None,
        variant_id=str(variant_id), selection_source=selection_source,
    ).model_dump(mode="json")
    if snapshot is None:
        return base
    base.update(source_run_id=snapshot.get("source_run_id"),
                request_conditions=snapshot.get("request_conditions") or {})
    candidate = snapshot.get("candidates", {}).get(str(variant_id))
    if candidate is None:
        return {**base, "reason": "candidate_not_in_snapshot"}
    if candidate.get("product_id") != base["product_id"] or candidate.get("slot") != slot:
        return {**base, "status": "failed", "reason": "snapshot_identity_mismatch"}
    try:
        detail = ReviewScoreDetail.model_validate(candidate["detail"])
        return RecommendationReviewOut(
            **{**base, "status": "ready", "reason": None, "applied_to_ranking": True,
               "rank_weight": candidate["rank_weight"],
               "rank_contribution": candidate["rank_contribution"],
               "rank_score": candidate["rank_score"], "detail": detail},
        ).model_dump(mode="json")
    except (ValidationError, KeyError, TypeError):
        return {**base, "status": "failed", "reason": "invalid_snapshot_detail"}


def original_review(snapshot, *, slot, current_variant_id) -> dict | None:
    if snapshot is None:
        return None
    variant_id = snapshot.get("selected", {}).get(slot)
    if not variant_id or variant_id == str(current_variant_id):
        return None
    candidate = snapshot.get("candidates", {}).get(variant_id)
    if candidate is None:
        return None
    return review_for_candidate(snapshot, variant_id=variant_id,
                                product_id=candidate.get("product_id"), slot=slot)
