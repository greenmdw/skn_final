"""이메일 발송 워커.

notification.notification_event(delivery_state='pending')를 잡아 메일 발송 → sent/failed 갱신.
dedupe_key로 중복 방지(price_poll_worker가 이미 "새로 도달한 경우만" 이벤트를 만들어서, 이 워커는
있는 이벤트를 순서대로 처리하기만 하면 된다).

**데모는 SES 샌드박스 대신 콘솔 로그로 발송을 대신한다** — 실제 SES 연동(자격 증명·발신 도메인 인증)이
이 프로젝트에 없다. 로그 한 줄이 실제 메일의 자리를 대신한다는 걸 명시적으로 남긴다.
"""
from __future__ import annotations

import logging

from src.db import get_conn
from src.repo.notification_repo import NotificationRepo

log = logging.getLogger(__name__)


def _send(event: dict) -> None:
    """실제 메일 발송 자리 — 지금은 콘솔 로그로 대신한다."""
    payload = event["payload_snapshot"]
    log.info(
        "[MOCK EMAIL] to=%s subject=목표가 도달 body=목표 %s원 이하로 내려갔어요(현재 %s원). "
        "watch_id=%s revision_id=%s",
        event["email"], payload.get("target_amount"), payload.get("amount"),
        payload.get("watch_id"), payload.get("revision_id"),
    )


def run(limit: int = 100) -> dict:
    """대기 중인 알림을 순서대로 처리한다. (성공, 실패) 건수를 돌려준다."""
    sent = failed = 0
    with get_conn() as conn:
        nrepo = NotificationRepo(conn)
        for event in nrepo.pending_events(limit=limit):
            try:
                _send(event)
            except Exception:  # noqa: BLE001 — 이 이벤트만 실패 처리하고 나머지는 계속 보낸다
                log.exception("notification event %s send failed", event["id"])
                nrepo.mark_failed(event["id"])
                failed += 1
                continue
            nrepo.mark_sent(event["id"])
            sent += 1
    log.info("notification worker: sent=%d failed=%d", sent, failed)
    return {"sent": sent, "failed": failed}
