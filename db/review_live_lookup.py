#!/usr/bin/env python3
"""임시 부품 저장소(catalog.live_spec_lookup_cache) 검토 도구 — 설계 문서 §9.3-3.

실시간 검색 결과는 처음엔 unreviewed 다. 사람이 원문 출처를 열어 확인하고 상태를 바꾼다.
  confirmed — 만료 없이 계속 쓴다(나중에 카탈로그 승격 후보)
  rejected  — 틀린 값. 서비스는 "못 찾음"으로 취급하고, 못 찾음 만료가 지나면 다시 검색한다

    DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/truefit python db/review_live_lookup.py list
    python db/review_live_lookup.py list --status confirmed
    python db/review_live_lookup.py confirm 3f2a9c1b          # id 앞 8자리 이상
    python db/review_live_lookup.py reject 3f2a9c1b
    python db/review_live_lookup.py reset 3f2a9c1b            # unreviewed 로 되돌림
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo  # noqa: E402

_STATUS_OF = {"confirm": "confirmed", "reject": "rejected", "reset": "unreviewed"}


def _fields(row: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in (row["supported_fields"] or {}).items() if v is not None) or "(필드 없음)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    listing = sub.add_parser("list", help="상태별 목록")
    listing.add_argument("--status", choices=["unreviewed", "confirmed", "rejected"], default="unreviewed")
    listing.add_argument("--limit", type=int, default=50)
    for name in _STATUS_OF:
        cmd = sub.add_parser(name)
        cmd.add_argument("id", help="행 id 앞부분(8자리 이상)")
    args = parser.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL 환경변수가 필요합니다.", file=sys.stderr)
        return 2
    with psycopg.connect(dsn) as conn:
        repo = LiveSpecLookupRepo(conn)
        if args.cmd == "list":
            rows = repo.list_by_status(args.status, limit=args.limit)
            for row in rows:
                found = "찾음" if row["relevant"] else "못 찾음"
                print(f"{str(row['id'])[:8]}  [{found}]  {row['lookup_key']}  | {_fields(row)}")
                print(f"          출처: {row['source_url'] or '-'}  · 확인 시각: {row['fetched_at']:%Y-%m-%d %H:%M}")
            print(json.dumps({"status": args.status, "count": len(rows)}, ensure_ascii=False))
            return 0
        if len(args.id) < 8:
            print("id 는 8자리 이상 입력하세요.", file=sys.stderr)
            return 2
        try:
            row = repo.set_status(args.id, _STATUS_OF[args.cmd])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if row is None:
            print("정확히 하나의 행을 찾지 못했습니다(id 가 없거나 여러 행과 겹침).", file=sys.stderr)
            return 1
        conn.commit()
        print(json.dumps({"id": str(row["id"]), "lookup_key": row["lookup_key"], "status": row["status"]},
                         ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
