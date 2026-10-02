"""planning.* 저장소."""
from __future__ import annotations

from uuid import UUID, uuid4
from psycopg.types.json import Jsonb

from src.db.base import Repo


# 견적 점검(타사 견적 비교 분석) 결과를 리비전에 붙여 두는 조건 키. 추천 입력(조건 값)이 아니라 결과라서
# load_full 이 조건 목록에서 빼고, 저장해도 lock_version 을 올리지 않는다(이미 끝난 추천을 stale 로 만들지 않는다).
QUOTE_REVIEW_KEY = "quote_review"
# "이어서 하기"로 조건을 가져온 원래 목록 id(A1). 이전 견적과 비교할 때(B1) 대상을 정하는 데만 쓴다 —
# 추천 입력이 아니므로 QUOTE_REVIEW_KEY 처럼 load_full 에서 빼고 lock_version 도 올리지 않는다.
RESUMED_FROM_KEY = "resumed_from"
# "견적 수정하기"로 복사해 온 원본 견적서 번호. 견적 리스트 히스토리가 "견적서 N에서 고쳐 시작"과 비교 대상을
# 정하는 데만 쓴다 — 추천 입력이 아니므로 위 둘처럼 load_full 에서 빼고 lock_version 도 올리지 않는다.
REVISED_FROM_KEY = "revised_from"
_NOT_CONDITIONS = (QUOTE_REVIEW_KEY, RESUMED_FROM_KEY, REVISED_FROM_KEY)
_NOT_CONDITIONS_SQL = ", ".join(["%s"] * len(_NOT_CONDITIONS))


class PlanRepo(Repo):
    def published_domain_version(self, category: str) -> dict | None:
        return self._one(
            "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE d.code=%s AND d.status='active' ORDER BY dv.version_no DESC LIMIT 1", (category,)
        )

    def bind_domain_version(self, revision_id: UUID, category: str) -> None:
        version = self.published_domain_version(category)
        if version is None:
            raise ValueError(f"published_domain_not_found:{category}")
        self._exec("UPDATE planning.plan_revision SET domain_version_id=%s, updated_at=now() WHERE id=%s", (version["id"], revision_id))
    def create_plan(self, conversation_id: UUID, name: str, owner_user_id: UUID | None) -> UUID:
        row = self._one("INSERT INTO planning.plan (conversation_id, name, owner_user_id) VALUES (%s, %s, %s) RETURNING id", (conversation_id, name, owner_user_id))
        return row["id"]

    def new_revision(self, plan_id: UUID, domain_version_id: UUID, name_snapshot: str) -> UUID:
        row = self._one("""INSERT INTO planning.plan_revision (plan_id, revision_no, domain_version_id, name_snapshot)
            SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s FROM planning.plan_revision WHERE plan_id=%s
            RETURNING id""", (plan_id, domain_version_id, name_snapshot, plan_id))
        return row["id"]

    def set_current_revision(self, plan_id: UUID, revision_id: UUID) -> None:
        row = self._one("UPDATE planning.plan SET current_revision_id=%s, updated_at=now() WHERE id=%s AND EXISTS (SELECT 1 FROM planning.plan_revision WHERE id=%s AND plan_id=%s) RETURNING id", (revision_id, plan_id, revision_id, plan_id))
        if row is None:
            raise ValueError("revision does not belong to plan")

    def get_revision(self, revision_id: UUID) -> dict | None:
        return self._one(
            "SELECT r.*, p.name AS plan_name, p.conversation_id, p.owner_user_id, "
            "c.user_id, c.guest_session_hash, d.code AS category "
            "FROM planning.plan_revision r JOIN planning.plan p ON p.id=r.plan_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "JOIN config.domain_version dv ON dv.id=r.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE r.id=%s", (revision_id,))

    def get_current_revision(self, plan_id: UUID) -> dict | None:
        """소프트 삭제된 목록은 제외한다 — 일반 조회·추천·확정·리포트 전부 이 경로를 탄다."""
        return self._one(
            "SELECT r.*, p.name AS plan_name, p.conversation_id, p.owner_user_id, "
            "c.user_id, c.guest_session_hash, d.code AS category "
            "FROM planning.plan p JOIN planning.plan_revision r ON r.id=p.current_revision_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "JOIN config.domain_version dv ON dv.id=r.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE p.id=%s AND p.status='active'", (plan_id,))

    def list_owned(self, *, user_id: UUID | None, guest_session_hash: str | None,
                   limit: int | None = None, offset: int = 0) -> list[dict]:
        """사이드바 "내 장바구니" — 최근 수정순(§D-4-3).

        limit=None(기본)이면 예전처럼 전량 반환 — 지금 호출부는 전부 이 기본값을 쓴다.
        계정에 리스트가 아주 많을 때 전량 반환이 느려질 수 있어(발견 사항,
        docs/전체_테스트_시나리오_실행_기획.md §9) 호출부가 원하면 자를 수 있게만 열어 둔다."""
        clause = " LIMIT %s OFFSET %s" if limit is not None else ""
        params = (user_id, user_id, guest_session_hash, guest_session_hash)
        if limit is not None:
            params = params + (limit, offset)
        return self._all(
            "SELECT p.id AS list_id, p.name, p.updated_at, pr.id AS revision_id, pr.state, "
            "d.code AS category, "
            # 대화 목록(패널)용: 첫 사용자 말과 마지막 활동 — 대화가 plan.updated_at 을 올리지 않는다
            "(SELECT m.content FROM identity.message m WHERE m.conversation_id=p.conversation_id "
            "  AND m.role='user' ORDER BY m.created_at LIMIT 1) AS first_message, "
            "GREATEST(p.updated_at, (SELECT max(m.created_at) FROM identity.message m "
            "  WHERE m.conversation_id=p.conversation_id)) AS last_active_at, "
            "EXISTS(SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.condition_key='category' AND pc.status='active') AS has_category, "
            "EXISTS(SELECT 1 FROM engine.recommendation_run rr WHERE rr.revision_id=pr.id "
            "  AND rr.status='completed') AS has_result "
            "FROM planning.plan p "
            "JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
            "JOIN config.domain_version dv ON dv.id=pr.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "WHERE p.status='active' AND ("
            "  (%s::uuid IS NOT NULL AND c.user_id=%s) OR "
            "  (%s::text IS NOT NULL AND c.guest_session_hash=%s)"
            ") ORDER BY p.updated_at DESC" + clause,
            params,
        )

    def confirmed_revisions(self, plan_id: UUID) -> list[dict]:
        """한 목록의 확정된 견적서들(오래된 것부터). 견적서 하나 = 확정된 revision 하나.
        개별 삭제된(deleted_at) 견적서는 빼고 낸다(개발요청 10번).
        item_count는 본체 부품 수만(개발요청 11번), peripheral_count는 주변기기 수다."""
        return self._all(
            "SELECT r.id, r.revision_no, r.name_snapshot, r.confirmed_at, r.confirmed_total, r.planned_purchase_at, "
            "(SELECT count(*) FROM planning.purchase_line l WHERE l.revision_id=r.id) AS item_count, "
            "(SELECT count(*) FROM planning.peripheral_line pl WHERE pl.revision_id=r.id) AS peripheral_count "
            "FROM planning.plan_revision r WHERE r.plan_id=%s AND r.state='confirmed' AND r.deleted_at IS NULL "
            "ORDER BY r.revision_no",
            (plan_id,),
        )

    def get_revision_by_no(self, plan_id: UUID, revision_no: int) -> dict | None:
        """개별 삭제된 견적서는 번호로도 더는 못 찾는다(개발요청 10번) — 목록에서 사라진 것과 같은 의미."""
        row = self._one(
            "SELECT id FROM planning.plan_revision WHERE plan_id=%s AND revision_no=%s AND deleted_at IS NULL",
            (plan_id, revision_no),
        )
        return self.get_revision(row["id"]) if row else None

    def soft_delete_revision(self, revision_id: UUID) -> bool:
        """견적서 하나만 삭제(개발요청 10번) — 확정된 것만, 이미 지운 것은 다시 지우지 않는다."""
        row = self._one(
            "UPDATE planning.plan_revision SET deleted_at=now(), updated_at=now() "
            "WHERE id=%s AND state='confirmed' AND deleted_at IS NULL RETURNING id",
            (revision_id,),
        )
        return row is not None

    def rename_revision(self, revision_id: UUID, name: str) -> bool:
        """견적서 하나의 name_snapshot만 바꾼다(개발요청 10번) — 대화 이름(plan.name)과는 별개."""
        row = self._one(
            "UPDATE planning.plan_revision SET name_snapshot=%s, updated_at=now() "
            "WHERE id=%s AND state='confirmed' AND deleted_at IS NULL RETURNING id",
            (name, revision_id),
        )
        return row is not None

    def clone_revision(self, plan_id: UUID, source_revision_id: UUID) -> UUID:
        """source 의 도메인 버전·활성 조건과, 있으면 추천 결과(부품 구성)까지 가진 새 draft revision(다음
        번호). 현재 revision 으로 바꾸는 건 호출자 몫.

        개발요청 8번("견적 수정하기"): 확정본을 그대로 열어서 이어서 바꿀 수 있어야 하므로, 조건만
        복사하던 예전 동작에 추천 결과(노드·요구사항·recommendation_run·candidate·validation_result)
        복사를 더했다. 가격은 원본 확정 시점의 offer_observation_id를 그대로 가리키므로 "확정 당시
        가격 유지"가 기본 동작이다(현재가로 갱신하지 않는다) — 재추천·재검증을 하기 전까지는."""
        source = self.get_revision(source_revision_id)
        new_id = self.new_revision(plan_id, source["domain_version_id"], source["name_snapshot"])
        self._exec(
            "INSERT INTO planning.plan_condition (revision_id, condition_key, value, origin, source_message_id) "
            "SELECT %s, condition_key, value, origin, source_message_id FROM planning.plan_condition "
            "WHERE revision_id=%s AND status='active'",
            (new_id, source_revision_id),
        )
        self._clone_recommendation_result(source_revision_id, new_id)
        self.upsert_condition(new_id, REVISED_FROM_KEY, {"value": source["revision_no"]}, "inferred",
                              bump_version=False)
        return new_id

    def _clone_recommendation_result(self, source_revision_id: UUID, new_revision_id: UUID) -> None:
        nodes = self._all("SELECT * FROM planning.plan_node WHERE revision_id=%s", (source_revision_id,))
        node_id_map = {n["id"]: uuid4() for n in nodes}
        for n in nodes:
            self._exec(
                "INSERT INTO planning.plan_node (id, revision_id, parent_id, node_type, template_key, name, "
                "position, context) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (node_id_map[n["id"]], new_revision_id,
                 node_id_map.get(n["parent_id"]) if n["parent_id"] else None,
                 n["node_type"], n["template_key"], n["name"], n["position"], Jsonb(n["context"])),
            )

        requirements = self._all("SELECT * FROM planning.requirement WHERE revision_id=%s", (source_revision_id,))
        req_id_map: dict[UUID, UUID] = {}
        for r in requirements:
            row = self._one(
                "INSERT INTO planning.requirement (revision_id, node_id, quantity, unit_code, required, "
                "needed_at, timing_context, match_spec, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (new_revision_id, node_id_map[r["node_id"]], r["quantity"], r["unit_code"], r["required"],
                 r["needed_at"], Jsonb(r["timing_context"]), Jsonb(r["match_spec"]), r["status"]),
            )
            req_id_map[r["id"]] = row["id"]

        run = self._one(
            "SELECT * FROM engine.recommendation_run WHERE revision_id=%s ORDER BY created_at DESC LIMIT 1",
            (source_revision_id,),
        )
        if run is None:
            return  # 확정 전 추천을 한 번도 안 받은 revision(있을 수 없지만) — 복사할 결과가 없다
        new_run = self._one(
            "INSERT INTO engine.recommendation_run (revision_id, domain_version_id, input_snapshot, input_hash, "
            "draft_lock_version, engine_versions, status, completed_at, explanation_status, "
            "explanation_headline, explanation_text, reasoning_log) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (new_revision_id, run["domain_version_id"], Jsonb(run["input_snapshot"]), run["input_hash"],
             run["draft_lock_version"], Jsonb(run["engine_versions"]), run["status"], run["completed_at"],
             run["explanation_status"], run["explanation_headline"], run["explanation_text"],
             Jsonb(run["reasoning_log"])),
        )
        new_run_id = new_run["id"]

        candidates = self._all(
            "SELECT * FROM engine.recommendation_candidate WHERE run_id=%s", (run["id"],))
        for c in candidates:
            self._exec(
                "INSERT INTO engine.recommendation_candidate (run_id, requirement_id, variant_id, "
                "offer_observation_id, result, score, score_method_version, reason, reason_status, "
                "evidence_refs, selected, qty, timing, checks, checks_status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (new_run_id, req_id_map[c["requirement_id"]], c["variant_id"], c["offer_observation_id"],
                 c["result"], c["score"], c["score_method_version"], c["reason"], c["reason_status"],
                 Jsonb(c["evidence_refs"]), c["selected"], c["qty"], c["timing"], c["checks"],
                 c["checks_status"]),
            )

        validations = self._all("SELECT * FROM engine.validation_result WHERE run_id=%s", (run["id"],))
        for v in validations:
            self._exec(
                "INSERT INTO engine.validation_result (run_id, rule_key, rule_version, executor_version, "
                "status, severity, measured_values, threshold, message, checked_at, issues) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (new_run_id, v["rule_key"], v["rule_version"], v["executor_version"], v["status"],
                 v["severity"], Jsonb(v["measured_values"]), Jsonb(v["threshold"]), v["message"],
                 v["checked_at"], Jsonb(v["issues"])),
            )

    def latest_previous(self, *, user_id: UUID | None, guest_session_hash: str | None, category: str,
                        mode: str | None = None, exclude_list_id: UUID | None = None,
                        require_result: bool = False) -> dict | None:
        """같은 사용자(로그인 계정 또는 게스트 토큰)의 가장 최근 다른 목록 — 같은 카테고리(·mode)이고
        category·mode 말고도 채운 조건이 하나 이상 있는 것만. 새 세션에서 "지난번 조건으로 이어서"를 묻는 데 쓴다.
        require_result 면 완료된 추천 실행이 있는 목록만(이전 견적과 구성 비교용)."""
        return self._one(
            "SELECT p.id AS list_id, p.name, pr.id AS revision_id, pr.state, "
            "GREATEST(p.updated_at, pr.updated_at) AS last_active_at "
            "FROM planning.plan p "
            "JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
            "JOIN identity.conversation c ON c.id=p.conversation_id "
            "WHERE p.status='active' AND (%s::uuid IS NULL OR p.id<>%s) AND ("
            "  (%s::uuid IS NOT NULL AND c.user_id=%s) OR "
            "  (%s::uuid IS NULL AND %s::text IS NOT NULL AND c.guest_session_hash=%s)"
            ") AND EXISTS (SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.status='active' AND pc.condition_key='category' AND pc.value->>'value'=%s) "
            "AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.status='active' AND pc.condition_key='mode' AND pc.value->>'value'=%s)) "
            "AND EXISTS (SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            f"  AND pc.status='active' AND pc.condition_key NOT IN ('category', 'mode', {_NOT_CONDITIONS_SQL}) "
            "  AND pc.value->'value' IS NOT NULL AND pc.value->'value'<>'null'::jsonb) "
            "AND (NOT %s OR EXISTS (SELECT 1 FROM engine.recommendation_run rr WHERE rr.revision_id=pr.id "
            "  AND rr.status='completed')) "
            "ORDER BY last_active_at DESC LIMIT 1",
            (exclude_list_id, exclude_list_id, user_id, user_id, user_id, guest_session_hash, guest_session_hash,
             category, mode, mode, *_NOT_CONDITIONS, require_result),
        )

    def get_summary(self, list_id: UUID) -> dict | None:
        """PATCH /lists/{id} 응답(ListSummary)용 — list_owned와 같은 모양의 단건 조회."""
        return self._one(
            "SELECT p.id AS list_id, p.name, p.updated_at, pr.id AS revision_id, pr.state, "
            "d.code AS category, "
            "EXISTS(SELECT 1 FROM planning.plan_condition pc WHERE pc.revision_id=pr.id "
            "  AND pc.condition_key='category' AND pc.status='active') AS has_category, "
            "EXISTS(SELECT 1 FROM engine.recommendation_run rr WHERE rr.revision_id=pr.id "
            "  AND rr.status='completed') AS has_result "
            "FROM planning.plan p "
            "JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
            "JOIN config.domain_version dv ON dv.id=pr.domain_version_id "
            "JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE p.id=%s",
            (list_id,),
        )

    def rename(self, list_id: UUID, name: str) -> None:
        self._exec("UPDATE planning.plan SET name=%s, updated_at=now() WHERE id=%s", (name, list_id))

    def soft_delete(self, list_id: UUID) -> None:
        self._exec(
            "UPDATE planning.plan SET status='deleted', deleted_at=now(), updated_at=now() "
            "WHERE id=%s AND status='active'",
            (list_id,),
        )

    def confirm_revision(self, revision_id: UUID, *, confirmed_total, planned_purchase_at,
                         target_amount, memo: str, name: str | None = None) -> bool:
        """draft → confirmed. 이미 confirmed면 아무것도 안 하고 False.

        name 을 주면 name_snapshot 도 그 이름으로 굳힌다 — 리포트(get_report)가 읽는 이름이라, 안 바꾸면
        확정 때 사용자가 붙인 이름이 목록(plan.name)에는 있고 리포트에는 기본 이름으로 남는다."""
        row = self._one(
            "UPDATE planning.plan_revision SET state='confirmed', confirmed_at=now(), "
            "confirmed_total=%s, planned_purchase_at=%s, target_amount=%s, memo=%s, "
            "name_snapshot=COALESCE(%s, name_snapshot), updated_at=now() "
            "WHERE id=%s AND state='draft' RETURNING id",
            (confirmed_total, planned_purchase_at, target_amount, memo, name, revision_id),
        )
        return row is not None

    def add_purchase_line(self, revision_id: UUID, offer_id: UUID, offer_observation_id: UUID,
                          amount: int, snapshot: dict, pack_count: int = 1) -> UUID:
        """확정 시점에 후보를 얼려서 기록 — 이후 추천 결과가 바뀌어도 리포트는 그대로다.
        amount 는 줄 합계(단가 × pack_count)다 — 확정 총액(confirmed_total)이 줄 합계의 합과 같다."""
        row = self._one(
            "INSERT INTO planning.purchase_line "
            "(revision_id, offer_id, selected_observation_id, pack_count, line_amount, snapshot) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (revision_id, offer_id, offer_observation_id, pack_count, amount, Jsonb(snapshot)),
        )
        return row["id"]

    def list_purchase_lines(self, revision_id: UUID) -> list[dict]:
        return self._all(
            "SELECT pack_count, line_amount, snapshot FROM planning.purchase_line "
            "WHERE revision_id=%s ORDER BY created_at",
            (revision_id,),
        )

    def add_peripheral_line(self, revision_id: UUID, kind: str, variant_id: UUID,
                            amount: int, snapshot: dict, pack_count: int = 1) -> UUID:
        """확정 시점에 주변기기 선택을 얼려서 기록(개발요청 11번) — purchase_line과 같은 원칙,
        실제 offer가 없어(참고가뿐) 별도 테이블."""
        row = self._one(
            "INSERT INTO planning.peripheral_line "
            "(revision_id, kind, variant_id, pack_count, line_amount, snapshot) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (revision_id, kind, variant_id, pack_count, amount, Jsonb(snapshot)),
        )
        return row["id"]

    def list_peripheral_lines(self, revision_id: UUID) -> list[dict]:
        return self._all(
            "SELECT kind, pack_count, line_amount, snapshot FROM planning.peripheral_line "
            "WHERE revision_id=%s ORDER BY created_at",
            (revision_id,),
        )

    def count_peripheral_lines(self, revision_id: UUID) -> int:
        row = self._one(
            "SELECT count(*) AS n FROM planning.peripheral_line WHERE revision_id=%s", (revision_id,)
        )
        return int(row["n"])

    def lock_revision(self, revision_id: UUID) -> None:
        """같은 리비전의 조건·요구사항 변경을 하나의 행 잠금으로 직렬화한다."""
        self._one("SELECT id FROM planning.plan_revision WHERE id=%s FOR UPDATE", (revision_id,))

    def upsert_condition(self, revision_id: UUID, key: str, value: dict, origin: str, source_message_id: UUID | None = None,
                         *, bump_version: bool = True) -> UUID:
        self.lock_revision(revision_id)
        old = self._one("SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active' FOR UPDATE", (revision_id, key))
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        row = self._one("INSERT INTO planning.plan_condition (revision_id, condition_key, value, origin, source_message_id, supersedes_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (revision_id, key, Jsonb(value), origin, source_message_id, old["id"] if old else None))
        if bump_version:
            self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))
        return row["id"]

    def clear_condition(self, revision_id: UUID, key: str) -> None:
        self.lock_revision(revision_id)
        old = self._one(
            "SELECT id FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s AND status='active'",
            (revision_id, key),
        )
        if old:
            self._exec("UPDATE planning.plan_condition SET status='superseded', updated_at=now() WHERE id=%s", (old["id"],))
        self._exec("UPDATE planning.plan_revision SET lock_version=lock_version+1, updated_at=now() WHERE id=%s AND state='draft'", (revision_id,))

    def add_node(self, revision_id: UUID, node_type: str, template_key: str, name: str,
                 parent_id: UUID | None = None, position: int = 0) -> UUID:
        row = self._one(
            """INSERT INTO planning.plan_node (revision_id, parent_id, node_type, template_key, name, position)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (revision_id, parent_id, node_type, template_key, name, position),
        )
        return row["id"]

    def ensure_node(self, revision_id: UUID, template_key: str, name: str, *, position: int = 0) -> UUID:
        """template_key 로 슬롯 노드 1개 보장 (없으면 생성)."""
        row = self._one(
            "SELECT id FROM planning.plan_node WHERE revision_id=%s AND template_key=%s",
            (revision_id, template_key),
        )
        if row is not None:
            return row["id"]
        return self.add_node(revision_id, "slot", template_key, name, position=position)

    def ensure_requirement(self, revision_id: UUID, node_id: UUID, match_spec: dict) -> UUID:
        """슬롯 노드당 requirement 1개 보장 (없으면 생성, 있으면 match_spec 갱신)."""
        row = self._one(
            "SELECT id FROM planning.requirement WHERE revision_id=%s AND node_id=%s",
            (revision_id, node_id),
        )
        if row is not None:
            self._exec(
                "UPDATE planning.requirement SET match_spec=%s, status='active' WHERE id=%s",
                (Jsonb(match_spec), row["id"]),
            )
            return row["id"]
        row = self._one(
            """INSERT INTO planning.requirement (revision_id, node_id, match_spec)
            VALUES (%s, %s, %s) RETURNING id""",
            (revision_id, node_id, Jsonb(match_spec)),
        )
        return row["id"]

    def active_condition(self, revision_id: UUID, condition_key: str) -> dict | None:
        return self._one(
            "SELECT id, value FROM planning.plan_condition WHERE revision_id=%s AND condition_key=%s "
            "AND status='active'",
            (revision_id, condition_key),
        )

    def load_full(self, revision_id: UUID) -> dict:
        revision = self.get_revision(revision_id)
        if revision is None:
            raise ValueError("revision not found")
        revision["conditions"] = self._all(f"SELECT condition_key, value, origin FROM planning.plan_condition WHERE revision_id=%s AND status='active' AND condition_key NOT IN ({_NOT_CONDITIONS_SQL}) ORDER BY created_at", (revision_id, *_NOT_CONDITIONS))
        revision["nodes"] = self._all("SELECT * FROM planning.plan_node WHERE revision_id=%s ORDER BY position, created_at", (revision_id,))
        revision["requirements"] = self._all("SELECT * FROM planning.requirement WHERE revision_id=%s AND status='active'", (revision_id,))
        return revision
