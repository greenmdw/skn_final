import hashlib
import runpy
import json
import os
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/review_seed"
read_bundle = runpy.run_path(str(ROOT / "db/seed_review_corpus.py"))["read_bundle"]
apply_all = runpy.run_path(str(ROOT / "db/import_review_corpus_all_observations.py"))["apply_all"]
ARTIFACTS = (
    "documents.json", "rules.json", "canonical_results.json",
    "consolidated_observation_drafts.json",
)


def test_private_bundle_is_complete_hashed_and_excludes_quarantines():
    _root, manifest, documents, rules, canonical, drafts = read_bundle(BUNDLE)
    excluded = set(manifest["excluded_document_ids"])
    document_ids = {row["document_id"] for row in documents}
    assert manifest["database_import_allowed"] is True
    assert len(documents) == 5653
    assert len(rules) == 102
    assert len(drafts) == 3676
    assert not excluded & document_ids
    assert not excluded & {row["review"]["document_id"] for row in canonical}
    assert not excluded & {row["document_id"] for row in drafts}


def test_bundle_loader_rejects_missing_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="Required private review seed bundle"):
        read_bundle(tmp_path)


def test_bundle_loader_rejects_changed_artifact_hash(tmp_path):
    for name in ARTIFACTS:
        (tmp_path / name).write_text("[]", encoding="utf-8")
    manifest = {
        "bundle_version": "review-seed-v1",
        "database_import_allowed": True,
        "analysis_version": "review-aspect-v6-prod-20261002",
        "documents": 0,
        "rules": 0,
        "observations": 0,
        "excluded_document_ids": [],
        "sha256": {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                   for name in ARTIFACTS},
    }
    manifest["sha256"]["rules.json"] = "0" * 64
    (tmp_path / "bundle_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing or changed review seed artifact: rules.json"):
        read_bundle(tmp_path)


@pytest.mark.db
def test_observation_seed_exact_reimport_and_conflict_preserve_existing_rows():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        before_observations = conn.execute(
            "SELECT id::text,document_id::text,rule_id::text,observation_text,direction,evidence_sentences "
            "FROM evidence.review_aspect_observation ORDER BY id"
        ).fetchall()
        before_aggregates = conn.execute(
            "SELECT id::text,product_id::text,rule_id::text,p,n,mixed,k "
            "FROM evidence.review_aspect_aggregate ORDER BY id"
        ).fetchall()
        before_members = conn.execute(
            "SELECT aggregate_id::text,observation_id::text "
            "FROM evidence.review_aspect_aggregate_member ORDER BY aggregate_id,observation_id"
        ).fetchall()

        result = apply_all(conn, BUNDLE, apply=True)
        assert result["inserted"] == 0
        assert result["existing_preserved"] == len(before_observations) == 3676
        assert conn.execute(
            "SELECT id::text,document_id::text,rule_id::text,observation_text,direction,evidence_sentences "
            "FROM evidence.review_aspect_observation ORDER BY id"
        ).fetchall() == before_observations
        assert conn.execute(
            "SELECT id::text,product_id::text,rule_id::text,p,n,mixed,k "
            "FROM evidence.review_aspect_aggregate ORDER BY id"
        ).fetchall() == before_aggregates
        assert conn.execute(
            "SELECT aggregate_id::text,observation_id::text "
            "FROM evidence.review_aspect_aggregate_member ORDER BY aggregate_id,observation_id"
        ).fetchall() == before_members

        first = before_observations[0]
        replacement = "negative" if first[4] != "negative" else "positive"
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE evidence.review_aspect_observation SET direction=%s WHERE id=%s",
            (replacement, first[0]),
        )
        with pytest.raises(ValueError, match="Existing observation differs"):
            apply_all(conn, BUNDLE, apply=True)
        assert conn.execute(
            "SELECT direction FROM evidence.review_aspect_observation WHERE id=%s", (first[0],)
        ).fetchone()[0] == replacement
        assert conn.execute(
            "SELECT id::text,product_id::text,rule_id::text,p,n,mixed,k "
            "FROM evidence.review_aspect_aggregate ORDER BY id"
        ).fetchall() == before_aggregates
        conn.rollback()
