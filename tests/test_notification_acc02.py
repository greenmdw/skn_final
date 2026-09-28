"""목표가 알림 판정·발송 (ACC-02) — 저장소·서비스·워커 통합 테스트.

tests/test_list_service.py 와 같은 방식(실 로컬 PostgreSQL, autocommit)으로 돈다. price_poll_worker와
notification_worker는 자체 커넥션을 열므로(get_conn()) 이 파일의 autocommit 연결과는 별도다 — 워커가
쓴 값을 보려면 이 연결에서 다시 조회해야 한다(트랜잭션 격리 없음, autocommit이라 바로 보인다).

카탈로그 가격을 실제로 낮추는 것은 손대지 않는다(합성 카탈로그가 아니라 실 시드 데이터라 값을 바꾸면
다른 테스트에 영향) — 대신 목표 금액을 지금 가격보다 낮게/높게 잡아 도달 여부를 만든다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.errors import NotFound
from src.repo.notification_repo import NotificationRepo
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import UserRepo
from src.services import auth_service, list_service, notification_service, recommendation_service, session_service
from src.workers import notification_worker, price_poll_worker


class _Ctx:
    def __init__(self, connection):
        self.conn = connection
        self.created_ids: list[str] = []

    def signup(self, email: str, password: str = "abc12345") -> Principal:
        user, token = auth_service.signup(
            self.conn, Principal(user_id=None, browser_token=None),
            email=email, password=password, display_name="알림테스트",
            terms_agreed=True, privacy_agreed=True, marketing_agreed=False,
        )
        self.created_ids.append(user["id"])
        import base64
        import json
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        iat = json.loads(base64.urlsafe_b64decode(padded))["iat"]
        return Principal(user_id=uuid.UUID(user["id"]), browser_token=None, session_iat=iat)

    def confirmed_list(self, principal: Principal, target_amount: int) -> tuple[str, int]:
        """카테고리→조건→추천→확정까지 마친 list_id 와 그 확정 총액(현재 카탈로그 관측가와 보통 같다)."""
        list_id = session_service.create_session(self.conn, principal)["list_id"]
        list_uuid = uuid.UUID(list_id)
        session_service.choose_category(self.conn, list_uuid, "computer", "build", principal)
        for field, value in (("purpose", "game"), ("budget_max", 1500000), ("priority", "value")):
            session_service.patch_slot(self.conn, list_uuid, field, value, principal)
        revision_id = PlanRepo(self.conn).get_current_revision(list_uuid)["id"]
        accepted = recommendation_service.start_recommendation(self.conn, revision_id, strategy="default")
        recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
        report = list_service.confirm(
            self.conn, list_uuid, principal, name="알림 테스트", planned_purchase_at=None,
            target_amount=target_amount, memo="",
        )
        return list_id, report["total"]


@pytest.fixture
def ctx():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    has_pwe = connection.execute(
        "SELECT to_regclass('notification.price_watch_evaluation') IS NOT NULL"
    ).fetchone()[0]
    if not has_pwe:
        connection.close()
        pytest.skip("0004_notification_events.sql 이 적용되지 않은 DB입니다 — db/migrate.py up 으로 준비하세요.")
    context = _Ctx(connection)
    try:
        yield context
    finally:
        for user_id in context.created_ids:
            try:
                UserRepo(connection).withdraw(uuid.UUID(user_id))
            except Exception:  # noqa: BLE001
                pass
        connection.close()


def _unique_email() -> str:
    return f"notif-test-{uuid.uuid4().hex}@example.com"


# ── NotificationRepo.current_total — 확정 스냅샷과 분리된 "지금 가격" ──────────────────────

def test_current_total_matches_the_confirmed_total_right_after_confirming(ctx):
    """확정 직후엔 관측가가 안 바뀌었으니 지금 합계도 확정 총액과 같다."""
    principal = ctx.signup(_unique_email())
    list_id, confirmed_total = ctx.confirmed_list(principal, target_amount=1_000_000)
    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]

    total, complete = NotificationRepo(ctx.conn).current_total(revision_id)
    assert complete is True and total == confirmed_total


def test_current_total_does_not_touch_the_confirmed_snapshot(ctx):
    principal = ctx.signup(_unique_email())
    list_id, confirmed_total = ctx.confirmed_list(principal, target_amount=1_000_000)
    NotificationRepo(ctx.conn).current_total(PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"])
    report = list_service.get_report(ctx.conn, uuid.UUID(list_id), principal)
    assert report["total"] == confirmed_total   # 재조회해도 확정 스냅샷은 그대로


# ── create_watch / get_watch_status ──────────────────────────────────────────────────

def test_create_watch_requires_a_confirmed_list(ctx):
    principal = ctx.signup(_unique_email())
    list_id = session_service.create_session(ctx.conn, principal)["list_id"]
    with pytest.raises(NotFound):
        notification_service.create_watch(ctx.conn, uuid.UUID(list_id), principal, target_amount=1_000_000)


def test_watch_status_reflects_the_saved_target_and_starts_waiting(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    status = notification_service.create_watch(ctx.conn, uuid.UUID(list_id), principal, target_amount=total - 1)
    assert status == {"enabled": True, "target_amount": total - 1, "status": "waiting",
                      "latest_total": None, "observed_at": None}


def test_only_the_owner_can_read_watch_status(ctx):
    owner = ctx.signup(_unique_email())
    stranger = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(owner, target_amount=1_000_000)
    with pytest.raises(NotFound):
        notification_service.get_watch_status(ctx.conn, uuid.UUID(list_id), stranger)


# ── price_poll_worker: 판정과 상태 갱신 ──────────────────────────────────────────────────

def test_a_watch_below_current_price_stays_above_and_creates_no_event(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total - 1)

    result = price_poll_worker.run()
    assert result["evaluated"] >= 1 and result["notified"] == 0

    status = notification_service.get_watch_status(ctx.conn, uuid.UUID(list_id), principal)
    assert status["status"] == "tracking" and status["latest_total"] == total and status["observed_at"] is not None


def test_a_watch_at_or_above_current_price_reaches_and_creates_exactly_one_event(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)

    price_poll_worker.run()
    status = notification_service.get_watch_status(ctx.conn, uuid.UUID(list_id), principal)
    assert status["status"] == "reached" and status["latest_total"] == total

    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]
    watch = NotificationRepo(ctx.conn).get_for_revision(revision_id)
    events = ctx.conn.execute(
        "SELECT count(*) FROM notification.notification_event ne "
        "JOIN notification.price_watch_evaluation pwe ON pwe.id = ne.evaluation_id "
        "WHERE pwe.watch_id = %s", (watch["id"],),
    ).fetchone()[0]
    assert events == 1

    # 이미 도달한 채로 다시 돌려도 새 알림을 또 만들지 않는다(주기마다 스팸 방지) — due_before 를 우회해
    # 강제로 다시 평가해도 이벤트 수는 그대로다.
    from src.repo.notification_repo import NotificationRepo as _NR
    now = datetime.now(timezone.utc)
    price_poll_worker._evaluate_one(_NR(ctx.conn), watch, now)
    events_after = ctx.conn.execute(
        "SELECT count(*) FROM notification.notification_event ne "
        "JOIN notification.price_watch_evaluation pwe ON pwe.id = ne.evaluation_id "
        "WHERE pwe.watch_id = %s", (watch["id"],),
    ).fetchone()[0]
    assert events_after == 1


def test_a_paused_watch_is_not_evaluated(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=False, target_amount=None)

    price_poll_worker.run()
    status = notification_service.get_watch_status(ctx.conn, uuid.UUID(list_id), principal)
    assert status["latest_total"] is None       # paused 라 evaluate 대상에서 빠졌다


def test_list_active_watches_skips_ones_evaluated_within_the_poll_interval(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)
    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]
    nrepo = NotificationRepo(ctx.conn)
    watch = nrepo.get_for_revision(revision_id)

    now = datetime.now(timezone.utc)
    due = [w["id"] for w in nrepo.list_active_watches(due_before=now - timedelta(hours=6))]
    assert watch["id"] in due                      # 아직 평가 이력 없음 → due

    nrepo.add_evaluation(watch["id"], evaluated_at=now, amount=total, status="complete",
                        target_reached=True, breakdown={})
    still_due = [w["id"] for w in nrepo.list_active_watches(due_before=now - timedelta(hours=6))]
    assert watch["id"] not in still_due             # 방금 평가함 → 이번 주기엔 다시 안 줌


# ── notification_worker: 발송·재시도 ─────────────────────────────────────────────────────

def test_notification_worker_sends_pending_events_and_marks_them(ctx, caplog):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)
    price_poll_worker.run()

    import logging
    with caplog.at_level(logging.INFO, logger="src.workers.notification_worker"):
        result = notification_worker.run()
    assert result["sent"] >= 1
    assert any("MOCK EMAIL" in r.message for r in caplog.records)

    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]
    watch = NotificationRepo(ctx.conn).get_for_revision(revision_id)
    state = ctx.conn.execute(
        "SELECT ne.delivery_state FROM notification.notification_event ne "
        "JOIN notification.price_watch_evaluation pwe ON pwe.id = ne.evaluation_id "
        "WHERE pwe.watch_id = %s", (watch["id"],),
    ).fetchone()[0]
    assert state == "sent"


def test_a_send_failure_is_marked_failed_and_does_not_stop_the_batch(ctx, monkeypatch):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)
    price_poll_worker.run()

    monkeypatch.setattr(notification_worker, "_send", lambda _e: (_ for _ in ()).throw(RuntimeError("smtp down")))
    result = notification_worker.run()
    assert result["failed"] >= 1 and result["sent"] == 0

    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]
    watch = NotificationRepo(ctx.conn).get_for_revision(revision_id)
    row = ctx.conn.execute(
        "SELECT ne.delivery_state, ne.attempts FROM notification.notification_event ne "
        "JOIN notification.price_watch_evaluation pwe ON pwe.id = ne.evaluation_id "
        "WHERE pwe.watch_id = %s", (watch["id"],),
    ).fetchone()
    assert row == ("failed", 1)


# ── create_event dedupe ──────────────────────────────────────────────────────────────────

def test_create_event_is_idempotent_on_the_same_dedupe_key(ctx):
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    revision_id = PlanRepo(ctx.conn).get_current_revision(uuid.UUID(list_id))["id"]
    nrepo = NotificationRepo(ctx.conn)
    watch_id = nrepo.create_watch(revision_id, target_amount=total, pricing_policy={},
                                  ends_at=datetime.now(timezone.utc) + timedelta(days=1))
    ev_id = nrepo.add_evaluation(watch_id, evaluated_at=datetime.now(timezone.utc), amount=total,
                                 status="complete", target_reached=True, breakdown={})
    first = nrepo.create_event(ev_id, uuid.UUID(principal.user_id.hex), dedupe_key="dupe-test-key",
                               payload_snapshot={"a": 1})
    second = nrepo.create_event(ev_id, uuid.UUID(principal.user_id.hex), dedupe_key="dupe-test-key",
                                payload_snapshot={"a": 2})
    assert first == second
    count = ctx.conn.execute(
        "SELECT count(*) FROM notification.notification_event WHERE dedupe_key='dupe-test-key'"
    ).fetchone()[0]
    assert count == 1


# ── HTTP: GET /lists/{id}/alert ──────────────────────────────────────────────────────────

def test_get_alert_endpoint_returns_watch_status_over_http(ctx, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    principal = ctx.signup(_unique_email())
    list_id, total = ctx.confirmed_list(principal, target_amount=1_000_000)
    list_service.set_alert(ctx.conn, uuid.UUID(list_id), principal, enabled=True, target_amount=total)
    price_poll_worker.run()

    from src.auth.jwt import issue
    token = issue(principal.user_id, "")
    with TestClient(app) as client:
        client.cookies.set("truefit_session", token)
        res = client.get(f"/lists/{list_id}/alert")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "reached" and body["latest_total"] == total
