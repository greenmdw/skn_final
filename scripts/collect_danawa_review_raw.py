"""Re-fetch matched Danawa reviews into a local, unapproved raw-text JSON file.

This does not alter the metadata-only collector or import into the DB. Product
matches are model-family matches, not SKU proofs. Output is ignored by Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from scripts.collect_danawa_review_pilot import ReviewCardParser, request_review_page


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA = ROOT / "outputs/danawa_review_collection_20260927/review_metadata.jsonl"
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_raw_20260928"


def load_targets(path: Path) -> dict[tuple[str, int], list[dict]]:
    targets: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["source"] != "danawa_company_product_review":
            raise ValueError("unexpected review source")
        if row["model_match_status"] != "model_family_matched":
            raise ValueError("unverified model-family match")
        targets[(str(row["source_pcode"]), int(row["page"]))].append(row)
    return dict(targets)


def extract_page(html: str, targets: list[dict], collected_at: str) -> tuple[list[dict], list[str]]:
    parser = ReviewCardParser()
    parser.feed(html)
    cards = {card.review_id: card for card in parser.cards if card.review_id}
    found: list[dict] = []
    missing: list[str] = []
    for row in targets:
        review_id = str(row["external_review_key"])
        card = cards.get(review_id)
        if card is None:
            missing.append(review_id)
            continue
        # Keep wording, normalize HTML whitespace exactly as in the metadata hash.
        body = " ".join(" ".join(card.body_parts).split())
        if not body:
            missing.append(review_id)
            continue
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        found.append({
            **row,
            "text": body,
            "text_fidelity": "original_wording_html_whitespace_normalized",
            "text_sha256_current": digest,
            "text_matches_metadata_hash": digest == row["body_sha256"],
            "raw_collected_at_utc": collected_at,
            "usage_status": "unreviewed_local_raw_research_only",
        })
    return found, missing


def collect_batch(targets: dict[tuple[str, int], list[dict]], existing: dict,
                  max_requests: int, delay: float, fetch=request_review_page,
                  sleep=time.sleep) -> dict:
    if not 1 <= max_requests <= 100 or delay < 1.0:
        raise ValueError("max_requests must be 1..100 and delay >= 1 second")
    result = {
        "schema_version": 1,
        "status": "unreviewed_local_raw_research_only",
        "source": "danawa_company_product_review",
        "contains_original_review_text": True,
        "usage_approved": False,
        "sku_matches_approved": False,
        "records": list(existing.get("records", [])),
        "completed_pages": list(existing.get("completed_pages", [])),
        "failed_pages": list(existing.get("failed_pages", [])),
        "missing_review_ids": list(existing.get("missing_review_ids", [])),
        "stopped_on_rate_limit": bool(existing.get("stopped_on_rate_limit", False)),
    }
    done = {tuple(page) for page in result["completed_pages"]}
    failed = {(row["pcode"], row["page"]) for row in result["failed_pages"]}
    seen = {(row["source"], str(row["external_review_key"])) for row in result["records"]}
    requests = 0
    for pcode, page in sorted(targets):
        if result["stopped_on_rate_limit"]:
            break
        if (pcode, page) in done or (pcode, page) in failed:
            continue
        if requests >= max_requests:
            break
        if requests:
            sleep(delay)
        requests += 1
        try:
            html = fetch(pcode, page, 10)
            collected_at = datetime.now(timezone.utc).isoformat()
            rows, missing = extract_page(html, targets[(pcode, page)], collected_at)
        except HTTPError as exc:
            result["failed_pages"].append({"pcode": pcode, "page": page, "error": f"HTTP {exc.code}"})
            if exc.code in (403, 429):
                result["stopped_on_rate_limit"] = True
                break
            continue
        except Exception as exc:
            result["failed_pages"].append({"pcode": pcode, "page": page,
                                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        for row in rows:
            identity = (row["source"], str(row["external_review_key"]))
            if identity not in seen:
                result["records"].append(row)
                seen.add(identity)
        result["missing_review_ids"].extend({"pcode": pcode, "page": page, "review_id": key}
                                            for key in missing)
        result["completed_pages"].append([pcode, page])
    result["last_batch_requests"] = requests
    result["target_pages"] = len(targets)
    result["target_review_rows"] = sum(map(len, targets.values()))
    return result


def write_results(output_dir: Path, result: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reviews.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    report = {
        "status": result["status"],
        "target_pages": result["target_pages"],
        "completed_pages": len(result["completed_pages"]),
        "failed_pages": len(result["failed_pages"]),
        "target_review_rows": result["target_review_rows"],
        "raw_review_rows": len(result["records"]),
        "exact_hash_matches": sum(row["text_matches_metadata_hash"] for row in result["records"]),
        "changed_text_rows": sum(not row["text_matches_metadata_hash"] for row in result["records"]),
        "missing_review_ids": len(result["missing_review_ids"]),
        "products_with_raw_text": len({row["product_key"] for row in result["records"]}),
        "last_batch_requests": result["last_batch_requests"],
        "usage_approved": False,
        "db_imported": False,
        "stopped_on_rate_limit": result["stopped_on_rate_limit"],
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-requests", type=int, default=50)
    parser.add_argument("--delay", type=float, default=1.2)
    args = parser.parse_args()
    targets = load_targets(args.metadata)
    output_path = args.output_dir / "reviews.json"
    existing = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
    result = collect_batch(targets, existing, args.max_requests, args.delay)
    report = write_results(args.output_dir, result)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
