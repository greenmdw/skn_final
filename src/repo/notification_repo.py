"""notification.* 저장소 — price_watch / price_watch_evaluation / notification_event.

S5-b 목표가 추적 → 판정 → 이메일. 같은 범위에 active watch 는 하나(부분 UNIQUE).
이벤트 생성은 도달 상태 갱신과 같은 트랜잭션, 발송은 커밋 후 워커(§53).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from src.db.base import Repo


class NotificationRepo(Repo):
    def get_for_revision(self, revision_id: UUID) -> dict | None:
        """purchase_line_id 없는(전체 구성 대상) watch 1건 — revision당 최대 하나(부분 UNIQUE)."""
        return self._one(
            "SELECT * FROM notification.price_watch WHERE revision_id=%s AND purchase_line_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (revision_id,),
        )

    def upsert_active(self, revision_id: UUID, *, target_amount, ends_at) -> dict:
        """활성 watch를 만들거나(없으면) 기존 것을 갱신+재활성화한다. purchase_line_id는 항상 NULL(전체 구성 대상)."""
        existing = self.get_for_revision(revision_id)
        if existing is None:
            return self._one(
                "INSERT INTO notification.price_watch "
                "(revision_id, target_amount, pricing_policy, state, ends_at) "
                "VALUES (%s, %s, '{}'::jsonb, 'active', %s) RETURNING *",
                (revision_id, target_amount, ends_at),
            )
        return self._one(
            "UPDATE notification.price_watch SET target_amount=%s, state='active', ends_at=%s, "
            "updated_at=now() WHERE id=%s RETURNING *",
            (target_amount, ends_at, existing["id"]),
        )

    def get_by_id(self, watch_id: UUID) -> dict | None:
        return self._one("SELECT * FROM notification.price_watch WHERE id=%s", (watch_id,))

    def pause(self, watch_id: UUID) -> None:
        self._exec(
            "UPDATE notification.price_watch SET state='paused', updated_at=now() WHERE id=%s",
            (watch_id,),
        )

    def create_watch(self, revision_id: UUID, *, target_amount, pricing_policy: dict,
                     ends_at, purchase_line_id: UUID | None = None) -> UUID:
        """`upsert_active`의 일반형 — 부품 하나(purchase_line_id)에 대한 watch도 만들 수 있다(전체 구성은 NULL).
        같은 범위(revision_id, purchase_line_id)에 이미 활성 watch가 있으면 그것을 갱신·재활성화한다
        (부분 UNIQUE `price_watch_active_scope_key`가 같은 범위의 중복 활성 watch를 막는다)."""
        existing = self._one(
            "SELECT id FROM notification.price_watch WHERE revision_id=%s "
            "AND purchase_line_id IS NOT DISTINCT FROM %s AND state='active'",
            (revision_id, purchase_line_id),
        )
        if existing is not None:
            row = self._one(
                "UPDATE notification.price_watch SET target_amount=%s, pricing_policy=%s, ends_at=%s, "
                "updated_at=now() WHERE id=%s RETURNING id",
                (target_amount, Jsonb(pricing_policy), ends_at, existing["id"]),
            )
        else:
            row = self._one(
                "INSERT INTO notification.price_watch "
                "(revision_id, purchase_line_id, target_amount, pricing_policy, state, ends_at) "
                "VALUES (%s, %s, %s, %s, 'active', %s) RETURNING id",
                (revision_id, purchase_line_id, target_amount, Jsonb(pricing_policy), ends_at),
            )
        return row["id"]

    def list_active_watches(self, *, due_before: datetime | None = None) -> list[dict]:
        """만료되지 않은 활성 watch. `due_before`를 주면 그 시각 이후로 평가된 적 없는(=이번 주기에
        아직 안 본) watch만 돌려준다 — 폴링 주기보다 자주 불려도 같은 watch를 두 번 평가하지 않는다."""
        return self._all(
            "SELECT pw.*, p.owner_user_id, pr.state AS revision_state FROM notification.price_watch pw "
            "JOIN planning.plan_revision pr ON pr.id = pw.revision_id "
            "JOIN planning.plan p ON p.id = pr.plan_id "
            "WHERE pw.state='active' AND pw.ends_at > now() AND p.owner_user_id IS NOT NULL "
            "AND (%(due_before)s::timestamptz IS NULL OR NOT EXISTS ("
            "  SELECT 1 FROM notification.price_watch_evaluation pwe "
            "  WHERE pwe.watch_id = pw.id AND pwe.evaluated_at > %(due_before)s"
            ")) ORDER BY pw.created_at",
            {"due_before": due_before},
        )

    def set_condition_state(self, watch_id: UUID, state: str) -> None:
        """평가 결과로 `price_watch.last_condition_state`를 갱신한다(화면의 PriceWatchOut.status가 읽는 값)."""
        self._exec(
            "UPDATE notification.price_watch SET last_condition_state=%s, updated_at=now() WHERE id=%s",
            (state, watch_id),
        )

    def add_evaluation(self, watch_id: UUID, *, evaluated_at, amount, status: str,
                       target_reached: bool | None, breakdown: dict) -> UUID:
        row = self._one(
            "INSERT INTO notification.price_watch_evaluation "
            "(watch_id, evaluated_at, amount, status, target_reached, breakdown) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (watch_id, evaluated_at, amount, status, target_reached, Jsonb(breakdown)),
        )
        return row["id"]

    def latest_evaluation(self, watch_id: UUID) -> dict | None:
        return self._one(
            "SELECT * FROM notification.price_watch_evaluation WHERE watch_id=%s "
            "ORDER BY evaluated_at DESC LIMIT 1",
            (watch_id,),
        )

    def create_event(self, evaluation_id: UUID, user_id: UUID, *, dedupe_key: str,
                     payload_snapshot: dict) -> UUID:
        """UNIQUE(dedupe_key) 로 중복 알림 방지 — 이미 같은 키로 만든 이벤트가 있으면 그 id를 그대로 돌려준다
        (호출자가 재시도해도 두 번째 행이 생기지 않는다)."""
        row = self._one(
            "INSERT INTO notification.notification_event "
            "(evaluation_id, user_id, dedupe_key, payload_snapshot) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (dedupe_key) DO UPDATE SET dedupe_key=EXCLUDED.dedupe_key RETURNING id",
            (evaluation_id, user_id, dedupe_key, Jsonb(payload_snapshot)),
        )
        return row["id"]

    def pending_events(self, limit: int = 100) -> list[dict]:
        """발송 대기 중인 이벤트 — 발송에 필요한 수신자 이메일까지 조인해서 낸다."""
        return self._all(
            "SELECT ne.id, ne.user_id, ne.dedupe_key, ne.payload_snapshot, ne.attempts, "
            "u.email_normalized AS email "
            "FROM notification.notification_event ne "
            "JOIN identity.app_user u ON u.id = ne.user_id "
            "WHERE ne.delivery_state='pending' AND u.status='active' "
            "ORDER BY ne.created_at LIMIT %s",
            (limit,),
        )

    def mark_sent(self, event_id: UUID) -> None:
        self._exec(
            "UPDATE notification.notification_event SET delivery_state='sent', sent_at=now(), "
            "updated_at=now() WHERE id=%s AND delivery_state='pending'",
            (event_id,),
        )

    def current_total(self, revision_id: UUID) -> tuple[int | None, bool]:
        """확정 스냅샷(`purchase_line.snapshot`/`confirmed_total`)은 절대 바꾸지 않는다(리포트 불변 원칙,
        db/README.md "C14 게시/확정 불변성") — 대신 그 라인이 가리키는 오퍼(offer_id)의 **지금 최신
        관측가**를 새로 조회해 합산한다. 목표가 알림은 이 값을 본다.

        반환: (합계 또는 None, 전 라인의 최신가를 다 알면 True). 관측이 없는 라인이 하나라도 있으면
        `complete=False`이고 합계는 None — 일부만 더해 실제보다 낮은 값으로 오판하지 않는다."""
        rows = self._all(
            "SELECT pl.pack_count, "
            "(SELECT oo.price FROM catalog.offer_observation oo WHERE oo.offer_id = pl.offer_id "
            " AND oo.quality_status='valid' ORDER BY oo.observed_at DESC LIMIT 1) AS latest_price "
            "FROM planning.purchase_line pl WHERE pl.revision_id=%s",
            (revision_id,),
        )
        if not rows or any(r["latest_price"] is None for r in rows):
            return None, False
        return int(sum(int(r["latest_price"]) * int(r["pack_count"]) for r in rows)), True

    def mark_failed(self, event_id: UUID) -> None:
        self._exec(
            "UPDATE notification.notification_event SET delivery_state='failed', attempts=attempts+1, "
            "updated_at=now() WHERE id=%s",
            (event_id,),
        )
