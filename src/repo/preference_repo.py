"""identity.preference_signal 저장소 — 사용자 선호·비선호 신호.

docs/사용자_선호비선호_기록_설계.md 참고. 판정은 호출자(배치/에이전트)가 하고, 여기는
저장·조회·상태 전이만 한다.
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class PreferenceRepo(Repo):
    def get_signal(self, *, user_id: UUID, dimension: str, slot: str | None, value: str) -> dict | None:
        """멱등 배치가 "이미 반영한 이벤트"를 알려면 먼저 이걸로 evidence_event_ids를 봐야 한다
        (preference_signal_batch.py)."""
        return self._one(
            "SELECT * FROM identity.preference_signal "
            "WHERE user_id=%s AND dimension=%s AND slot IS NOT DISTINCT FROM %s AND value=%s",
            (user_id, dimension, slot, value),
        )

    def upsert_signal(self, *, user_id: UUID, dimension: str, slot: str | None, value: str,
                       direction: str, source: str, confidence_delta: int = 1,
                       evidence_event_ids: list[UUID] | None = None) -> dict:
        """같은 (user, dimension, slot, value)면 confidence를 더하고 관측 시각만 갱신한다.
        상태가 'dismissed'였어도 다시 관측되면 'active'로 되돌린다 — 사용자가 한 번 거부했어도
        같은 패턴이 또 나오면 다시 물어볼 기회를 준다(설계 문서 §9).

        evidence_event_ids는 호출자가 이미 "새로 관측된 것만" 걸러서 넘겨야 한다 — 여기서는
        중복 검사를 하지 않는다(배치의 멱등성은 호출자가 get_signal로 미리 확인하는 책임)."""
        ids = list(evidence_event_ids or [])
        return self._one(
            """INSERT INTO identity.preference_signal
               (user_id, dimension, slot, value, direction, source, confidence, evidence_event_ids)
               VALUES (%(user_id)s, %(dimension)s, %(slot)s, %(value)s, %(direction)s, %(source)s,
                       %(confidence_delta)s, %(ids)s::uuid[])
               ON CONFLICT (user_id, dimension, slot, value) DO UPDATE SET
                   confidence = identity.preference_signal.confidence + EXCLUDED.confidence,
                   direction = EXCLUDED.direction,
                   source = EXCLUDED.source,
                   status = 'active',
                   evidence_event_ids = identity.preference_signal.evidence_event_ids || EXCLUDED.evidence_event_ids,
                   last_observed_at = now()
               RETURNING *""",
            {
                "user_id": user_id, "dimension": dimension, "slot": slot, "value": value,
                "direction": direction, "source": source, "confidence_delta": confidence_delta,
                "ids": ids,
            },
        )

    def list_active(self, user_id: UUID, *, dimension: str | None = None,
                     min_confidence: int | None = None) -> list[dict]:
        """min_confidence는 'inferred_swap'(행동 추론) 신호에만 적용한다 — 'explicit_chat'(사용자가
        직접 말한 것)은 반복 없이도 그 자체로 신뢰할 수 있어 문턱 없이 통과시킨다."""
        clauses = ["user_id=%s", "status='active'"]
        params: list = [user_id]
        if dimension is not None:
            clauses.append("dimension=%s")
            params.append(dimension)
        if min_confidence is not None:
            clauses.append("(source='explicit_chat' OR confidence>=%s)")
            params.append(min_confidence)
        return self._all(
            f"SELECT * FROM identity.preference_signal WHERE {' AND '.join(clauses)} "
            "ORDER BY confidence DESC, last_observed_at DESC",
            tuple(params),
        )

    def dismiss(self, user_id: UUID, signal_id: UUID) -> None:
        """사용자가 되묻기에 '아니요'를 선택했을 때 — 완전 삭제 대신 상태만 바꾼다(§9)."""
        self._exec(
            "UPDATE identity.preference_signal SET status='dismissed' "
            "WHERE id=%s AND user_id=%s",
            (signal_id, user_id),
        )
