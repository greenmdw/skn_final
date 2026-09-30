"""Separate exact metadata/body-hash duplicate candidates without raw text."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs/danawa_review_batch_final_20260927/review_metadata.jsonl"
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_batch_final_20260927/review_metadata_deduped.jsonl"
DEFAULT_REPORT = ROOT / "outputs/danawa_review_batch_final_20260927/dedupe_report.json"


def dedupe(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    possible_duplicates: list[dict] = []
    seen_ids: set[tuple[str, str]] = set()
    signatures: dict[tuple[str, str, int, str], str] = {}
    for row in rows:
        identity = (row["source"], str(row["external_review_key"]))
        if identity in seen_ids:
            raise ValueError(f"duplicate review ID in batch: {identity}")
        seen_ids.add(identity)
        signature = (row["product_key"], row["review_posted_date"], row["rating"], row["body_sha256"])
        if all(value is not None for value in signature):
            first_id = signatures.get(signature)
            if first_id is not None:
                possible_duplicates.append({
                    "product_key": row["product_key"],
                    "kept_review_id": first_id,
                    "possible_duplicate_review_id": row["external_review_key"],
                    "reason": "same_product_posted_date_rating_body_hash",
                })
                continue
            signatures[signature] = str(row["external_review_key"])
        kept.append(row)
    return kept, possible_duplicates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept, duplicates = dedupe(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8")
    counts = Counter(row["product_key"] for row in kept)
    report = {
        "input_unique_id_rows": len(rows),
        "after_exact_signature_dedupe": len(kept),
        "possible_duplicate_rows_separated": len(duplicates),
        "products_with_rows": len(counts),
        "max_rows_per_product": max(counts.values(), default=0),
        "usage_approved": False,
        "original_review_text_stored": False,
        "possible_duplicates": duplicates,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("input_unique_id_rows", "after_exact_signature_dedupe",
                                               "possible_duplicate_rows_separated", "products_with_rows")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
