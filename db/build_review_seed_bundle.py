"""Build the private, reproducible setup bundle from finalized review artifacts.

The generated JSON contains actual review text and stays outside Git. Run this in
the curated workspace, then securely copy data/review_seed to test/deployment hosts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> str:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path, target: Path) -> dict:
    audit = _read(source / "final_readback_audit.json")
    accounting = _read(source / "effective_all_record_accounting.json")
    effective_ids = {
        row["document_id"] for row in accounting["rows"]
        if row.get("status") in {"matched", "matched_supplemental_literal_alias"}
    }
    main = _read(source / "source_manifest.json")
    supplemental = _read(source / "supplement_literal_regional_alias/source_manifest.json")
    catalog = {row["id"]: row for row in _read(source / "catalog.json")}
    documents_by_id = {}
    for manifest in (main, supplemental):
        for row in manifest["rows"]:
            if row.get("document_id") not in effective_ids or row.get("status") != "matched":
                continue
            doc = row["document"]
            product = catalog[doc["product_id"]]
            documents_by_id[doc["id"]] = {
                "document_id": doc["id"], "product_id": doc["product_id"],
                "part_type": row["part_type"], "product_name": product["name"],
                "product_brand": product["brand"], "product_model": product["model"],
                "is_synthetic": False, "body": doc["body"],
                "source_code": doc["source_code"], "posted_at": doc.get("posted_at"),
            }
    excluded = sorted(audit["excluded_documents_absent"])
    if set(documents_by_id) & set(excluded):
        raise ValueError("A quarantined review source is in the effective document set")
    if len(documents_by_id) != audit["db_counts"]["evidence.review_document"]:
        raise ValueError("Effective document count differs from finalized DB audit")

    documents = sorted(documents_by_id.values(), key=lambda row: row["document_id"])
    rules = _read(source / "rules.json")
    canonical = [
        row for row in _read(source / "canonical_results.json")
        if row["review"]["document_id"] in documents_by_id
    ]
    drafts = [
        row for row in _read(source / "consolidated_observation_drafts.json")
        if row["document_id"] in documents_by_id
    ]
    if len(rules) != audit["db_counts"]["evidence.review_aspect_rule"]:
        raise ValueError("Rule count differs from finalized DB audit")
    if len(drafts) != audit["canonical_observation_drafts"]:
        raise ValueError("Observation count differs from finalized audit")
    canonical_observation_count = sum(len(row["result"]["observations"]) for row in canonical)
    if canonical_observation_count != len(drafts):
        raise ValueError("Canonical results and consolidated observations disagree")

    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, value in (("documents.json", documents), ("rules.json", rules),
                        ("canonical_results.json", canonical),
                        ("consolidated_observation_drafts.json", drafts)):
        hashes[name] = _write(target / name, value)
    version_set = {row["analysis_version"] for row in rules}
    if len(version_set) != 1:
        raise ValueError("Bundle must contain exactly one registered analysis version")
    manifest = {
        "bundle_version": "review-seed-v1", "database_import_allowed": True,
        "analysis_version": next(iter(version_set)), "documents": len(documents),
        "rules": len(rules), "observations": len(drafts),
        "excluded_document_ids": excluded, "sha256": hashes,
    }
    _write(target / "bundle_manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path("outputs/review_full_corpus/20261002_authorized"))
    parser.add_argument("--target", type=Path, default=Path("data/review_seed"))
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.target), ensure_ascii=False, sort_keys=True))
