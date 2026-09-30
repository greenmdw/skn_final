"""Compare PC review targets with research metadata without allocating reviews.

Danawa metadata is unapproved research evidence. Counts in this report are
potential matching leads, never an approved real-review inventory.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from scripts.plan_review_mix import ROOT


DEFAULT_PLAN = ROOT / "outputs/review_mix_20260927/plan.json"
DEFAULT_QUEUE = ROOT / "outputs/danawa_review_queue_20260927/queue.jsonl"
DEFAULT_METADATA = ROOT / "outputs/danawa_review_collection_20260927/review_metadata.jsonl"
DEFAULT_CSV = ROOT / "outputs/review_coverage_20260928/coverage.csv"
DEFAULT_REPORT = ROOT / "outputs/review_coverage_20260928/report.json"
FIELDS = (
    "product_key", "sheet", "manufacturer", "model", "target_total_even",
    "target_real_reviews", "model_match_status", "research_metadata_count",
    "research_count_shortfall_if_approved", "approved_real_available",
    "review_mix_status",
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit_coverage(plan: dict, queue: list[dict], metadata: list[dict]) -> tuple[list[dict], dict]:
    records = plan["records"]
    planned_keys = [row["product_key"] for row in records]
    if len(planned_keys) != len(set(planned_keys)):
        raise ValueError("duplicate product key in review mix plan")
    queued = {row["product_key"]: row for row in queue}
    if len(queued) != len(queue) or set(queued) != set(planned_keys):
        raise ValueError("queue and review mix plan product keys differ")

    research_counts: Counter[str] = Counter()
    review_ids: set[tuple[str, str]] = set()
    for row in metadata:
        key = row["product_key"]
        if key not in queued:
            raise ValueError(f"metadata has unknown product key: {key}")
        if row.get("usage_status") == "approved":
            raise ValueError("approved reviews require the separate inventory pipeline")
        if row.get("model_match_status") != "model_family_matched":
            raise ValueError(f"metadata model is not matched: {key}")
        external_key = (row["source"], str(row["external_review_key"]))
        if external_key in review_ids:
            raise ValueError(f"duplicate external review ID: {external_key}")
        review_ids.add(external_key)
        research_counts[key] += 1

    result = []
    for row in records:
        key = row["product_key"]
        candidates = queued[key]["danawa_candidates"]
        matched = any(candidate["model_match_status"] == "model_family_matched"
                      for candidate in candidates)
        count = research_counts[key]
        if count and not matched:
            raise ValueError(f"metadata attached to unmatched product: {key}")
        if row.get("verified_real_available") is not None or row.get("allocated_real") is not None:
            raise ValueError("coverage audit requires an unallocated review mix plan")
        needed = row["real_reviews_needed_for_target"]
        result.append({
            "product_key": key,
            "sheet": row["sheet"],
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "target_total_even": row["target_total_even"],
            "target_real_reviews": needed,
            "model_match_status": "matched" if matched else "unmatched",
            "research_metadata_count": count,
            "research_count_shortfall_if_approved": max(0, needed - count),
            "approved_real_available": "unknown",
            "review_mix_status": "not_allocated",
        })

    target = sum(row["target_real_reviews"] for row in result)
    potential = sum(min(row["target_real_reviews"], row["research_metadata_count"])
                    for row in result)
    summary = {
        "status": "research_coverage_only_not_approved_inventory",
        "products": len(result),
        "model_matched_products": sum(row["model_match_status"] == "matched" for row in result),
        "products_with_research_metadata": sum(row["research_metadata_count"] > 0 for row in result),
        "products_without_research_metadata": sum(row["research_metadata_count"] == 0 for row in result),
        "products_meeting_target_by_research_count_only": sum(
            row["research_metadata_count"] >= row["target_real_reviews"] for row in result),
        "target_real_reviews_total": target,
        "research_metadata_rows": sum(research_counts.values()),
        "research_count_within_product_targets": potential,
        "research_count_shortfall_if_approved": target - potential,
        "approved_real_inventory_rows": None,
        "approved_real_review_count": None,
        "allocated_reviews": None,
        "note": "Research counts do not establish source rights, SKU identity, review summary, or usable real reviews.",
    }
    return result, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    rows, report = audit_coverage(
        json.loads(args.plan.read_text(encoding="utf-8")),
        read_jsonl(args.queue), read_jsonl(args.metadata),
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
