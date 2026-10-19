"""Evaluate human-labeled free-question retrieval; paid execution requires --execute.

JSON rows: {id, product_id, query, split: "tune"|"test", relevant:
[{post_id, start_char, end_char}]}. An empty relevant list labels a negative query.
Offsets refer to normalized Unicode codepoints. Keep private question sets outside Git.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from uuid import UUID

from src import config
from src.services.review_evidence_search import search


def relevance(hit, labels):
    for label in labels:
        if hit["document_id"] != label["post_id"]:
            continue
        overlap = max(0, min(hit["end_char"], label["end_char"]) - max(hit["start_char"], label["start_char"]))
        if overlap >= (label["end_char"] - label["start_char"]) / 2:
            return True
    return False


def summarize(rows):
    positives = [r for r in rows if r["positive"]]
    negatives = [r for r in rows if not r["positive"]]
    return {
        "questions": len(rows), "positive_questions": len(positives), "negative_questions": len(negatives),
        "hit_at_3": statistics.mean(any(r["relevant"]) for r in positives) if positives else None,
        "precision_at_3": statistics.mean(sum(r["relevant"]) / 3 for r in positives) if positives else None,
        "mrr": statistics.mean(next((1 / i for i, good in enumerate(r["relevant"], 1) if good), 0)
                               for r in positives) if positives else None,
        "negative_false_positive_rate": statistics.mean(r["hits"] > 0 for r in negatives) if negatives else None,
        "latency_p50_seconds": statistics.median(r["seconds"] for r in rows) if rows else None,
        "latency_p95_seconds": sorted(r["seconds"] for r in rows)[min(len(rows)-1, int(len(rows)*0.95))] if rows else None,
        "incomplete_index_questions": sum(not r["index_complete"] for r in rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split", choices=("tune", "test"), default="test")
    parser.add_argument("--corpus-mode", choices=("real", "demo"), default="real")
    parser.add_argument("--execute", action="store_true", help="allow real, paid embedding calls")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    rows = json.loads(args.dataset.read_text())
    seen = set()
    for row in rows:
        if row["id"] in seen or row["split"] not in ("tune", "test") or not row["query"].strip():
            parser.error("question IDs must be unique, queries nonempty, and split tune or test")
        seen.add(row["id"])
        UUID(row["product_id"])
        for label in row["relevant"]:
            UUID(label["post_id"])
            if not 0 <= label["start_char"] < label["end_char"]:
                parser.error("invalid evidence offsets")
    selected = [r for r in rows if r["split"] == args.split]
    if not selected:
        parser.error("no questions in the selected split")
    if not args.execute:
        print(json.dumps({"validated_questions": len(rows), "selected_questions": len(selected),
                          "paid_calls": False, "execution": "add --execute to run real retrieval"}))
        return 0
    if config.MOCK_MODE:
        parser.error("semantic quality evaluation requires MOCK_MODE=0")
    results = []
    for row in selected:
        start = time.perf_counter()
        source = search(product_ids=[row["product_id"]], query=row["query"], limit=3,
                        sources=["community"], corpus_mode=args.corpus_mode)["products"][0]["sources"]["community"]
        results.append({"id": row["id"], "positive": bool(row["relevant"]),
                        "relevant": [relevance(h, row["relevant"]) for h in source["hits"]],
                        "hits": len(source["hits"]), "seconds": time.perf_counter()-start,
                        "index_complete": source["coverage"]["index_complete"]})
    report = {"split": args.split, "corpus_mode": args.corpus_mode,
              "min_similarity": config.COMMUNITY_REVIEW_SEARCH_MIN_SIMILARITY,
              "summary": summarize(results), "results": results}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
