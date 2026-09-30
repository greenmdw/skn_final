"""Build the 50:50 planner input from approved, non-original review summaries.

Input is a JSONL of derived summaries, never raw external review text. This
script checks declared source permission and record-level review before it
counts anything. It does not import to the DB or approve a source itself.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from scripts.plan_review_mix import DEFAULT_COUNT_PLAN, product_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config/review_source_use_policy.json"
RAW_FIELDS = {"text", "body", "raw_text", "original_text", "text_or_excerpt", "username", "author_name", "author_ip"}
INVENTORY_COLUMNS = ("product_key", "available_real_count", "source_ref", "review_ids_verified", "usage_approved")


def _valid_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.hostname.endswith(".invalid")


def prepare_inventory(rows: list[dict], policy: dict, valid_keys: set[str]) -> tuple[list[dict], dict]:
    by_product: dict[str, list[dict]] = defaultdict(list)
    seen_ids: set[tuple[str, str]] = set()
    seen_body_signatures: set[tuple[str, str, str, int, str]] = set()
    for index, row in enumerate(rows, 1):
        if RAW_FIELDS.intersection(row):
            raise ValueError(f"row {index}: raw review or personal identifier field present")
        if row.get("is_synthetic") is not False:
            raise ValueError(f"row {index}: only real reviews can enter real inventory")
        source = row.get("source")
        source_rule = policy.get("sources", {}).get(source)
        if not source_rule or source_rule.get("status") != "approved" or \
                source_rule.get("permitted_use") != "derived_summary_and_count" or \
                not source_rule.get("approval_reference"):
            raise ValueError(f"row {index}: source use is not explicitly approved: {source!r}")
        key = row.get("product_key")
        if key not in valid_keys or row.get("model_match_status") != "model_family_matched":
            raise ValueError(f"row {index}: catalog model match is not approved")
        if row.get("usage_status") != "approved" or row.get("summary_status") != "approved":
            raise ValueError(f"row {index}: record or derived summary is not reviewed")
        review_id = str(row.get("external_review_key") or "")
        if not review_id:
            raise ValueError(f"row {index}: missing external review ID")
        identity = (source, review_id)
        if identity in seen_ids:
            raise ValueError(f"row {index}: duplicate source/review ID")
        seen_ids.add(identity)
        if not _valid_url(row.get("original_url")):
            raise ValueError(f"row {index}: missing review-specific HTTPS source URL")
        if not isinstance(row.get("summary"), str) or not row["summary"].strip():
            raise ValueError(f"row {index}: missing derived summary")
        if type(row.get("rating")) is not int or not 1 <= row["rating"] <= 5:
            raise ValueError(f"row {index}: invalid observed rating")
        body_hash = row.get("text_hash")
        if not isinstance(body_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", body_hash):
            raise ValueError(f"row {index}: missing original-body SHA-256")
        if type(row.get("body_chars")) is not int or row["body_chars"] <= 0:
            raise ValueError(f"row {index}: missing original body length")
        try:
            posted_date = date.fromisoformat(row["review_posted_date"]).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"row {index}: missing or invalid original posted date") from exc
        signature = (source, key, posted_date, row["rating"], body_hash)
        if signature in seen_body_signatures:
            raise ValueError(f"row {index}: duplicate body/date/rating signature")
        seen_body_signatures.add(signature)
        by_product[key].append(row)

    inventory = [{
        "product_key": key,
        "available_real_count": len(product_rows),
        "source_ref": ";".join(sorted({r["source"] for r in product_rows})),
        "review_ids_verified": "yes",
        "usage_approved": "yes",
    } for key, product_rows in sorted(by_product.items())]
    report = {
        "status": "approved_derived_summary_inventory" if inventory else "no_approved_real_reviews_submitted",
        "input_rows": len(rows),
        "products_with_approved_real_reviews": len(inventory),
        "approved_real_reviews": sum(int(row["available_real_count"]) for row in inventory),
        "original_review_text_stored": False,
        "database_import_performed": False,
        "note": "source approval references and record-level approvals require human verification",
    }
    return inventory, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-summaries", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--count-plan", type=Path, default=DEFAULT_COUNT_PLAN)
    parser.add_argument("--inventory-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.approved_summaries.read_text(encoding="utf-8").splitlines() if line.strip()]
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    plan = json.loads(args.count_plan.read_text(encoding="utf-8"))
    valid_keys = {product_key(row) for row in plan["records"]}
    inventory, report = prepare_inventory(rows, policy, valid_keys)
    args.inventory_output.parent.mkdir(parents=True, exist_ok=True)
    with args.inventory_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(inventory)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
