"""Validate agent input/output snapshots and atomically replace unaggregated observations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(Contract):
    rule_id: UUID
    observation_text: StrictStr = Field(min_length=1)
    direction: Literal["positive", "negative", "mixed"]
    evidence_sentences: list[StrictStr] = Field(min_length=1)


class Diagnostic(Contract):
    code: Literal["invalid_input", "analysis_failed", "synthetic_in_production",
                  "other_target", "not_experienced", "no_aspect_evidence", "out_of_scope",
                  "unknown_noise_source", "no_direction", "unmapped_rule", "ambiguous_rule"]
    evidence_text: StrictStr | None
    detail: StrictStr


class Result(Contract):
    document_id: UUID | None
    result: Literal["ok", "partial", "error"]
    observations: list[Observation]
    diagnostics: list[Diagnostic]


class Output(Contract):
    analysis_version: StrictStr = Field(min_length=1)
    results: list[Result]


Part = Literal["gpu", "cpu", "cooler", "mainboard", "ram", "ssd", "case", "psu"]


class Rule(Contract):
    id: UUID
    analysis_version: StrictStr
    part_type: Part
    aspect_code: StrictStr
    context_code: StrictStr
    definition: dict


class Review(Contract):
    document_id: UUID
    product_id: UUID
    part_type: Part
    product_name: StrictStr
    is_synthetic: StrictBool
    body: StrictStr = Field(min_length=1)


class Input(Contract):
    analysis_version: StrictStr = Field(min_length=1)
    mode: Literal["production", "test"]
    rules: list[Rule]
    reviews: list[Review]


def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Invalid JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=invalid)


def import_observations(conn, source: dict, output: dict, *, dry_run: bool = False) -> dict:
    """Caller must stop review writers during maintenance; no commit outside this transaction.

    Reject the entire file on any unresolved/error result. Exact reimports are no-ops.
    Changed observations already used by aggregates require a separate rebuild first.
    """
    inp, out = Input.model_validate(source), Output.model_validate(output)
    if inp.analysis_version != out.analysis_version or not inp.analysis_version.strip():
        raise ValueError("Analysis version mismatch or blank version")
    reviews = {r.document_id: r for r in inp.reviews}
    rules = {r.id: r for r in inp.rules}
    if len(reviews) != len(inp.reviews) or len(rules) != len(inp.rules):
        raise ValueError("Duplicate document or rule ID in input")
    if [r.document_id for r in out.results] != [r.document_id for r in inp.reviews]:
        raise ValueError("Output must cover every input document exactly once, in order")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        # Serialize loaders and block concurrent writes to the validated source tables.
        cur.execute("LOCK TABLE evidence.review_document, evidence.review_aspect_rule, "
                    "evidence.review_aspect_observation, evidence.review_aspect_aggregate, "
                    "evidence.review_aspect_aggregate_member IN SHARE ROW EXCLUSIVE MODE")
        for rule in inp.rules:
            cur.execute("SELECT id, analysis_version, part_type, aspect_code, context_code, definition "
                        "FROM evidence.review_aspect_rule WHERE id=%s", (rule.id,))
            if rule.analysis_version != inp.analysis_version or cur.fetchone() != rule.model_dump():
                raise ValueError(f"Missing or changed rule: {rule.id}")
        changes = []
        total = 0
        for result in out.results:
            review = reviews[result.document_id]
            if result.result != "ok" or any(d.code in {
                "invalid_input", "analysis_failed", "synthetic_in_production",
                "unmapped_rule", "ambiguous_rule"} for d in result.diagnostics):
                raise ValueError(f"Unresolved result: {review.document_id}")
            if inp.mode == "production" and review.is_synthetic:
                raise ValueError("Synthetic review in production")
            cur.execute("SELECT product_id, body, is_synthetic FROM evidence.review_document WHERE id=%s",
                        (review.document_id,))
            if cur.fetchone() != {"product_id": review.product_id, "body": review.body,
                                  "is_synthetic": review.is_synthetic}:
                raise ValueError(f"Missing or changed document: {review.document_id}")
            cur.execute(sql.SQL("SELECT 1 FROM catalog.{} WHERE product_id=%s").format(
                sql.Identifier(review.part_type + "_spec")), (review.product_id,))
            if not cur.fetchone():
                raise ValueError(f"Product part type mismatch: {review.document_id}")
            desired = {}
            for obs in result.observations:
                rule = rules.get(obs.rule_id)
                if rule is None or rule.part_type != review.part_type or obs.rule_id in desired:
                    raise ValueError("Unknown, duplicate, or mismatched observation rule")
                if not obs.observation_text.strip() or any(
                    not e.strip() or e not in review.body for e in obs.evidence_sentences
                ) or len(set(obs.evidence_sentences)) != len(obs.evidence_sentences):
                    raise ValueError("Invalid observation text or source evidence")
                desired[obs.rule_id] = obs.model_dump()
            for diag in result.diagnostics:
                if diag.evidence_text is not None and (
                    not diag.evidence_text.strip() or diag.evidence_text not in review.body
                ):
                    raise ValueError("Diagnostic evidence is not in source")
            cur.execute("SELECT rule_id, observation_text, direction, evidence_sentences "
                        "FROM evidence.review_aspect_observation WHERE document_id=%s",
                        (review.document_id,))
            existing = {row["rule_id"]: row for row in cur.fetchall()}
            total += len(desired)
            if existing == desired:
                continue
            cur.execute("SELECT 1 FROM evidence.review_aspect_aggregate_member m "
                        "JOIN evidence.review_aspect_observation o ON o.id=m.observation_id "
                        "WHERE o.document_id=%s LIMIT 1", (review.document_id,))
            linked = cur.fetchone()
            cur.execute("SELECT 1 FROM evidence.review_aspect_aggregate WHERE product_id=%s LIMIT 1",
                        (review.product_id,))
            if linked or cur.fetchone():
                raise ValueError("Existing aggregates require a coordinated rebuild before replacement")
            changes.append((review.document_id, desired))
        if not dry_run:
            for document_id, desired in changes:
                cur.execute("DELETE FROM evidence.review_aspect_observation WHERE document_id=%s "
                            "AND NOT (rule_id = ANY(%s::uuid[]))", (document_id, list(desired)))
                for obs in desired.values():
                    cur.execute("INSERT INTO evidence.review_aspect_observation "
                                "(document_id, rule_id, observation_text, direction, evidence_sentences) "
                                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (document_id,rule_id) DO UPDATE SET "
                                "observation_text=EXCLUDED.observation_text, direction=EXCLUDED.direction, "
                                "evidence_sentences=EXCLUDED.evidence_sentences",
                                (document_id, obs["rule_id"], obs["observation_text"], obs["direction"],
                                 Jsonb(obs["evidence_sentences"])))
    return {"documents": len(reviews), "observations": total,
            "changed_documents": len(changes), "dry_run": dry_run}
