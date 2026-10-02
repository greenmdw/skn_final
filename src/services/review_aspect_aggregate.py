"""Transactional rebuild of product/rule review-aspect aggregates."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg import pq
from psycopg.rows import dict_row


_PRODUCT_TYPE_BY_PART = {"mainboard": "motherboard"}


def _decimal_k(value: Any, rule_id: Any) -> Decimal:
    try:
        k = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"rule {rule_id} has invalid k") from exc
    if not k.is_finite() or k <= 0:
        raise ValueError(f"rule {rule_id} k must be positive and finite")
    return k


def _read_source(cur, analysis_version: str) -> tuple[dict, list, dict]:
    cur.execute(
        "SELECT id, part_type, k FROM evidence.review_aspect_rule "
        "WHERE analysis_version=%s ORDER BY id", (analysis_version,)
    )
    rules = {row["id"]: row for row in cur.fetchall()}
    if not rules:
        raise ValueError(f"analysis version has no registered rules: {analysis_version}")
    for rule_id, rule in rules.items():
        rule["k"] = _decimal_k(rule["k"], rule_id)

    cur.execute(
        "SELECT o.id AS observation_id, o.document_id, o.rule_id, o.direction, "
        "d.id AS found_document_id, d.product_id, d.is_synthetic, p.id AS found_product_id, "
        "p.product_type, r.part_type "
        "FROM evidence.review_aspect_observation o "
        "JOIN evidence.review_aspect_rule r ON r.id=o.rule_id "
        "LEFT JOIN evidence.review_document d ON d.id=o.document_id "
        "LEFT JOIN catalog.product p ON p.id=d.product_id "
        "WHERE r.analysis_version=%s ORDER BY d.product_id, o.rule_id, o.id",
        (analysis_version,),
    )
    observations = cur.fetchall()
    members: dict[tuple[Any, Any], list[Any]] = defaultdict(list)
    counts: dict[tuple[Any, Any], dict[str, Any]] = {}
    for obs in observations:
        rule_id = obs["rule_id"]
        if rule_id not in rules:
            raise ValueError(f"observation references an unselected rule: {rule_id}")
        if obs["found_document_id"] is None or obs["found_product_id"] is None:
            raise ValueError(f"broken document/product reference for observation {obs['observation_id']}")
        if obs["is_synthetic"]:
            raise ValueError(f"synthetic document linked to observation {obs['observation_id']}")
        expected_type = _PRODUCT_TYPE_BY_PART.get(obs["part_type"], obs["part_type"])
        if obs["product_type"] != expected_type:
            raise ValueError(
                f"product/rule part_type mismatch for observation {obs['observation_id']}"
            )
        direction = obs["direction"]
        if direction not in ("positive", "negative", "mixed"):
            raise ValueError(f"invalid direction for observation {obs['observation_id']}")
        key = (obs["product_id"], rule_id)
        if key not in counts:
            counts[key] = {"product_id": obs["product_id"], "rule_id": rule_id,
                           "p": 0, "n": 0, "mixed": 0, "k": rules[rule_id]["k"]}
        counts[key][{"positive": "p", "negative": "n", "mixed": "mixed"}[direction]] += 1
        members[key].append(obs["observation_id"])
    return rules, observations, {key: (counts[key], members[key]) for key in counts}


def _existing(cur, analysis_version: str) -> dict[tuple[Any, Any], dict]:
    cur.execute(
        "SELECT a.id, a.product_id, a.rule_id, a.p, a.n, a.mixed, a.k, a.q, "
        "(a.p::numeric + a.k * 0.5) / (a.p::numeric + a.n::numeric + a.k) AS expected_q, "
        "array_agg(m.observation_id ORDER BY m.observation_id) "
        "FILTER (WHERE m.observation_id IS NOT NULL) AS member_ids "
        "FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id "
        "LEFT JOIN evidence.review_aspect_aggregate_member m ON m.aggregate_id=a.id "
        "WHERE r.analysis_version=%s GROUP BY a.id, a.product_id, a.rule_id "
        "ORDER BY a.product_id, a.rule_id", (analysis_version,)
    )
    return {(row["product_id"], row["rule_id"]): row for row in cur.fetchall()}


def _report(groups: dict, old: dict, rules: dict, observations: list, version: str) -> dict:
    inserted, updated, unchanged = 0, 0, 0
    for key, (count, member_ids) in groups.items():
        prior = old.get(key)
        if prior is None:
            inserted += 1
            continue
        same = all(prior[col] == count[col] for col in ("p", "n", "mixed", "k"))
        same = same and set(prior["member_ids"] or []) == set(member_ids)
        if same:
            unchanged += 1
        else:
            updated += 1
    totals = {"positive": 0, "negative": 0, "mixed": 0}
    for obs in observations:
        totals[obs["direction"]] += 1
    return {
        "analysis_version": version,
        "rules": len(rules),
        "observations": len(observations),
        "groups": len(groups),
        **totals,
        "existing_aggregates": len(old),
        "would_insert": inserted,
        "would_update": updated,
        "unchanged": unchanged,
        "would_delete": len(set(old) - set(groups)),
    }


def _apply(cur, analysis_version: str, rules: dict, groups: dict) -> None:
    # Prune only stale groups belonging to this analysis version.
    cur.execute(
        "DELETE FROM evidence.review_aspect_aggregate a USING evidence.review_aspect_rule r "
        "WHERE r.id=a.rule_id AND r.analysis_version=%s AND NOT EXISTS ("
        "SELECT 1 FROM evidence.review_aspect_observation o "
        "JOIN evidence.review_document d ON d.id=o.document_id "
        "WHERE o.rule_id=a.rule_id AND d.product_id=a.product_id)", (analysis_version,)
    )
    # q is a generated column and deliberately omitted. ON CONFLICT preserves aggregate IDs.
    for count, _member_ids in groups.values():
        cur.execute(
            "INSERT INTO evidence.review_aspect_aggregate "
            "(product_id, rule_id, p, n, mixed, k) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (product_id, rule_id) DO UPDATE SET "
            "p=EXCLUDED.p, n=EXCLUDED.n, mixed=EXCLUDED.mixed, k=EXCLUDED.k",
            (count["product_id"], count["rule_id"], count["p"], count["n"],
             count["mixed"], count["k"]),
        )

    # Replace memberships for every aggregate in the selected version, including unchanged groups.
    cur.execute(
        "DELETE FROM evidence.review_aspect_aggregate_member m USING "
        "evidence.review_aspect_aggregate a, evidence.review_aspect_rule r "
        "WHERE m.aggregate_id=a.id AND r.id=a.rule_id AND r.analysis_version=%s",
        (analysis_version,),
    )
    if groups:
        keys = list(groups)
        cur.execute(
            "SELECT id, product_id, rule_id FROM evidence.review_aspect_aggregate "
            "WHERE (product_id, rule_id) IN ("
            + ",".join(["(%s,%s)"] * len(keys)) + ")",
            [value for key in keys for value in key],
        )
        aggregate_ids = {(row["product_id"], row["rule_id"]): row["id"]
                         for row in cur.fetchall()}
        cur.executemany(
            "INSERT INTO evidence.review_aspect_aggregate_member(aggregate_id, observation_id) "
            "VALUES (%s,%s)",
            [(aggregate_ids[key], observation_id)
             for key, (_count, member_ids) in groups.items() for observation_id in member_ids],
        )


def _verify(cur, version: str, groups: dict) -> None:
    actual = _existing(cur, version)
    if set(actual) != set(groups):
        raise RuntimeError("aggregate audit mismatch: group keys differ")
    for key, (expected, member_ids) in groups.items():
        row = actual[key]
        if any(row[column] != expected[column] for column in ("p", "n", "mixed", "k")):
            raise RuntimeError("aggregate audit mismatch: counts or k differ")
        if row["q"] != row["expected_q"]:
            raise RuntimeError("aggregate audit mismatch: generated q differs")
        if set(row["member_ids"] or []) != set(member_ids):
            raise RuntimeError("aggregate audit mismatch: member identities differ")
    cur.execute(
        "SELECT count(*) AS aggregate_count FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id "
        "WHERE r.analysis_version=%s", (version,)
    )
    if cur.fetchone()["aggregate_count"] != len(groups):
        raise RuntimeError("aggregate audit mismatch: aggregate row count differs")


def rebuild_review_aspect_aggregates(conn, analysis_version: str, *, apply: bool = False) -> dict:
    """Preview or rebuild one registered analysis version in one transaction.

    `apply=True` owns a transaction when called with a normal psycopg connection. The post-commit
    audit runs in a separate read-only repeatable-read snapshot. A post-commit audit failure means
    the write may already be committed and is reported distinctly by the caller.
    """
    if not analysis_version or not analysis_version.strip():
        raise ValueError("analysis_version must not be blank")
    if conn.info.transaction_status != pq.TransactionStatus.IDLE:
        raise ValueError("rebuild requires an idle connection and owns its transaction")
    report = None
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if not apply:
            conn.execute("SET TRANSACTION READ ONLY")
        else:
            # Keep this lock order aligned with review_observation_import.import_observations.
            conn.execute(
                "LOCK TABLE evidence.review_document, evidence.review_aspect_rule, "
                "evidence.review_aspect_observation, evidence.review_aspect_aggregate, "
                "evidence.review_aspect_aggregate_member IN SHARE ROW EXCLUSIVE MODE"
            )
            # The product type is part of structural validation; prevent it changing mid-rebuild.
            conn.execute("LOCK TABLE catalog.product IN SHARE MODE")
        with conn.cursor(row_factory=dict_row) as cur:
            rules, observations, groups = _read_source(cur, analysis_version)
            old = _existing(cur, analysis_version)
            report = _report(groups, old, rules, observations, analysis_version)
            if apply:
                _apply(cur, analysis_version, rules, groups)
                _verify(cur, analysis_version, groups)
    assert report is not None
    if apply:
        try:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                with conn.cursor(row_factory=dict_row) as cur:
                    rules, observations, groups = _read_source(cur, analysis_version)
                    _verify(cur, analysis_version, groups)
        except Exception as exc:
            raise RuntimeError(
                "aggregate rebuild committed, but the post-commit audit failed; inspect the target version"
            ) from exc
    return report
