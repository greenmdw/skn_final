"""Independent full-body community review indexing worker (never changes recommendation scores)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from uuid import UUID

from src import config
from src.rag.embedding import OpenAIEmbedder
from src.services.community_review_search_index import dry_run, repository_factory, run_once


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="count documents/chunks without writes or paid calls")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--post", help="comma-separated post UUIDs")
    parser.add_argument("--rebuild", action="store_true", help="queue a complete replacement; preserve rows until commit")
    parser.add_argument("--include-examples", action="store_true")
    args = parser.parse_args(argv)
    try:
        only = {UUID(s.strip()) for s in args.post.split(",")} if args.post else None
    except ValueError:
        parser.error("--post must contain UUIDs")
    if args.include_examples and not config.COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES:
        parser.error("set COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES=1 to index example posts")
    if not args.dry_run and not config.COMMUNITY_REVIEW_SEARCH_ENABLED:
        parser.error("set COMMUNITY_REVIEW_SEARCH_ENABLED=1 to run the index worker")
    if min(config.COMMUNITY_REVIEW_INDEX_INTERVAL_SECONDS, config.COMMUNITY_REVIEW_INDEX_SCAN_SECONDS) <= 0:
        parser.error("worker intervals must be positive")
    logging.basicConfig(level=logging.INFO)
    embedder = OpenAIEmbedder()
    factory = repository_factory(embedder, dsn=os.getenv("TEST_DATABASE_URL") or config.DATABASE_URL)
    if args.dry_run:
        print(json.dumps(dry_run(factory, include_examples=args.include_examples, only=only), ensure_ascii=False))
        return 0
    last_scan = float("-inf")
    failed = False
    while True:
        scan = args.once or time.monotonic() - last_scan >= config.COMMUNITY_REVIEW_INDEX_SCAN_SECONDS
        try:
            report = run_once(factory, embedder, include_examples=args.include_examples, only=only,
                              scan=scan, rebuild=args.rebuild)
        except ValueError as exc:
            parser.error(str(exc))
        if scan:
            last_scan = time.monotonic()
        args.rebuild = False
        print(json.dumps(report, ensure_ascii=False), flush=True)
        failed = bool(report["failed"])
        if args.once:
            return 1 if failed else 0
        time.sleep(config.COMMUNITY_REVIEW_INDEX_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
