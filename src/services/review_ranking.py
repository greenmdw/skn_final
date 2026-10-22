"""Shared review-profile and score orchestration for every PC ranking entry point."""
from __future__ import annotations

import os
from uuid import UUID
from psycopg.types.json import Jsonb

from src.dto import HardFilterResult, ReviewRequirementProfile, Slots
from src.engine import LogFn, stage3b_rank
from src.repo.review_aspect_repo import load_review_aspect_snapshot
from src.services.review_aspect_score import (
    ReviewProductIdentifierError,
    build_review_requirement_profile,
    calculate_review_score,
    load_review_profile_config,
)


class ReviewRankingError(RuntimeError):
    """Review inputs are not ready for a database-backed recommendation."""


def rank_with_review_aspects(
    hf: HardFilterResult,
    spec,
    slots: Slots,
    log: LogFn,
    *,
    conn=None,
    run_id: UUID | str | None = None,
    catalog_source: str | None = None,
):
    """Attach one immutable review detail per candidate, then invoke the pure ranker.

    CATALOG_SOURCE=mock is the only neutral path. All other modes require a live DB
    snapshot and valid product IDs; callers may pass their current recommendation
    transaction connection so the ranking sees the same database transaction.
    """
    source = catalog_source if catalog_source is not None else os.environ.get("CATALOG_SOURCE", "db")
    offline = source == "mock"
    if source not in {"db", "mock"}:
        raise ReviewRankingError(f"unsupported CATALOG_SOURCE: {source}")

    candidates = [candidate for group in hf.slots.values() for candidate in group]
    if run_id is not None and offline:
        raise ReviewRankingError("a persisted recommendation run cannot use offline neutral review scoring")
    if run_id is not None and conn is None:
        raise ReviewRankingError("persisting a review profile requires the recommendation transaction connection")
    config = load_review_profile_config()
    profiles: dict[str, ReviewRequirementProfile] = {}
    candidate_types: dict[int, str] = {}
    expected_part_types = {
        "CPU": "cpu", "GPU": "gpu", "RAM": "ram", "메인보드": "mainboard",
        "저장장치": "ssd", "파워": "psu", "케이스": "case", "쿨러": "cooler",
    }

    if offline:
        # Scenario/demo candidates have no product IDs or DB rules. The mapping still
        # fixes alpha and conditions; every contribution records explicit demo neutrality.
        part_type_by_slot = {
            "메인보드": "mainboard", "저장장치": "ssd", "파워": "psu",
            "쿨러": "cooler", "케이스": "case",
        }
        for candidate in candidates:
            if candidate.product_id is not None:
                raise ReviewRankingError("offline mock ranking received a DB product_id candidate")
            part_type = part_type_by_slot.get(candidate.slot, candidate.slot.lower())
            if part_type not in config["part_types"]:
                raise ReviewRankingError(f"no review profile mapping for candidate slot {candidate.slot}")
            candidate_types[id(candidate)] = part_type
            if part_type not in profiles:
                profiles[part_type] = build_review_requirement_profile(
                    part_type, slots.values, assumed_keys=slots.assumed_keys, config=config,
                )
        for candidate in candidates:
            detail = calculate_review_score(
                profiles[candidate_types[id(candidate)]],
                {"analysis_version": config["analysis_version"], "products": {}},
                candidate.product_id, allow_missing_product_id=True,
            )
            candidate.review_detail = detail
    else:
        ids = [candidate.product_id for candidate in candidates]
        if any(product_id is None for product_id in ids):
            raise ReviewRankingError("DB recommendation candidate is missing product_id")
        own_connection = conn is None
        if own_connection:
            from src.db import get_conn
            connection_context = get_conn()
        else:
            from contextlib import nullcontext
            connection_context = nullcontext(conn)
        with connection_context as active_conn:
            snapshot = load_review_aspect_snapshot(active_conn, config["analysis_version"], ids)
            for candidate in candidates:
                product_key = str(candidate.product_id)
                product = snapshot["products"].get(product_key)
                if product is None:
                    raise ReviewRankingError(f"candidate product absent from review snapshot: {product_key}")
                part_type = product["part_type"]
                if expected_part_types.get(candidate.slot) != part_type:
                    raise ReviewRankingError(
                        f"candidate slot/product type mismatch: {candidate.slot}/{part_type}"
                    )
                candidate_types[id(candidate)] = part_type
                if part_type not in profiles:
                    profiles[part_type] = build_review_requirement_profile(
                        part_type, slots.values, assumed_keys=slots.assumed_keys,
                        registered_rules=list(product["rules"].values()), config=config,
                    )
            # Keep the global readiness limitation visible in the saved request profile.
            if not snapshot["readiness"]["global_completeness_verified"]:
                log("      ⚠ 리뷰 readiness: 요청 후보/규칙 범위의 관측·member 정합은 확인했지만 "
                    "전역 집계 완전성은 manifest가 없어 검증되지 않았습니다")
                for part_type, profile in list(profiles.items()):
                    profiles[part_type] = profile.model_copy(update={
                        "diagnostics": [*profile.diagnostics, "global_completeness_unverified"],
                    })
            for candidate in candidates:
                candidate.review_detail = calculate_review_score(
                    profiles[candidate_types[id(candidate)]], snapshot, candidate.product_id,
                )
            if run_id is not None:
                parts = {part_type: profile.model_dump(mode="json") for part_type, profile in profiles.items()}
                active_conn.execute(
                    "INSERT INTO engine.review_requirement_profile "
                    "(run_id, profile_version, analysis_version, parts) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (run_id) DO UPDATE SET profile_version=EXCLUDED.profile_version, "
                    "analysis_version=EXCLUDED.analysis_version, parts=EXCLUDED.parts",
                    (run_id, config["profile_version"], config["analysis_version"], Jsonb(parts)),
                )
                active_conn.execute(
                    "UPDATE engine.recommendation_run SET engine_versions=engine_versions || %s::jsonb "
                    "WHERE id=%s",
                    (Jsonb({"review_profile": config["profile_version"],
                            "review_analysis": config["analysis_version"]}), run_id),
                )

    rank = stage3b_rank.run(hf, spec, slots, log, require_review_details=True)
    return rank, profiles


def score_peripheral_candidates(conn, candidates_by_kind: dict, values: dict, *, catalog_source: str):
    """Attach versioned review details to peripheral candidates in one request snapshot.

    This does not create a recommendation run or persist a profile. The caller owns the
    transaction and passes the same candidates onward to peripheral ranking/payload.
    """
    config = load_review_profile_config()
    candidates = [candidate for group in candidates_by_kind.values() for candidate in group]
    profiles: dict[str, ReviewRequirementProfile] = {}
    if catalog_source == "mock":
        for kind, group in candidates_by_kind.items():
            if kind not in config["part_types"]:
                raise ReviewRankingError(f"no review profile mapping for peripheral kind {kind}")
            if any(candidate.product_id is not None for candidate in group):
                raise ReviewRankingError("offline peripheral mock received a DB product_id")
            profiles[kind] = build_review_requirement_profile(kind, values, config=config)
        snapshot = {"analysis_version": config["analysis_version"], "products": {}}
        for kind, group in candidates_by_kind.items():
            for candidate in group:
                candidate.review_detail = calculate_review_score(
                    profiles[kind], snapshot, candidate.product_id, allow_missing_product_id=True,
                )
        return profiles
    if catalog_source != "db":
        raise ReviewRankingError(f"unsupported CATALOG_SOURCE: {catalog_source}")
    if any(candidate.product_id is None for candidate in candidates):
        raise ReviewProductIdentifierError("DB peripheral candidate is missing product_id")
    snapshot = load_review_aspect_snapshot(
        conn, config["analysis_version"], [candidate.product_id for candidate in candidates],
    )
    for kind, group in candidates_by_kind.items():
        for candidate in group:
            product = snapshot["products"].get(str(candidate.product_id))
            if product is None or product["part_type"] != kind:
                raise ReviewRankingError(f"peripheral candidate kind/product mismatch: {kind}")
            if kind not in profiles:
                profiles[kind] = build_review_requirement_profile(
                    kind, values, registered_rules=list(product["rules"].values()), config=config,
                )
            candidate.review_detail = calculate_review_score(
                profiles[kind], snapshot, candidate.product_id,
            )
    if not snapshot["readiness"]["global_completeness_verified"]:
        for kind, profile in list(profiles.items()):
            profiles[kind] = profile.model_copy(update={
                "diagnostics": [*profile.diagnostics, "global_completeness_unverified"],
            })
            for candidate in candidates_by_kind[kind]:
                if candidate.review_detail is not None:
                    candidate.review_detail = candidate.review_detail.model_copy(update={
                        "profile": profiles[kind],
                        "diagnostics": [*candidate.review_detail.diagnostics,
                                        "global_completeness_unverified"],
                    })
    return profiles
