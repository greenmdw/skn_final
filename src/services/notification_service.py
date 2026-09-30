"""알림 서비스 — 목표가 추적 설정 · 판정 결과 조회.

발송 자체는 notification_worker. 이 서비스는 watch 생성/조회와 판정 이력 조회.

`POST /lists/{id}/alert`(전체 구성 대상 on/off)는 `list_service.set_alert`가 `NotificationRepo.upsert_active`로
이미 처리한다 — 여기서는 그 경로를 대체하지 않는다. 이 모듈은 (1) 부품 단위 watch를 포함한 일반 생성
(`create_watch`, `NotificationRepo.create_watch` 사용 — 지금은 호출하는 화면이 없다)과 (2) 판정 상태 조회
(`get_watch_status`, 새 엔드포인트 `GET /lists/{id}/alert`가 쓴다)를 맡는다.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from uuid import UUID

from src.auth.deps import Principal
from src.errors import NotFound
from src.repo.notification_repo import NotificationRepo
from src.repo.plan_repo import PlanRepo
from src.services import auth_service
from src.services.session_service import _owned

_DEFAULT_WINDOW_DAYS = 90


def _require_confirmed_owned(conn, list_id: UUID, principal: Principal) -> dict:
    from src.services.list_service import confirmed_revision

    auth_service.require_active_user(conn, principal)
    # 새 견적서를 작성 중이면(현재 revision 이 draft) 가장 최근 확정 견적서의 알림을 본다.
    return confirmed_revision(conn, list_id, principal)


def create_watch(conn, list_id: UUID, principal: Principal, *, target_amount,
                 ends_at=None, purchase_line_id: UUID | None = None) -> dict:
    """목표가 watch를 만들거나 갱신한다. `purchase_line_id`를 주면 그 부품 하나만 지켜본다(전체 구성은 None).

    확정된 계획에만 걸 수 있다 — 확정 전 견적은 부품·가격이 계속 바뀌어 "지켜볼 가격"이 아직 없다."""
    from datetime import datetime

    revision = _require_confirmed_owned(conn, list_id, principal)
    ends_at = ends_at or (datetime.now(timezone.utc) + timedelta(days=_DEFAULT_WINDOW_DAYS))
    watch_id = NotificationRepo(conn).create_watch(
        revision["id"], target_amount=target_amount, pricing_policy={}, ends_at=ends_at,
        purchase_line_id=purchase_line_id,
    )
    return get_watch_status(conn, list_id, principal, watch_id=watch_id)


def get_watch_status(conn, list_id: UUID, principal: Principal, *, watch_id: UUID | None = None) -> dict:
    """현재 총액(지금 카탈로그 관측가 기준, 확정 스냅샷과 다를 수 있다)·목표가·도달 여부·최근 판정 시각.

    확정 스냅샷(`confirmed_total`)은 건드리지 않는다 — 이 값은 "그때 그 가격"이고, 여기서 보는 값은
    "지금 이 가격"이다. 목표가 알림은 후자를 본다."""
    revision = _require_confirmed_owned(conn, list_id, principal)
    nrepo = NotificationRepo(conn)
    watch = nrepo.get_by_id(watch_id) if watch_id is not None else None
    if watch is not None and watch["revision_id"] != revision["id"]:
        watch = None
    watch = watch or nrepo.get_for_revision(revision["id"])
    if watch is None:
        return {"enabled": False, "target_amount": None, "status": "waiting",
                "latest_total": None, "observed_at": None}

    latest = nrepo.latest_evaluation(watch["id"])
    status = {"unknown": "waiting", "above": "tracking", "reached": "reached"}.get(
        watch["last_condition_state"], "waiting")
    return {
        "enabled": watch["state"] == "active",
        "target_amount": int(watch["target_amount"]),
        "status": status if watch["state"] == "active" else "waiting",
        "latest_total": int(latest["amount"]) if latest and latest["amount"] is not None else None,
        "observed_at": latest["evaluated_at"].isoformat() if latest else None,
    }
