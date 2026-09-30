"""Prepare an offline Danawa product-review queue from already recorded URLs.

This script performs no network requests and does not approve review usage or
turn displayed family counts into verified individual reviews.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.collect_danawa_review_pilot import DEFAULT_MATCHES, load_model_matches, pcode_from_url
from scripts.derive_recorded_danawa_matches import DEFAULT_OUTPUT as DEFAULT_RECORDED_MATCHES
from scripts.plan_review_mix import DEFAULT_COUNT_PLAN, product_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_queue_20260927/queue.jsonl"
DEFAULT_REPORT = ROOT / "outputs/danawa_review_queue_20260927/report.json"
DEFAULT_LIVE_MATCHES = ROOT / "outputs/danawa_review_queue_20260927/live_verified_matches.json"
DEFAULT_SEARCH_MATCHES = ROOT / "outputs/danawa_review_queue_20260927/search_verified_matches.json"
DEFAULT_SEARCH_CANDIDATES = ROOT / "outputs/danawa_review_queue_20260927/search_candidates.jsonl"


def validate_search_matches(matches: list[dict], candidate_rows: list[dict]) -> set[tuple[str, str]]:
    candidates = {(row["key"], pcode_from_url(hit["url"])):
                  hit["title"].removesuffix(" : 다나와 가격비교")
                  for row in candidate_rows for hit in row["hits"]}
    verified: set[tuple[str, str]] = set()
    for row in matches:
        pair = (row["product_key"], row["pcode"])
        if pair in verified or not row.get("source_title") or candidates.get(pair) != row["source_title"]:
            raise ValueError(f"search match lacks recorded title evidence: {pair}")
        verified.add(pair)
    return verified


def build_queue(count_plan: dict, curated_matches: set[tuple[str, str]],
                recorded_matches: set[tuple[str, str]] | None = None,
                live_matches: set[tuple[str, str]] | None = None,
                search_matches: set[tuple[str, str]] | None = None) -> tuple[list[dict], dict]:
    recorded_matches = recorded_matches or set()
    live_matches = live_matches or set()
    search_matches = search_matches or set()
    all_matches = curated_matches | recorded_matches | live_matches | search_matches
    queue: list[dict] = []
    seen_products: set[str] = set()
    for record in count_plan["records"]:
        key = product_key(record)
        if key in seen_products:
            raise ValueError(f"duplicate catalog product: {key}")
        seen_products.add(key)
        candidates: list[dict] = []
        seen_pcodes: set[str] = set()
        for url in record.get("source_urls") or []:
            try:
                pcode = pcode_from_url(url)
            except ValueError:
                continue
            if pcode in seen_pcodes:
                continue
            seen_pcodes.add(pcode)
            candidates.append({
                "pcode": pcode,
                "product_url": f"https://prod.danawa.com/info/?pcode={pcode}",
                "model_match_status": "model_family_matched" if (key, pcode) in all_matches else "needs_model_review",
                "match_basis": "curated" if (key, pcode) in curated_matches else
                               "recorded_title_token" if (key, pcode) in recorded_matches else
                               "live_page_title" if (key, pcode) in live_matches else
                               "search_product_title" if (key, pcode) in search_matches else "unreviewed_url",
            })
        for match_key, pcode in sorted(all_matches):
            if match_key != key or pcode in seen_pcodes:
                continue
            seen_pcodes.add(pcode)
            candidates.append({
                "pcode": pcode,
                "product_url": f"https://prod.danawa.com/info/?pcode={pcode}",
                "model_match_status": "model_family_matched",
                "match_basis": "curated" if (key, pcode) in curated_matches else
                               "recorded_title_token" if (key, pcode) in recorded_matches else
                               "live_page_title" if (key, pcode) in live_matches else "search_product_title",
            })
        queue.append({
            "product_key": key,
            "sheet": record["sheet"],
            "catalog_manufacturer": record["manufacturer"],
            "catalog_model": record["model"],
            "danawa_candidates": candidates,
            "candidate_count": len(candidates),
            "review_use_status": "unreviewed",
            "review_collection_status": "not_determined_by_match_queue",
        })
    queue.sort(key=lambda row: (row["sheet"], row["product_key"]))
    unknown_matches = {key for key, _ in all_matches} - seen_products
    if unknown_matches:
        raise ValueError(f"model matches contain unknown catalog products: {sorted(unknown_matches)}")
    owner_by_pcode: dict[str, str] = {}
    for key, pcode in sorted(all_matches):
        previous = owner_by_pcode.setdefault(pcode, key)
        if previous != key:
            raise ValueError(f"Danawa pcode assigned to two catalog products: {pcode}: {previous}, {key}")
    counts = Counter("no_url" if not row["candidate_count"] else
                     "one_url" if row["candidate_count"] == 1 else "multiple_urls" for row in queue)
    curated_products = sum(any(c["model_match_status"] == "model_family_matched"
                               for c in row["danawa_candidates"]) for row in queue)
    recorded_products = sum(any(c["match_basis"] == "recorded_title_token"
                                for c in row["danawa_candidates"]) for row in queue)
    report = {
        "products": len(queue),
        "products_without_danawa_url": counts["no_url"],
        "products_with_one_danawa_url": counts["one_url"],
        "products_with_multiple_danawa_urls": counts["multiple_urls"],
        "model_family_matched_products": curated_products,
        "recorded_title_token_products": recorded_products,
        "live_page_title_products": sum(any(c["match_basis"] == "live_page_title"
                                            for c in row["danawa_candidates"]) for row in queue),
        "search_product_title_products": sum(any(c["match_basis"] == "search_product_title"
                                               for c in row["danawa_candidates"]) for row in queue),
        "review_text_collected": False,
        "new_network_requests": 0,
        "usage_approved": False,
        "note": "Candidate URLs are not usable individual reviews; curated model matches do not approve review usage.",
    }
    return queue, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-plan", type=Path, default=DEFAULT_COUNT_PLAN)
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    parser.add_argument("--recorded-matches", type=Path, default=DEFAULT_RECORDED_MATCHES)
    parser.add_argument("--live-matches", type=Path, default=DEFAULT_LIVE_MATCHES)
    parser.add_argument("--search-matches", type=Path, default=DEFAULT_SEARCH_MATCHES)
    parser.add_argument("--search-candidates", type=Path, default=DEFAULT_SEARCH_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    recorded_document = json.loads(args.recorded_matches.read_text(encoding="utf-8"))
    recorded_matches = {(row["product_key"], row["pcode"]) for row in recorded_document["matches"]}
    live_document = json.loads(args.live_matches.read_text(encoding="utf-8"))
    live_matches = {(row["product_key"], row["pcode"]) for row in live_document["matches"]}
    search_document = json.loads(args.search_matches.read_text(encoding="utf-8"))
    search_candidates = [json.loads(line) for line in args.search_candidates.read_text(encoding="utf-8").splitlines()
                         if line.strip()]
    search_matches = validate_search_matches(search_document["matches"], search_candidates)
    queue, report = build_queue(
        json.loads(args.count_plan.read_text(encoding="utf-8")),
        load_model_matches(args.matches),
        recorded_matches,
        live_matches,
        search_matches,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queue), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
