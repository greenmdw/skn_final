"""삭제 표시 후 보관 기간이 지난 대화·견적서를 영구 삭제하는 작업(재기획 6.7).

    python -m src.workers.purge_deleted --once        # 한 번 돌고 끝낸다(스케줄러용)
    python -m src.workers.purge_deleted               # PURGE_INTERVAL_SECONDS 마다 반복한다(워커용)
    python -m src.workers.purge_deleted --dry-run     # 지울 개수만 센다

보관 기간은 PURGE_DELETED_AFTER_DAYS(기본 30, 가정). 항목마다 트랜잭션이 따로라 하나가 실패해도 나머지는 계속한다.
"""
from __future__ import annotations

import argparse
import logging
import time

from src.config import PURGE_DELETED_AFTER_DAYS, PURGE_INTERVAL_SECONDS
from src.db import get_conn
from src.services import purge_service

log = logging.getLogger("purge_deleted")


def run_once(days: int = PURGE_DELETED_AFTER_DAYS, *, dry_run: bool = False) -> dict[str, int]:
    with get_conn() as conn:
        if dry_run:
            repo = purge_service.PurgeRepo(conn)
            return {"plans": len(repo.expired_plans(days)), "revisions": len(repo.expired_revisions(days))}
        result = purge_service.purge_expired(conn, days)
    log.info("purged %s (older than %d days)", result, days)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=PURGE_DELETED_AFTER_DAYS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.dry_run or args.once:
        print(run_once(args.days, dry_run=args.dry_run))
        return
    while True:
        try:
            run_once(args.days)
        except Exception:                                   # noqa: BLE001 — 한 번 실패해도 다음 주기에 다시 한다
            log.exception("purge run failed")
        time.sleep(PURGE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
