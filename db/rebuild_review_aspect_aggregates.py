#!/usr/bin/env python3
"""Preview or rebuild review-aspect aggregates for one analysis version.

Examples:
    python db/rebuild_review_aspect_aggregates.py --analysis-version review-aspect-v6-prod-20261002
    python db/rebuild_review_aspect_aggregates.py --analysis-version test-version --apply

The default operation is read-only. Use an isolated test database for write validation; applying
to actual development data is outside this implementation verification run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import psycopg

# Direct `python db/...py` execution puts db/ first on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DATABASE_URL
from src.services.review_aspect_aggregate import rebuild_review_aspect_aggregates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-version", required=True)
    parser.add_argument("--apply", action="store_true", help="write the aggregate and member rows")
    args = parser.parse_args(argv)

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5, autocommit=True) as conn:
            report = rebuild_review_aspect_aggregates(
                conn, args.analysis_version, apply=args.apply,
            )
    except psycopg.Error as exc:
        state = exc.sqlstate or "unavailable"
        print(f"database operation failed (SQLSTATE {state})", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
