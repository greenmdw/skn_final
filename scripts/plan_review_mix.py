"""Plan a per-product 50:50 real/synthetic review mix without inventing real reviews.

The existing grouped count plan is a popularity-shaped *target*, not a source of
real review records. An optional, separately verified inventory is required
before this script assigns any reviews to a product.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COUNT_PLAN = ROOT / "outputs/review_counts_grouped_20260925/review_count_plan.json"
SHEET_TYPES = {
    "CPU": "cpu", "MainBoard": "motherboard", "RAM": "ram", "GPU": "gpu",
    "SSD": "ssd", "PSU": "psu", "Case": "case", "Cooler": "cooler",
}
INVENTORY_FIELDS = {
    "product_key", "available_real_count", "source_ref", "review_ids_verified", "usage_approved",
}


def product_key(row: dict) -> str:
    """Match the PC catalog's product_type:brand:model key convention."""
    return f"{SHEET_TYPES[row['sheet']]}:{row['manufacturer']}:{row['model']}".lower().replace(" ", "-")


def load_inventory(path: Path, valid_keys: set[str]) -> dict[str, int]:
    """Read audited counts, never Danawa's displayed aggregate review counts."""
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not INVENTORY_FIELDS.issubset(reader.fieldnames):
            raise ValueError(f"inventory columns required: {', '.join(sorted(INVENTORY_FIELDS))}")
        for line_no, row in enumerate(reader, 2):
            key = (row.get("product_key") or "").strip()
            if key not in valid_keys:
                raise ValueError(f"line {line_no}: unknown product_key {key!r}")
            if key in counts:
                raise ValueError(f"line {line_no}: duplicate product_key {key!r}")
            try:
                count = int(row["available_real_count"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"line {line_no}: invalid real review count") from exc
            if count < 0:
                raise ValueError(f"line {line_no}: negative real review count")
            if (row.get("review_ids_verified") or "").strip().lower() != "yes":
                raise ValueError(f"line {line_no}: individual review IDs not verified")
            if (row.get("usage_approved") or "").strip().lower() != "yes":
                raise ValueError(f"line {line_no}: use of this source not approved")
            if count and not (row.get("source_ref") or "").strip():
                raise ValueError(f"line {line_no}: missing source_ref")
            counts[key] = count
    return counts


def build_plan(count_plan: dict, inventory: dict[str, int] | None = None) -> dict:
    """Cap each product at 100; exact parity may reduce the popularity target."""
    rows = count_plan["records"]
    keys = [product_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("count plan contains duplicate catalog product keys")
    if inventory is not None and set(inventory) - set(keys):
        raise ValueError("inventory contains unknown catalog product keys")

    result = []
    for row, key in zip(rows, keys):
        original_target = row["planned_synthetic_reviews"]
        if type(original_target) is not int or not 0 <= original_target <= 100:
            raise ValueError(f"invalid target for {key}")
        # The old synthetic-only allocation is now the approximate *total*
        # target. Round odd targets up to allow an exact 1:1 split.
        target = min(100, original_target + original_target % 2)
        available = None if inventory is None else inventory.get(key)
        if available is not None and (type(available) is not int or available < 0):
            raise ValueError(f"invalid available real review count for {key}")
        pair_count = None if available is None else min(target // 2, available)
        result.append({
            "product_key": key,
            "sheet": row["sheet"],
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "old_synthetic_only_target": original_target,
            "target_total_even": target,
            "real_reviews_needed_for_target": target // 2,
            "verified_real_available": available,
            "allocated_real": pair_count,
            "allocated_synthetic": pair_count,
            "allocated_total": None if pair_count is None else 2 * pair_count,
            "status": "awaiting_real_inventory" if available is None else "allocated",
        })

    statuses = Counter(row["status"] for row in result)
    return {
        "policy": {
            "per_product_max_total": 100,
            "real_to_synthetic": "1:1",
            "old_count_interpretation": "approximate_total_target_not_real_review_count",
            "missing_inventory": "unknown_not_zero",
            "synthetic_excluded_from": [
                "real_review_count", "real_rating", "relation_behavior_signals", "production_ranking"
            ],
        },
        "summary": {
            "products": len(result),
            "pending_products": statuses["awaiting_real_inventory"],
            "allocated_products": statuses["allocated"],
            "allocated_real": sum(row["allocated_real"] or 0 for row in result),
            "allocated_synthetic": sum(row["allocated_synthetic"] or 0 for row in result),
        },
        "records": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-plan", type=Path, default=DEFAULT_COUNT_PLAN)
    parser.add_argument("--real-inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count_plan = json.loads(args.count_plan.read_text(encoding="utf-8"))
    valid_keys = {product_key(row) for row in count_plan["records"]}
    inventory = load_inventory(args.real_inventory, valid_keys) if args.real_inventory else None
    plan = build_plan(count_plan, inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
