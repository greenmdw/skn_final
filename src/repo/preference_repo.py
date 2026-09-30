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
        """관측을 confidence_delta 번 더한다. 한 (user, dimension, slot, value)에 행은 하나이고 방향은 순(net)으로 센다:

        - 같은 방향이면 더하고, 반대 방향이면 뺀다 — 음수가 되면 방향이 뒤집히고 차이만 남는다. 예전엔 방향을 새 값으로
          덮고 횟수는 더해서, Intel 선호 2 + 비선호 1 이 "비선호 3"(되묻기 문턱)이 됐다. 스키마(유일 키에 direction 없음)는
          그대로 두고 순 횟수로 뜻을 맞췄다 — 팀원 DB 에 마이그레이션이 필요 없다.
        - 직접 말한 것(explicit_chat)은 추론(inferred_swap)이 바꾸지 않는다. 예전엔 추론 한 번이 source 를 덮어
          문턱 우회를 잃고 되묻기가 사라졌다. 새로 직접 말하면 그 말이 이긴다(같은 방향이면 더하고, 아니면 새로 시작).
        - 'dismissed'였어도 다시 관측되면 'active'로 되돌린다 — 같은 패턴이 또 나오면 다시 물어볼 기회를 준다(설계 §9).

        evidence_event_ids 는 호출자가 "새로 관측된 것만" 넘긴다(중복 검사 없음)."""
        ids = list(evidence_event_ids or [])
        same = "ps.direction = EXCLUDED.direction"
        explicit_in, explicit_row = "EXCLUDED.source = 'explicit_chat'", "ps.source = 'explicit_chat'"
        return self._one(
            f"""INSERT INTO identity.preference_signal AS ps
               (user_id, dimension, slot, value, direction, source, confidence, evidence_event_ids)
               VALUES (%(user_id)s, %(dimension)s, %(slot)s, %(value)s, %(direction)s, %(source)s,
                       %(confidence_delta)s, %(ids)s::uuid[])
               ON CONFLICT (user_id, dimension, slot, value) DO UPDATE SET
                   direction = CASE
                       WHEN {explicit_in} THEN EXCLUDED.direction
                       WHEN {explicit_row} OR {same} THEN ps.direction
                       WHEN EXCLUDED.confidence > ps.confidence THEN EXCLUDED.direction
                       ELSE ps.direction END,
                   confidence = CASE
                       WHEN {explicit_in} THEN CASE WHEN {explicit_row} AND {same}
                                                    THEN ps.confidence + EXCLUDED.confidence ELSE EXCLUDED.confidence END
                       WHEN {explicit_row} THEN ps.confidence
                       WHEN {same} THEN ps.confidence + EXCLUDED.confidence
                       ELSE abs(ps.confidence - EXCLUDED.confidence) END,
                   source = CASE WHEN {explicit_in} OR {explicit_row} THEN 'explicit_chat' ELSE ps.source END,
                   status = 'active',
                   evidence_event_ids = ps.evidence_event_ids || EXCLUDED.evidence_event_ids,
                   last_observed_at = now()
               RETURNING *""",
            {
                "user_id": user_id, "dimension": dimension, "slot": slot, "value": value,
                "direction": direction, "source": source, "confidence_delta": confidence_delta,
                "ids": ids,
            },
        )

    def set_inferred(self, *, user_id: UUID, dimension: str, slot: str | None, value: str,
                     direction: str, confidence: int, evidence_event_ids: list[UUID]) -> dict | None:
        """배치 전용 — 기간 안의 이벤트로 다시 센 순 횟수를 그대로 기록한다(더하지 않는다, 그래서 재실행해도 같다).
        직접 말한 행(explicit_chat)은 건드리지 않고 None. 무시(dismissed)한 신호는 근거에 새 이벤트가 있을 때만
        되살린다. 바뀐 것이 없으면 None — 배치가 갱신 건수를 셀 수 있게."""
        return self._one(
            """INSERT INTO identity.preference_signal AS ps
               (user_id, dimension, slot, value, direction, source, confidence, evidence_event_ids)
               VALUES (%(user_id)s, %(dimension)s, %(slot)s, %(value)s, %(direction)s, 'inferred_swap',
                       %(confidence)s, %(ids)s::uuid[])
               ON CONFLICT (user_id, dimension, slot, value) DO UPDATE SET
                   direction = EXCLUDED.direction,
                   confidence = EXCLUDED.confidence,
                   status = CASE WHEN EXCLUDED.evidence_event_ids <@ ps.evidence_event_ids THEN ps.status ELSE 'active' END,
                   evidence_event_ids = EXCLUDED.evidence_event_ids,
                   last_observed_at = CASE WHEN EXCLUDED.evidence_event_ids <@ ps.evidence_event_ids
                                           THEN ps.last_observed_at ELSE now() END
               WHERE ps.source <> 'explicit_chat'
                 AND ((ps.direction, ps.confidence) IS DISTINCT FROM (EXCLUDED.direction, EXCLUDED.confidence)
                      OR NOT (EXCLUDED.evidence_event_ids <@ ps.evidence_event_ids
                              AND ps.evidence_event_ids <@ EXCLUDED.evidence_event_ids))
               RETURNING *""",
            {"user_id": user_id, "dimension": dimension, "slot": slot, "value": value,
             "direction": direction, "confidence": confidence, "ids": list(evidence_event_ids)},
        )

    def inferred_rows(self, user_id: UUID | None = None) -> list[dict]:
        """행동에서 추론한 행(직접 말한 것 제외) — 배치가 이번에 관측되지 않은 행을 0 으로 내릴 때 쓴다."""
        return self._all(
            "SELECT * FROM identity.preference_signal WHERE source='inferred_swap' "
            "AND (%s::uuid IS NULL OR user_id=%s::uuid)", (user_id, user_id),
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
