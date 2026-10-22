#!/usr/bin/env python3
"""Import agent observations; documents and rules must already exist."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from src.services.review_observation_import import import_observations, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Original agent input JSON")
    parser.add_argument("--output", type=Path, required=True, help="Agent output JSON")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    args = parser.parse_args()
    try:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL must be explicitly set")
        source, output = read_json(args.input), read_json(args.output)
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            summary = import_observations(conn, source, output, dry_run=args.dry_run)
        print(json.dumps(summary))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Import rejected: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"Database import failed (SQLSTATE={exc.sqlstate}); transaction rolled back", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
