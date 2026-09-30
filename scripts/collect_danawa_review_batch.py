"""Bounded Danawa metadata batch for explicitly model-matched PC products.

Raw review bodies are processed in memory and discarded. Output is research
metadata with keyword topic mentions, not approved customer-review evidence.
Never run against unreviewed product candidates or import output into the DB.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from scripts.build_danawa_review_queue import DEFAULT_OUTPUT as DEFAULT_QUEUE
from scripts.collect_danawa_review_pilot import parse_review_page, request_review_page


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_batch_20260927"


def selected_products(queue: list[dict], max_products: int,
                      exclude_pcodes: set[str] | None = None, start_index: int = 0,
                      include_pcodes: set[str] | None = None,
                      match_basis: str | None = None) -> list[dict]:
    if not 1 <= max_products <= 25:
        raise ValueError("max_products must be 1..25")
    if start_index < 0:
        raise ValueError("start_index must be nonnegative")
    exclude_pcodes = exclude_pcodes or set()
    selected = []
    for row in queue:
        for candidate in row["danawa_candidates"]:
            if candidate["model_match_status"] != "model_family_matched":
                continue
            if match_basis is not None and candidate.get("match_basis") != match_basis:
                continue
            if candidate["pcode"] in exclude_pcodes:
                continue
            if include_pcodes is not None and candidate["pcode"] not in include_pcodes:
                continue
            selected.append({
                "sheet": row["sheet"], "product_key": row["product_key"],
                "pcode": candidate["pcode"], "product_url": candidate["product_url"],
                "match_status": "model_family_matched",
            })
    return selected[start_index:start_index + max_products]


def collect(products: list[dict], limit: int, max_pages: int, delay: float) -> tuple[list[dict], list[dict]]:
    if not 1 <= limit <= 10 or not 1 <= max_pages <= 15 or delay < 1.0:
        raise ValueError("batch limits: limit 1..10, pages 1..15, delay >= 1 second")
    observations: list[dict] = []
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    model_counts: Counter[str] = Counter()
    request_count = 0
    rate_limited = False
    for product in products:
        accepted = duplicates = invalid = pages_read = 0
        error = None
        for page in range(1, max_pages + 1):
            if model_counts[product["product_key"]] >= 100:
                break
            if request_count:
                time.sleep(delay)
            request_count += 1
            try:
                html = request_review_page(product["pcode"], page, limit)
                rows, rejected = parse_review_page(html, product, page)
            except HTTPError as exc:
                error = f"HTTP {exc.code}"
                if exc.code in (403, 429):
                    rate_limited = True
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
            pages_read += 1
            invalid += rejected
            for row in rows:
                identity = (row["source"], row["external_review_key"])
                if identity in seen:
                    duplicates += 1
                    continue
                if model_counts[product["product_key"]] >= 100:
                    break
                seen.add(identity)
                observations.append(row)
                accepted += 1
                model_counts[product["product_key"]] += 1
            if len(rows) < limit or model_counts[product["product_key"]] >= 100:
                break
        results.append({**product, "pages_read": pages_read, "review_rows": accepted,
                        "duplicates": duplicates, "invalid_cards": invalid, "error": error})
        if rate_limited:
            break
    return observations, results


def write_results(output_dir: Path, observations: list[dict], results: list[dict], selected_count: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "review_metadata.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations), encoding="utf-8")
    report = {
        "status": "research_metadata_only_not_import_ready",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "products_selected": selected_count,
        "products_checked": len(results),
        "metadata_rows": len(observations),
        "pages_read": sum(row["pages_read"] for row in results),
        "errors": sum(bool(row["error"]) for row in results),
        "stopped_on_403_or_429": any(row["error"] in ("HTTP 403", "HTTP 429") for row in results),
        "contains_original_review_text": False,
        "contains_author_name_or_ip": False,
        "usage_approved": False,
        "real_inventory_approved": False,
        "products": results,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--exclude-report", type=Path, action="append", default=[])
    parser.add_argument("--only-full-page-report", type=Path, action="append", default=[])
    parser.add_argument("--pcode", action="append", default=[], help="Restrict to these verified product codes")
    parser.add_argument("--match-basis", choices=("curated", "recorded_title_token", "live_page_title",
                                                  "search_product_title"))
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    queue = [json.loads(line) for line in args.queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    excluded_pcodes = {row["pcode"] for path in args.exclude_report
                       for row in json.loads(path.read_text(encoding="utf-8"))["products"]}
    include_pcodes = None if not args.only_full_page_report else {
        row["pcode"] for path in args.only_full_page_report
        for row in json.loads(path.read_text(encoding="utf-8"))["products"]
        if row["review_rows"] == args.limit and row["pages_read"] == 1 and not row["error"]
    }
    if args.pcode:
        include_pcodes = set(args.pcode) if include_pcodes is None else include_pcodes & set(args.pcode)
    products = selected_products(queue, args.max_products, excluded_pcodes, args.start_index,
                                 include_pcodes, args.match_basis)
    observations, results = collect(products, args.limit, args.max_pages, args.delay)
    report = write_results(args.output_dir, observations, results, len(products))
    print(json.dumps({key: report[key] for key in ("products_selected", "products_checked", "metadata_rows",
                                                    "pages_read", "errors", "stopped_on_403_or_429")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
