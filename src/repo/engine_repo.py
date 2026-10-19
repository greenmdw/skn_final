"""engine recommendation 실행 결과 저장소."""
from __future__ import annotations
from uuid import UUID
from psycopg.types.json import Jsonb
from src.db.base import Repo
from src.errors import Conflict

class EngineRepo(Repo):
    def start_run(self, revision_id: UUID, domain_version_id: UUID, *, input_snapshot: dict, input_hash: str, draft_lock_version: int, engine_versions: dict) -> UUID:
        row = self._one("""INSERT INTO engine.recommendation_run (revision_id, domain_version_id, input_snapshot, input_hash, draft_lock_version, engine_versions, status)
        VALUES (%s,%s,%s,%s,%s,%s,'running') RETURNING id""", (revision_id, domain_version_id, Jsonb(input_snapshot), input_hash, draft_lock_version, Jsonb(engine_versions)))
        return row["id"]
    def complete_run(self, run_id: UUID, status: str = "completed") -> None:
        if status not in {"completed", "failed", "stale"}: raise ValueError("invalid terminal run status")
        run = self._one("SELECT r.*, p.lock_version FROM engine.recommendation_run r JOIN planning.plan_revision p ON p.id=r.revision_id WHERE r.id=%s FOR UPDATE", (run_id,))
        if run is None: raise ValueError("recommendation run not found")
        if run["status"] != "running": raise Conflict("추천 실행이 이미 종료되었습니다.")
        terminal = "stale" if status == "completed" and run["lock_version"] != run["draft_lock_version"] else status
        self._exec("UPDATE engine.recommendation_run SET status=%s, completed_at=now(), updated_at=now() WHERE id=%s", (terminal, run_id))
        if terminal == "stale": raise Conflict("추천 도중 조건이 변경되었습니다.")
    def add_candidate(self, run_id: UUID, requirement_id: UUID, variant_id: UUID, *, result: str, score=None, score_method_version: str | None = None, reason: str | None = None, offer_observation_id: UUID | None = None, qty: int = 1) -> UUID:
        # PostgreSQL has individual FKs for run and requirement, but cannot express
        # that they belong to the same revision with those columns alone.
        scope = self._one(
            """SELECT 1 FROM engine.recommendation_run run
               JOIN planning.requirement req ON req.id=%s
               WHERE run.id=%s AND req.revision_id=run.revision_id""",
            (requirement_id, run_id),
        )
        if scope is None:
            raise ValueError("cross_revision_candidate_rejected")
        reason_status = "ready" if reason is not None else "pending"
        row=self._one("""INSERT INTO engine.recommendation_candidate (run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status,qty)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,requirement_id,variant_id,offer_observation_id,result,score,score_method_version,reason,reason_status,qty)); return row["id"]
    def update_candidate_reason(self, candidate_id: UUID, reason: str, variant_id: UUID | None = None) -> bool:
        """[5] 설명 문장이 부품표 확정보다 늦게 끝날 때, 나중에 reason만 채워 넣는다.

        variant_id 를 주면 그 상품을 가리키는 행일 때만 채운다 — 후처리 도중 사용자가 부품을 교체했으면 행의
        variant_id 가 이미 바뀌어 있어서, 이전 상품의 문장이 새 상품(교체 문장)을 덮어쓰지 않는다. 채웠는지(bool)를 돌려준다."""
        sql, params = "UPDATE engine.recommendation_candidate SET reason=%s, reason_status='ready' WHERE id=%s", [reason, candidate_id]
        if variant_id is not None:
            sql += " AND variant_id=%s"
            params.append(variant_id)
        return self.conn.execute(sql, params).rowcount > 0
    def fail_candidate_reason(self, candidate_id: UUID, variant_id: UUID | None = None) -> bool:
        """[5] 실패 — reason은 NULL로 남기고(제약상 ready만 값을 가짐) 상태만 failed로.

        아직 pending 인 행만 바꾼다. 교체가 이미 문장을 채운(ready) 행을 failed 로 바꾸면 reason_content_check 제약 위반이다.
        variant_id 를 주면 그 상품을 가리키는 행일 때만 바꾼다. 바꿨는지(bool)를 돌려준다."""
        sql, params = "UPDATE engine.recommendation_candidate SET reason_status='failed' WHERE id=%s AND reason_status='pending'", [candidate_id]
        if variant_id is not None:
            sql += " AND variant_id=%s"
            params.append(variant_id)
        return self.conn.execute(sql, params).rowcount > 0
    def update_candidate_checks(self, candidate_id: UUID, checks: str, variant_id: UUID | None = None) -> bool:
        """부품 사용 가이드 RAG 검색 결과 — "구매 전 확인" 문장을 채운다. variant_id 를 주면 그 상품을 가리키는 행일 때만
        채운다(이전 상품의 가이드가 교체된 새 상품에 붙지 않게). 채웠는지(bool)를 돌려준다."""
        sql, params = "UPDATE engine.recommendation_candidate SET checks=%s, checks_status='ready' WHERE id=%s", [checks, candidate_id]
        if variant_id is not None:
            sql += " AND variant_id=%s"
            params.append(variant_id)
        return self.conn.execute(sql, params).rowcount > 0
    def fail_candidate_checks(self, candidate_id: UUID, variant_id: UUID | None = None) -> bool:
        """가이드 검색/임베딩 실패 — checks는 NULL로 남기고 상태만 failed로. 아직 pending 인 행만 바꾼다(variant_id 를 주면
        그 상품을 가리키는 행일 때만). 바꿨는지(bool)를 돌려준다."""
        sql, params = "UPDATE engine.recommendation_candidate SET checks_status='failed' WHERE id=%s AND checks_status='pending'", [candidate_id]
        if variant_id is not None:
            sql += " AND variant_id=%s"
            params.append(variant_id)
        return self.conn.execute(sql, params).rowcount > 0
    def add_validation(self, run_id: UUID, *, rule_key: str, rule_version: str, executor_version: str, status: str, severity: str, measured_values: dict, threshold: dict, message: str, checked_at, issues: list | None = None) -> UUID:
        row=self._one("""INSERT INTO engine.validation_result (run_id,rule_key,rule_version,executor_version,status,severity,measured_values,threshold,message,checked_at,issues)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(run_id,rule_key,rule_version,executor_version,status,severity,Jsonb(measured_values),Jsonb(threshold),message,checked_at,Jsonb(issues or []))); return row["id"]
    def delete_validations(self, run_id: UUID) -> int:
        """run 의 검증 결과를 지운다. 세트 재검증(교체·담기 뒤)이 규칙 스캐폴드 결과를 통째로 다시 쓸 때 쓴다.
        근거·대상 표(validation_evidence/target)는 0012 에서 없어졌고 이 행을 가리키는 것이 없다."""
        return self.conn.execute("DELETE FROM engine.validation_result WHERE run_id=%s", (run_id,)).rowcount
    def set_explanation(self, run_id: UUID, *, headline: str, text: str, reasoning_log: list) -> None:
        from src.engine.build_margins import MARGINS_STEP
        from src.engine.eligibility import ELIGIBILITY_STEP
        from src.engine.omitted_slots import OMITTED_SLOTS_STEP
        from src.services.recommendation_review_snapshot import SNAPSHOT_STEP
        # 리뷰 snapshot·추천 적격성·조합 여유·견적 구성 슬롯(뺀 GPU·쿨러) 단계는 설명과 별개로 먼저 저장된다 — 설명 trace 가 지우거나 중복시키지 않는다.
        kept = (SNAPSHOT_STEP, ELIGIBILITY_STEP, MARGINS_STEP, OMITTED_SLOTS_STEP)
        trace = [step for step in reasoning_log if step.get("step") not in kept]
        self._exec(
            """UPDATE engine.recommendation_run
            SET explanation_status='ready', explanation_headline=%s, explanation_text=%s,
                reasoning_log=COALESCE((SELECT jsonb_agg(entry)
                    FROM jsonb_array_elements(engine.recommendation_run.reasoning_log) entry
                    WHERE entry->>'step' = ANY(%s)), '[]'::jsonb) || %s::jsonb, updated_at=now()
            WHERE id=%s""",
            (headline, text, list(kept), Jsonb(trace), run_id),
        )
    def upsert_run_step(self, run_id: UUID, step: dict) -> None:
        """reasoning_log 에서 이름(step)이 같은 단계를 지우고 새로 덧붙인다(추천 적격성 단계의 저장·재검증 교체)."""
        self._exec(
            """UPDATE engine.recommendation_run
            SET reasoning_log=COALESCE((SELECT jsonb_agg(entry)
                    FROM jsonb_array_elements(engine.recommendation_run.reasoning_log) entry
                    WHERE entry->>'step' <> %s), '[]'::jsonb) || %s::jsonb, updated_at=now()
            WHERE id=%s""",
            (step["step"], Jsonb([step]), run_id),
        )
    def store_review_snapshot(self, run_id: UUID, step: dict) -> None:
        """Store before completing the build, independently of later explanation calls."""
        from src.services.recommendation_review_snapshot import SNAPSHOT_STEP
        updated = self.conn.execute(
            "UPDATE engine.recommendation_run SET reasoning_log=reasoning_log || %s::jsonb "
            "WHERE id=%s AND status='running' AND NOT EXISTS "
            "(SELECT 1 FROM jsonb_array_elements(reasoning_log) entry WHERE entry->>'step'=%s)",
            (Jsonb([step]), run_id, SNAPSHOT_STEP),
        ).rowcount
        if updated != 1:
            raise ValueError("review snapshot must be stored once on a running run")
    def fail_explanation(self, run_id: UUID) -> None:
        """[5] 실패 — headline/text는 NULL로 남기고(제약상 ready만 값을 가짐) 상태만 failed로.
        run.status는 건드리지 않는다 — 부품·가격·검증은 이미 complete_run으로 확정된 뒤다."""
        self._exec("UPDATE engine.recommendation_run SET explanation_status='failed', updated_at=now() WHERE id=%s",(run_id,))
    def get_run(self, run_id: UUID) -> dict | None:
        return self._one("SELECT * FROM engine.recommendation_run WHERE id=%s",(run_id,))
    def get_latest_run(self, revision_id: UUID) -> dict | None:
        return self._one("SELECT * FROM engine.recommendation_run WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1",(revision_id,))
    def get_latest_run_state(self, revision_id: UUID) -> dict | None:
        """가벼운 상태 조회용 — reasoning_log(리뷰 스냅샷 포함 수백 KB) 같은 큰 컬럼을 읽지 않는다."""
        return self._one("SELECT id, status, explanation_status, updated_at FROM engine.recommendation_run "
                         "WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1", (revision_id,))
    def get_candidate_states(self, run_id: UUID) -> list[dict]:
        """가벼운 상태 조회용 — 후보 행의 상태 컬럼만(상품·가격·리뷰 조인 없음)."""
        return self._all("SELECT id, variant_id, score, reason_status, checks_status, selected, qty, timing, updated_at "
                         "FROM engine.recommendation_candidate WHERE run_id=%s", (run_id,))
    # 폴링(GET /result)용 — reasoning_log(추천 한 건 약 236KB, 리뷰 계산 근거가 대부분)와 input_snapshot 을 읽지 않는다.
    # SELECT * 로 읽으면 DB 가 압축을 풀고 앱이 JSON 을 파싱하는 데 한 번에 약 17ms(큰 열 제외 0.3ms)가 들고, 폴링이 초당 수 회 몰린다.
    _RUN_LIGHT_COLUMNS = ("id, revision_id, domain_version_id, input_hash, draft_lock_version, engine_versions, status, completed_at, "
                          "created_at, updated_at, explanation_status, explanation_headline, explanation_text")

    def get_latest_run_light(self, revision_id: UUID) -> dict | None:
        return self._one(f"SELECT {self._RUN_LIGHT_COLUMNS} FROM engine.recommendation_run WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1", (revision_id,))

    def get_run_trace(self, run_id: UUID) -> list[dict]:
        """reasoning_log 중 리뷰 계산 snapshot 을 뺀 항목들(화면의 추적 기록). snapshot 은 get_run_snapshot_steps 로 따로 읽는다."""
        from src.services.recommendation_review_snapshot import SNAPSHOT_STEP
        row = self._one(
            "SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) AS steps FROM engine.recommendation_run r, jsonb_array_elements(r.reasoning_log) e "
            "WHERE r.id=%s AND e->>'step' <> %s", (run_id, SNAPSHOT_STEP))
        return list(row["steps"] or [])

    def get_run_step(self, run_id: UUID, step: str) -> dict | None:
        """reasoning_log 에서 이름이 같은 단계 하나만 읽는다(실패 사유처럼 작은 항목용 — 큰 snapshot 은 SQL 에서 걸러 앱으로 오지 않는다)."""
        row = self._one(
            "SELECT e AS step FROM engine.recommendation_run r, jsonb_array_elements(r.reasoning_log) e "
            "WHERE r.id=%s AND e->>'step' = %s LIMIT 1", (run_id, step))
        return row["step"] if row else None

    def get_run_steps(self, run_id: UUID, names: list[str]) -> dict[str, dict]:
        """이름이 names 에 있는 단계들만 {이름: 단계}로 읽는다(적격성·여유처럼 설명이 끝나기 전에도 보여 줄 작은 항목용 —
        큰 snapshot 은 SQL 에서 걸러 앱으로 오지 않는다). 같은 이름이 여럿이면 앞의 것."""
        rows = self._all(
            "SELECT e AS step FROM engine.recommendation_run r, jsonb_array_elements(r.reasoning_log) e "
            "WHERE r.id=%s AND e->>'step' = ANY(%s)", (run_id, list(names)))
        out: dict[str, dict] = {}
        for row in rows:
            out.setdefault(row["step"]["step"], row["step"])
        return out

    def get_run_snapshot_steps(self, run_id: UUID) -> list[dict]:
        from src.services.recommendation_review_snapshot import SNAPSHOT_STEP
        row = self._one(
            "SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) AS steps FROM engine.recommendation_run r, jsonb_array_elements(r.reasoning_log) e "
            "WHERE r.id=%s AND e->>'step' = %s", (run_id, SNAPSHOT_STEP))
        return list(row["steps"] or [])

    def has_running_run(self, revision_id: UUID) -> bool:
        row = self._one("SELECT 1 FROM engine.recommendation_run WHERE revision_id=%s AND status='running' LIMIT 1", (revision_id,))
        return row is not None
    def get_candidates(self, run_id: UUID) -> list[dict]:
        """후보 행(결과 품목). 순서는 결정적이다 — plan_node.position·created_at 은 한 run 안에서 대개 같으므로, 엔진이 품목을 만드는
        순서(카테고리 slot_structure)를 다음 기준으로 쓰고 목록에 없는 슬롯은 뒤에서 이름순으로 둔다. 마지막 기준은 후보 id 다.
        행이 UPDATE(교체·수량·이유)로 물리적으로 옮겨져도, 개정을 복제해도 같은 순서를 낸다."""
        from src.categories import load_category
        slot_order = list(load_category("computer").get("slot_structure") or [])
        return self._all("""
        SELECT c.*, p.id AS product_id, p.model AS product_key, p.product_type, v.id AS variant_id, v.variant_key,
               p.name AS product_name, p.brand, p.attributes, p.image_url,
               of.id AS offer_id, of.purchase_url, o.price, o.observed_at,
               n.template_key AS slot, n.name AS slot_label
        FROM engine.recommendation_candidate c
        JOIN catalog.product_variant v ON v.id=c.variant_id
        JOIN catalog.product p ON p.id=v.product_id
        LEFT JOIN catalog.offer_observation o ON o.id=c.offer_observation_id
        LEFT JOIN catalog.offer of ON of.id=o.offer_id
        JOIN planning.requirement r2 ON r2.id=c.requirement_id
        JOIN planning.plan_node n ON n.id=r2.node_id
        WHERE c.run_id=%s
        ORDER BY n.position, COALESCE(array_position(%s::text[], n.template_key), 1000), n.template_key, c.created_at, c.id""",
            (run_id, slot_order))
    def get_validations(self, run_id: UUID) -> list[dict]:
        return self._all("SELECT * FROM engine.validation_result WHERE run_id=%s ORDER BY created_at", (run_id,))
    def restore_candidate_score(self, candidate_id: UUID, *, score: float, score_method_version: str | None) -> None:
        """처음 추천한 상품으로 되돌렸을 때 그 상품의 추천 점수를 다시 적는다 — 교체가 지운 점수(update_candidate_variant)."""
        self._exec("UPDATE engine.recommendation_candidate SET score=%s, score_method_version=%s WHERE id=%s",
                   (score, score_method_version, candidate_id))
    def update_candidate_state(self, candidate_id: UUID, *, selected: bool | None = None,
                                qty: int | None = None, timing: str | None = None) -> None:
        sets, params = [], []
        if selected is not None:
            sets.append("selected=%s"); params.append(selected)
        if qty is not None:
            sets.append("qty=%s"); params.append(qty)
        if timing is not None:
            sets.append("timing=%s"); params.append(timing)
        if not sets:
            return
        params.append(candidate_id)
        self._exec(f"UPDATE engine.recommendation_candidate SET {', '.join(sets)} WHERE id=%s", params)
    def update_candidate_variant(self, candidate_id: UUID, *, variant_id: UUID,
                                  offer_observation_id: UUID | None) -> None:
        """후보 교체 — item_id(행 자체)는 그대로 두고 내용만 바꿔치기한다(계약: item_id 고정).
        점수·설명 문장·사용 가이드는 더 이상 새 상품을 반영하지 않으므로 pending으로 되돌린다(이전 상품의 가이드가 남지 않게)."""
        self._exec(
            "UPDATE engine.recommendation_candidate SET variant_id=%s, offer_observation_id=%s, "
            "score=NULL, score_method_version=NULL, reason=NULL, reason_status='pending', "
            "checks=NULL, checks_status='pending' WHERE id=%s",
            (variant_id, offer_observation_id, candidate_id),
        )

