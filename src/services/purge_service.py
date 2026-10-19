"""영구 삭제(재기획 6.7) — 사용자가 지운(soft delete) 대화·견적서를 보관 기간이 지나면, 또는 사용자가 "완전히 삭제"를 고르면 DB 에서 지운다.

외래 키가 대부분 RESTRICT 라서 **딸린 행을 자식부터** 지운다. 순서(견적서 하나 기준):
  알림(이벤트 → 평가 → 감시) → 추천 실행의 딸린 행(후보·검증·피드백·리뷰 프로필) → 추천 실행 → 구매·주변기기·유지 부품 줄 → 요구사항·노드 → 조건
  → (커뮤니티에 올린 구성이 이 견적서를 가리키면 그 연결만 끊는다) → 견적서.
대화 전체를 지울 때는 그 뒤에 plan, 메시지, 대화를 지운다.

보존하지 않는 것(가정, 팀 결정 필요): 추천 학습용 피드백 로그(engine.feedback_event)도 plan 을 가리키므로 함께 지운다 — 익명화해 남기려면 FK 를 풀어야 한다.
사용자가 커뮤니티에 올린 글·구성은 지우지 않는다(견적서와의 연결만 끊는다).
"""
from __future__ import annotations

import logging
from uuid import UUID

from src.db.base import Repo

log = logging.getLogger(__name__)


class PurgeRepo(Repo):
    def revision_ids(self, plan_id: UUID) -> list[UUID]:
        return [r["id"] for r in self._all("SELECT id FROM planning.plan_revision WHERE plan_id=%s", (plan_id,))]

    def purge_revision_rows(self, revision_id: UUID) -> dict[str, int]:
        """견적서 하나의 딸린 행과 견적서 자신. 호출 전에 plan 의 current_revision 이 이 견적서를 가리키지 않아야 한다."""
        counts: dict[str, int] = {}

        def run(label: str, sql: str, params: tuple) -> None:
            counts[label] = self.conn.execute(sql, params).rowcount or 0

        rid = (revision_id,)
        runs = "SELECT id FROM engine.recommendation_run WHERE revision_id=%s"
        run("feedback_event", f"DELETE FROM engine.feedback_event WHERE revision_id=%s OR recommendation_run_id IN ({runs})", rid + rid)
        run("recommendation_candidate", f"DELETE FROM engine.recommendation_candidate WHERE run_id IN ({runs})", rid)
        run("validation_result", f"DELETE FROM engine.validation_result WHERE run_id IN ({runs})", rid)
        run("review_requirement_profile", f"DELETE FROM engine.review_requirement_profile WHERE run_id IN ({runs})", rid)
        run("recommendation_run", "DELETE FROM engine.recommendation_run WHERE revision_id=%s", rid)
        run("purchase_line", "DELETE FROM planning.purchase_line WHERE revision_id=%s", rid)
        run("peripheral_line", "DELETE FROM planning.peripheral_line WHERE revision_id=%s", rid)
        run("kept_part_line", "DELETE FROM planning.kept_part_line WHERE revision_id=%s", rid)
        run("requirement", "DELETE FROM planning.requirement WHERE revision_id=%s", rid)
        run("plan_node", "DELETE FROM planning.plan_node WHERE revision_id=%s", rid)
        run("plan_condition", "DELETE FROM planning.plan_condition WHERE revision_id=%s", rid)
        run("community_link", "UPDATE community.pc_build_version SET source_plan_revision_id=NULL WHERE source_plan_revision_id=%s", rid)
        run("plan_revision", "DELETE FROM planning.plan_revision WHERE id=%s", rid)
        return counts

    def purge_plan_rows(self, plan_id: UUID) -> dict[str, int]:
        plan = self._one("SELECT conversation_id FROM planning.plan WHERE id=%s", (plan_id,))
        if plan is None:
            return {}
        self._exec("UPDATE planning.plan SET current_revision_id=NULL WHERE id=%s", (plan_id,))
        totals: dict[str, int] = {}
        for revision_id in self.revision_ids(plan_id):
            for key, n in self.purge_revision_rows(revision_id).items():
                totals[key] = totals.get(key, 0) + n
        self._exec("DELETE FROM engine.feedback_event WHERE plan_id=%s", (plan_id,))
        self._exec("DELETE FROM planning.plan_extras WHERE plan_id=%s", (plan_id,))
        self._exec("DELETE FROM planning.plan WHERE id=%s", (plan_id,))
        conversation_id = plan["conversation_id"]
        shared = self._one("SELECT 1 AS x FROM planning.plan WHERE conversation_id=%s LIMIT 1", (conversation_id,))
        if shared is None:                                   # 다른 목록이 같은 대화를 쓰지 않을 때만 대화와 메시지를 지운다
            self._exec("DELETE FROM identity.message WHERE conversation_id=%s", (conversation_id,))
            self._exec("DELETE FROM identity.conversation WHERE id=%s", (conversation_id,))
            totals["conversation"] = 1
        totals["plan"] = 1
        return totals

    def expired_plans(self, days: int) -> list[UUID]:
        return [r["id"] for r in self._all(
            "SELECT id FROM planning.plan WHERE status='deleted' AND deleted_at < now() - make_interval(days => %s)", (days,))]

    def expired_revisions(self, days: int) -> list[dict]:
        """개별로 지운 견적서 중 보관 기간이 지난 것 — 아직 plan 이 살아 있고 그 견적서가 현재 작업 견적서가 아닌 것만."""
        return self._all(
            "SELECT r.id, r.plan_id FROM planning.plan_revision r JOIN planning.plan p ON p.id=r.plan_id "
            "WHERE r.deleted_at IS NOT NULL AND r.deleted_at < now() - make_interval(days => %s) "
            "AND p.status='active' AND p.current_revision_id IS DISTINCT FROM r.id", (days,))


def purge_plan(conn, plan_id: UUID) -> dict[str, int]:
    """대화(목록) 하나와 딸린 모든 행을 영구 삭제한다."""
    counts = PurgeRepo(conn).purge_plan_rows(plan_id)
    log.info("purged plan %s: %s", plan_id, counts)
    return counts


def purge_revision(conn, revision_id: UUID) -> dict[str, int]:
    """견적서 하나와 딸린 행을 영구 삭제한다(plan 은 남는다)."""
    return PurgeRepo(conn).purge_revision_rows(revision_id)


def purge_expired(conn, days: int) -> dict[str, int]:
    """보관 기간(days)이 지난 삭제 표시 항목을 영구 삭제한다. {"plans": n, "revisions": n}."""
    repo = PurgeRepo(conn)
    plans = repo.expired_plans(days)
    for plan_id in plans:
        with conn.transaction():                             # 하나가 실패해도 다른 항목은 계속한다(바깥 트랜잭션 안에서는 savepoint)
            repo.purge_plan_rows(plan_id)
    revisions = repo.expired_revisions(days)
    for row in revisions:
        with conn.transaction():
            repo.purge_revision_rows(row["id"])
    return {"plans": len(plans), "revisions": len(revisions)}
