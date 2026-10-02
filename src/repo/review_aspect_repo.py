"""Batch reads for review-aspect aggregates and their observation evidence."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row


class ReviewAspectRepositoryError(RuntimeError):
    """The selected review data cannot safely be used for scoring."""


class ReviewAggregateNotReadyError(ReviewAspectRepositoryError):
    """No aggregate snapshot exists, or the requested products are only partly rebuilt."""


_PART_TYPE_BY_PRODUCT = {"motherboard": "mainboard"}


def _uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def load_review_aspect_snapshot(
    conn, analysis_version: str, product_ids: list[str | UUID],
) -> dict[str, Any]:
    """Read all selected products' rules, aggregates and members in one SQL snapshot.

    The query is request scoped and does no observation GROUP BY. It also checks source-observation
    existence for requested product/rule pairs, so missing aggregate rows are not silently treated
    as ordinary no-review cases. `version_has_any_aggregate` is a minimal global readiness signal;
    without a manifest, completeness outside the requested product scope cannot be proven.
    """
    if not analysis_version or not analysis_version.strip():
        raise ValueError("analysis_version must not be blank")
    normalized_ids = list(dict.fromkeys(_uuid(value) for value in product_ids))
    if not normalized_ids:
        return {
            "analysis_version": analysis_version,
            "products": {},
            "snapshot_consistency": "single_sql_statement",
            "readiness": {
                "status": "empty_request", "scope": "no product IDs supplied",
                "global_completeness_verified": False,
            },
        }

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "WITH requested(product_id) AS (SELECT DISTINCT unnest(%s::uuid[])), "
            "version_state AS (SELECT EXISTS ("
            "SELECT 1 FROM evidence.review_aspect_aggregate a "
            "JOIN evidence.review_aspect_rule ar ON ar.id=a.rule_id "
            "WHERE ar.analysis_version=%s) AS version_has_any_aggregate) "
            "SELECT req.product_id AS requested_product_id, p.id AS found_product_id, "
            "p.product_type, r.id AS rule_id, r.analysis_version AS rule_analysis_version, "
            "r.part_type, r.aspect_code, r.context_code, r.k, "
            "a.id AS aggregate_id, a.p, a.n, a.mixed, a.k AS aggregate_k, a.q, "
            "m.observation_id, o.rule_id AS member_rule_id, o.document_id, "
            "d.product_id AS member_product_id, d.is_synthetic AS member_is_synthetic, "
            "d.source_code, o.direction, "
            "o.observation_text, o.evidence_sentences, "
            "(SELECT count(*) FROM evidence.review_document sd "
            "JOIN evidence.review_aspect_observation so ON so.document_id=sd.id "
            "WHERE sd.product_id=req.product_id AND so.rule_id=r.id) AS source_observation_count, "
            "vs.version_has_any_aggregate "
            "FROM requested req CROSS JOIN version_state vs "
            "LEFT JOIN catalog.product p ON p.id=req.product_id "
            "LEFT JOIN evidence.review_aspect_rule r ON r.analysis_version=%s "
            "AND r.part_type=CASE p.product_type WHEN 'motherboard' THEN 'mainboard' ELSE p.product_type END "
            "LEFT JOIN evidence.review_aspect_aggregate a ON a.product_id=req.product_id AND a.rule_id=r.id "
            "LEFT JOIN evidence.review_aspect_aggregate_member m ON m.aggregate_id=a.id "
            "LEFT JOIN evidence.review_aspect_observation o ON o.id=m.observation_id "
            "LEFT JOIN evidence.review_document d ON d.id=o.document_id "
            "ORDER BY req.product_id, r.part_type, r.aspect_code, r.context_code, m.observation_id",
            (normalized_ids, analysis_version, analysis_version),
        )
        rows = cur.fetchall()

    products: dict[str, dict[str, Any]] = {}
    rules_by_product: dict[str, dict[str, dict]] = defaultdict(dict)
    version_has_any_aggregate: bool | None = None
    seen_products: set[str] = set()
    for row in rows:
        product_id = str(row["requested_product_id"])
        seen_products.add(product_id)
        if row["found_product_id"] is None:
            raise ReviewAspectRepositoryError(f"candidate product_id does not exist: {product_id}")
        product_type = row["product_type"]
        part_type = _PART_TYPE_BY_PRODUCT.get(product_type, product_type)
        if row["part_type"] is not None and row["part_type"] != part_type:
            raise ReviewAspectRepositoryError("product/rule part_type mismatch in review snapshot")
        if row["rule_id"] is not None and row["rule_analysis_version"] != analysis_version:
            raise ReviewAspectRepositoryError("review snapshot contains a mixed analysis version")
        version_has_any_aggregate = bool(row["version_has_any_aggregate"])
        product = products.setdefault(product_id, {
            "product_id": product_id, "product_type": product_type, "part_type": part_type,
            "rules": {},
        })
        if product["part_type"] != part_type or product["product_type"] != product_type:
            raise ReviewAspectRepositoryError("product type changed within review snapshot")
        rule_id = row["rule_id"]
        if rule_id is None:
            continue
        rule_key = str(rule_id)
        rule = rules_by_product[product_id].get(rule_key)
        if rule is None:
            rule = {
                "rule_id": rule_key,
                "analysis_version": row["rule_analysis_version"],
                "part_type": row["part_type"],
                "aspect_code": row["aspect_code"],
                "context_code": row["context_code"],
                "k": row["k"],
                "aggregate_id": str(row["aggregate_id"]) if row["aggregate_id"] else None,
                "p": row["p"] if row["p"] is not None else 0,
                "n": row["n"] if row["n"] is not None else 0,
                "mixed": row["mixed"] if row["mixed"] is not None else 0,
                "q": row["q"] if row["q"] is not None else None,
                "aggregate_k": row["aggregate_k"],
                "source_observation_count": row["source_observation_count"],
                "members": [],
            }
            rules_by_product[product_id][rule_key] = rule
        else:
            if rule["aggregate_id"] != (str(row["aggregate_id"]) if row["aggregate_id"] else None):
                raise ReviewAspectRepositoryError("aggregate identity changed within review snapshot")
        if row["observation_id"] is not None:
            if (row["document_id"] is None or row["member_product_id"] is None
                    or row["member_rule_id"] is None
                    or str(row["member_product_id"]) != product_id
                    or str(row["member_rule_id"]) != rule_key
                    or row["member_is_synthetic"] is not False
                    or row["direction"] not in ("positive", "negative", "mixed")):
                raise ReviewAspectRepositoryError("aggregate member has invalid observation evidence")
            rule["members"].append({
                "observation_id": str(row["observation_id"]),
                "document_id": str(row["document_id"]),
                "source_code": row["source_code"],
                "direction": row["direction"],
                "observation_text": row["observation_text"],
                "evidence_sentences": row["evidence_sentences"],
            })

    if seen_products != {str(product_id) for product_id in normalized_ids}:
        raise ReviewAspectRepositoryError("review snapshot omitted a requested product")
    for product_id, product in products.items():
        product["rules"] = rules_by_product[product_id]
        if not product["rules"]:
            raise ReviewAspectRepositoryError(
                f"analysis version has no registered rules for part_type {product['part_type']}"
            )

    if not version_has_any_aggregate:
        raise ReviewAggregateNotReadyError(
            f"analysis version has no aggregate rows: {analysis_version}"
        )

    aggregate_count = 0
    missing_scoped: list[tuple[str, str]] = []
    for product_id, product in products.items():
        for rule_id, rule in product["rules"].items():
            if rule["aggregate_id"] is None:
                if rule["source_observation_count"]:
                    missing_scoped.append((product_id, rule_id))
                continue
            aggregate_count += 1
            try:
                rule_k, aggregate_k = Decimal(rule["k"]), Decimal(rule["aggregate_k"])
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ReviewAspectRepositoryError("review rule or aggregate k is invalid") from exc
            if (not rule_k.is_finite() or rule_k <= 0 or not aggregate_k.is_finite()
                    or aggregate_k <= 0 or rule_k != aggregate_k):
                raise ReviewAspectRepositoryError("aggregate k differs from its registered rule")
            counts = {"positive": 0, "negative": 0, "mixed": 0}
            for member in rule["members"]:
                counts[member["direction"]] += 1
            if len(rule["members"]) != rule["p"] + rule["n"] + rule["mixed"]:
                raise ReviewAspectRepositoryError("aggregate/member observation count mismatch")
            if len(rule["members"]) != rule["source_observation_count"]:
                raise ReviewAspectRepositoryError("aggregate members do not cover current source observations")
            if (counts["positive"], counts["negative"], counts["mixed"]) != (
                rule["p"], rule["n"], rule["mixed"],
            ):
                raise ReviewAspectRepositoryError("aggregate/member direction counts mismatch")
    if missing_scoped:
        raise ReviewAggregateNotReadyError(
            f"selected products have source observations without aggregates ({len(missing_scoped)} product/rule pairs)"
        )

    return {
        "analysis_version": analysis_version,
        "products": products,
        "snapshot_consistency": "single_sql_statement",
        "readiness": {
            "status": "version_has_aggregates_scoped_validation_only",
            "scope": "requested products and registered rules; global partial coverage is not verifiable without a manifest",
            "requested_product_count": len(products),
            "aggregate_count_in_scope": aggregate_count,
            "global_completeness_verified": False,
        },
    }
