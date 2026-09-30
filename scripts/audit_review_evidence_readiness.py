"""Audit review preview readiness without importing reviews or storing external text."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA = ROOT / "outputs/danawa_review_collection_20260927/review_metadata.jsonl"
DEFAULT_SYNTHETIC = ROOT / "outputs/review_pilot_20260925/recommendation_evidence_demo.json"
DEFAULT_POLICY = ROOT / "config/review_source_use_policy.json"
DEFAULT_OUTPUT = ROOT / "outputs/review_evidence_readiness_20260927/readiness.json"
FORBIDDEN_EXTERNAL_FIELDS = {"text", "body", "raw_text", "original_text", "text_or_excerpt", "username", "author_name", "author_ip"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(metadata: list[dict], synthetic_demo: dict, source_policy: dict) -> dict:
    sources = source_policy["sources"]
    metadata_by_status: Counter[str] = Counter()
    model_matched = 0
    products_with_metadata: set[str] = set()
    review_keys: set[tuple[str, str]] = set()
    for row in metadata:
        forbidden = FORBIDDEN_EXTERNAL_FIELDS.intersection(row)
        if forbidden:
            raise ValueError(f"external metadata contains original text or personal identifier fields: {sorted(forbidden)}")
        source = row["source"]
        if source not in sources:
            raise ValueError(f"unknown external review source: {source}")
        if sources[source]["status"] != "unreviewed" or sources[source]["permitted_use"] != "metadata_pilot_only":
            raise ValueError("this audit only handles unreviewed external metadata; approved summaries need a separate pipeline")
        key = (source, str(row["external_review_key"]))
        if key in review_keys:
            raise ValueError(f"duplicate external review key: {key}")
        review_keys.add(key)
        metadata_by_status[sources[source]["status"]] += 1
        model_matched += row.get("model_match_status") == "model_family_matched"
        products_with_metadata.add(row["product_key"])

    if synthetic_demo.get("corpus") != "synthetic" or synthetic_demo.get("usage") != "demo_only":
        raise ValueError("synthetic preview must be explicitly marked demo_only")
    cards = synthetic_demo["cards"]
    if any(card.get("production_ranking_eligible") is not False or
           card.get("observed_customer_review_count") is not None or
           card.get("observed_customer_rating") is not None or
           card.get("demo_display_eligible") is not True for card in cards):
        raise ValueError("synthetic cards must not claim observed reviews, ratings, or ranking eligibility")
    synthetic_source = sources["truefit_synthetic_reviews_pilot_v1"]
    if synthetic_source["status"] != "demo_only" or synthetic_source["permitted_use"] != "labeled_synthetic_preview_only":
        raise ValueError("synthetic source policy is not demo-only")
    if any(not str(card.get("display_label", "")).startswith("합성 리뷰 예시") for card in cards):
        raise ValueError("synthetic card label is missing")

    return {
        "status": "demo_preview_only_real_source_not_approved",
        "external_metadata_rows": len(metadata),
        "external_products_with_metadata": len(products_with_metadata),
        "external_model_matched_rows": model_matched,
        "external_source_status_counts": dict(sorted(metadata_by_status.items())),
        "approved_real_review_evidence_rows": 0,
        "approved_real_inventory_count": None,
        "synthetic_demo_products": len(cards),
        "synthetic_demo_examples": sum(len(card["review_examples"]) for card in cards),
        "synthetic_demo_artifact": "outputs/review_pilot_20260925/recommendation_evidence_demo.json",
        "allowed_now": ["labeled_synthetic_preview", "external_metadata_availability_audit"],
        "blocked_now": ["real_review_display", "real_review_count_allocation", "review_manipulation_signal", "production_ranking_from_synthetic"],
        "next_gates": ["review_source_usage_scope", "transient_general_experience_summary", "remaining_model_family_matches", "option_specific_claims_disabled_until_variant_mapping"],
        "external_original_text_stored": False,
        "database_import_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--synthetic-demo", type=Path, default=DEFAULT_SYNTHETIC)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = audit(
        read_jsonl(args.metadata),
        json.loads(args.synthetic_demo.read_text(encoding="utf-8")),
        json.loads(args.policy.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "external_metadata_rows": result["external_metadata_rows"],
                      "synthetic_demo_products": result["synthetic_demo_products"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
