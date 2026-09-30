"""Build a clearly non-operational 1:1 scenario from unapproved research counts.

This does not create synthetic review texts, approve external reviews, or turn
unmatched products into verified zero-review products.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.plan_review_mix import ROOT


DEFAULT_COVERAGE = ROOT / "outputs/review_coverage_20260928/coverage.csv"
DEFAULT_OUTPUT = ROOT / "outputs/review_research_mix_20260928/plan.json"


def build_research_scenario(coverage: list[dict]) -> dict:
    rows = []
    keys: set[str] = set()
    for row in coverage:
        key = row["product_key"]
        if key in keys:
            raise ValueError(f"duplicate product key: {key}")
        keys.add(key)
        if row["approved_real_available"] != "unknown" or row["review_mix_status"] != "not_allocated":
            raise ValueError("input must be unapproved and unallocated research coverage")
        target = int(row["target_real_reviews"])
        observed = int(row["research_metadata_count"])
        total_target = int(row["target_total_even"])
        if target < 0 or observed < 0 or total_target != target * 2 or total_target > 100:
            raise ValueError(f"invalid target or research count: {key}")
        match = row["model_match_status"]
        if match not in ("matched", "unmatched") or (observed and match != "matched"):
            raise ValueError(f"research metadata lacks confirmed model: {key}")
        pair_count = min(target, observed)
        state = ("unmatched_model" if match == "unmatched" else
                 "matched_no_review_observed" if observed == 0 else "research_metadata_observed")
        rows.append({
            "product_key": key,
            "sheet": row["sheet"],
            "model": row["model"],
            "target_real_reviews": target,
            "research_metadata_count": observed,
            "research_scenario_real_count": pair_count,
            "research_scenario_synthetic_count": pair_count,
            "research_scenario_total": pair_count * 2,
            "research_state": state,
            "approved_real_available": None,
            "actual_synthetic_reviews_generated": 0,
            "production_allocation": None,
        })
    summary = {
        "products": len(rows),
        "unmatched_products": sum(row["research_state"] == "unmatched_model" for row in rows),
        "matched_without_observed_review": sum(
            row["research_state"] == "matched_no_review_observed" for row in rows),
        "products_with_research_metadata": sum(
            row["research_state"] == "research_metadata_observed" for row in rows),
        "research_scenario_real_count": sum(row["research_scenario_real_count"] for row in rows),
        "research_scenario_synthetic_count": sum(row["research_scenario_synthetic_count"] for row in rows),
        "research_scenario_total": sum(row["research_scenario_total"] for row in rows),
        "approved_real_count": None,
        "actual_synthetic_reviews_generated": 0,
        "production_allocation": None,
    }
    return {
        "status": "research_count_scenario_only_not_review_data",
        "interpretation": "A 1:1 numerical ceiling if every matched metadata row were later approved; not actual real or synthetic reviews.",
        "source_scope": "danawa_company_product_review_metadata_pilot",
        "summary": summary,
        "records": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with args.coverage.open(encoding="utf-8-sig", newline="") as handle:
        result = build_research_scenario(list(csv.DictReader(handle)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
