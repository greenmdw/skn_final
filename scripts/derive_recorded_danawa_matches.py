"""Recheck product-title evidence already saved in the earlier Danawa count audit."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.collect_danawa_review_pilot import pcode_from_url
from scripts.plan_review_mix import product_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "outputs/review_counts_20260925/review_count_sources.json"
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_queue_20260927/recorded_title_matches.json"


def _normalize(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def model_tokens_match(sheet: str, model: str, source_title: str) -> bool:
    title = _normalize(source_title)
    if sheet == "CPU":
        sku_tokens = [part for part in re.findall(r"[A-Za-z0-9]+", model) if any(c.isdigit() for c in part)]
        return bool(sku_tokens) and max(sku_tokens, key=len).casefold() in title
    return _normalize(model) in title


def derive(records: list[dict], valid_keys: set[str]) -> tuple[dict[tuple[str, str], str], list[dict]]:
    matches: dict[tuple[str, str], str] = {}
    rejected: list[dict] = []
    for row in records:
        if row.get("status") != "matched":
            continue
        key = product_key(row)
        url = row.get("danawa_product_url") or ""
        title = row.get("danawa_product_name") or ""
        try:
            pcode = pcode_from_url(url)
        except ValueError:
            rejected.append({"product_key": key, "reason": "not_product_info_url", "source_url": url})
            continue
        if key not in valid_keys or not model_tokens_match(row["sheet"], row["model"], title):
            rejected.append({"product_key": key, "reason": "catalog_or_title_mismatch", "source_url": url})
            continue
        pair = (key, pcode)
        if pair in matches and matches[pair] != title:
            raise ValueError(f"conflicting titles for {pair}")
        matches[pair] = title
    return matches, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--count-plan", type=Path, default=ROOT / "outputs/review_counts_grouped_20260925/review_count_plan.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source_records = json.loads(args.sources.read_text(encoding="utf-8"))["records"]
    catalog_records = json.loads(args.count_plan.read_text(encoding="utf-8"))["records"]
    matches, rejected = derive(source_records, {product_key(row) for row in catalog_records})
    output = {
        "status": "recorded_title_token_verified_not_review_usage_approved",
        "matches": [{"product_key": key, "pcode": pcode, "source_title": title,
                     "verification_method": "prior_recorded_title_model_token"}
                    for (key, pcode), title in sorted(matches.items())],
        "rejected": rejected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"matches": len(matches), "rejected": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
