"""Merge bounded Danawa metadata batches without approving or importing reviews."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.dedupe_danawa_review_metadata import dedupe


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_collection_20260927"
FORBIDDEN = {"text", "body", "raw_text", "original_text", "text_or_excerpt", "username", "author_name", "author_ip"}


def merge(batch_rows: list[list[dict]]) -> tuple[list[dict], dict]:
    unique: dict[tuple[str, str], dict] = {}
    input_rows = 0
    for rows in batch_rows:
        for row in rows:
            input_rows += 1
            if FORBIDDEN.intersection(row):
                raise ValueError("external original text or personal identifier field in input")
            identity = (row["source"], str(row["external_review_key"]))
            previous = unique.get(identity)
            if previous is not None:
                fields = ("product_key", "review_posted_date", "rating", "body_sha256")
                if any(previous.get(field) != row.get(field) for field in fields):
                    raise ValueError(f"same review ID has conflicting metadata: {identity}")
                continue
            unique[identity] = row
    signature_unique, possible_duplicates = dedupe(list(unique.values()))
    kept: list[dict] = []
    counts: Counter[str] = Counter()
    over_cap = 0
    for row in signature_unique:
        key = row["product_key"]
        if counts[key] >= 100:
            over_cap += 1
            continue
        counts[key] += 1
        kept.append(row)
    report = {
        "status": "research_metadata_only_not_import_ready",
        "input_rows_with_repeat_fetches": input_rows,
        "unique_external_review_ids": len(unique),
        "possible_body_signature_duplicates_separated": len(possible_duplicates),
        "over_100_per_model_separated": over_cap,
        "final_metadata_rows": len(kept),
        "models_with_metadata": len(counts),
        "models_at_100_metadata_rows": sum(count == 100 for count in counts.values()),
        "rows_with_posted_date": sum(bool(row.get("review_posted_date")) for row in kept),
        "rows_with_rating": sum(type(row.get("rating")) is int for row in kept),
        "rows_with_keyword_theme_mentions": sum(bool(row.get("theme_mentions")) for row in kept),
        "counts_by_product_key": dict(sorted(counts.items())),
        "possible_duplicates": possible_duplicates,
        "usage_approved": False,
        "approved_real_inventory_count": None,
        "contains_original_review_text": False,
        "database_import_performed": False,
    }
    return kept, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", default=[],
                        help="Repeat for each batch review_metadata.jsonl; put deep batches before shallow ones")
    parser.add_argument("--input-report", type=Path,
                        help="Reuse the original input paths from a previous merge report")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    previous_paths = [] if args.input_report is None else [
        Path(path) for path in json.loads(args.input_report.read_text(encoding="utf-8"))["inputs"]]
    paths = previous_paths + args.input
    if not paths:
        parser.error("at least one --input or --input-report is required")
    inputs = [[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
              for path in paths]
    kept, report = merge(inputs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "review_metadata.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8")
    report["inputs"] = [str(path) for path in paths]
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("unique_external_review_ids", "final_metadata_rows",
                                                    "models_with_metadata", "over_100_per_model_separated")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
