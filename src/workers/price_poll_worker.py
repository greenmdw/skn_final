"""가격 폴링 워커.

목표가 알림(ACC-02)의 판정 배치. 2026-09-12에 notification 스키마 전체가 "완전 제거" 대상이었다가,
2026-09-30 기획서가 판정·발송을 다시 요구해 2026-09-27 팀 재확인 뒤 되살렸다
(db/migrations/0004_notification_events.sql).

**범위를 줄였다**: 제휴 커머스 API로 가격을 새로 수집하는 실시간 재조회는 이 프로젝트에 없다. 대신 이미
있는 `catalog.offer_observation`(카탈로그 갱신 때 쌓인 최신 관측가)과 목표가를 비교하는 것까지만 한다 —
"가격을 새로 조사"하지 않고 "이미 아는 최신 가격으로 판정"한다. 실시간 수집이 필요하면 이 워커가 아니라
그 수집 파이프라인(카탈로그 갱신 배치)을 먼저 만들어야 한다.

스케줄: 이 프로젝트엔 cron이 없다. `feedback_batch.run()`과 같은 관례로, 외부에서 주기적으로 이 모듈의
`run()`을 부르는 것을 전제로 한다(수동 실행 또는 배포 환경의 스케줄러).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.db import get_conn
from src.repo.notification_repo import NotificationRepo

log = logging.getLogger(__name__)

# 같은 watch를 이 주기보다 자주 다시 평가하지 않는다 — 워커를 더 자주 돌려도 중복 판정을 만들지 않는다.
POLL_INTERVAL = timedelta(hours=6)


def _evaluate_one(nrepo: NotificationRepo, watch: dict, now: datetime) -> bool:
    """watch 하나를 평가하고 상태를 갱신한다. 새로 "도달" 알림을 만들었으면 True."""
    total, complete = nrepo.current_total(watch["revision_id"])
    status = "complete" if complete else "unavailable"
    target_reached = (total <= int(watch["target_amount"])) if complete else None
    evaluation_id = nrepo.add_evaluation(
        watch["id"], evaluated_at=now, amount=total, status=status,
        target_reached=target_reached, breakdown={"complete": complete},
    )
    new_state = "reached" if target_reached else "above" if complete else "unknown"
    # list_active_watches가 준 값 = 이번 평가 전 상태. 처음 도달한 순간에만 알림 이벤트를 만든다 —
    # 이미 도달한 채로 있는 매 주기마다 또 만들지 않는다(다시 올랐다가 또 떨어지면 그때 다시 알린다).
    previously_reached = watch["last_condition_state"] == "reached"
    nrepo.set_condition_state(watch["id"], new_state)

    if new_state != "reached" or previously_reached:
        return False
    nrepo.create_event(
        evaluation_id, watch["owner_user_id"],
        dedupe_key=f"pricewatch:{watch['id']}:{evaluation_id}",
        payload_snapshot={
            "watch_id": str(watch["id"]), "revision_id": str(watch["revision_id"]),
            "target_amount": int(watch["target_amount"]), "amount": total,
        },
    )
    return True


def run() -> dict:
    """활성 watch를 전부 평가한다. (평가한 개수, 새로 알림을 만든 개수)를 돌려준다."""
    now = datetime.now(timezone.utc)
    evaluated = notified = 0
    with get_conn() as conn:
        nrepo = NotificationRepo(conn)
        for watch in nrepo.list_active_watches(due_before=now - POLL_INTERVAL):
            try:
                if _evaluate_one(nrepo, watch, now):
                    notified += 1
            except Exception:  # noqa: BLE001 — watch 하나가 실패해도 나머지는 계속 평가한다
                log.exception("price watch %s evaluation failed", watch["id"])
                continue
            evaluated += 1
    log.info("price poll: evaluated=%d notified=%d", evaluated, notified)
    return {"evaluated": evaluated, "notified": notified}
