"""사용기 분석 결과 저장소 — engine.peripheral_post_* 네 테이블의 SQL만 안다(0015_peripheral_post_evidence.sql).

무엇을 언제 분석할지(`community_post_intake`), 어떻게 이을지(`peripheral_post_pipeline`)는 이 파일의 책임이 아니다.
`IntakeStore`·`ObservationStore` 인터페이스를 DB 로 구현한 클래스도 여기 둔다.

벡터는 pgvector 어댑터 없이 텍스트 리터럴('[v1,v2,...]')로 보내고 `::vector` 로 캐스트한다(리뷰 임베딩 저장소와 같은 방식).
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from psycopg.rows import dict_row

from src.engine.peripheral_feel import FeelObservation
from src.repo.review_embedding_repo import _vector_literal
from src.services.community_post_intake import IntakeRecord


def _record(row: dict) -> IntakeRecord:
    return IntakeRecord(
        post_id=str(row["post_id"]), status=row["status"], requested_at=row["requested_at"], started_at=row["started_at"],
        processed_at=row["processed_at"], attempts=row["attempts"], last_error=row["last_error"],
        analyzed_hash=row["analyzed_hash"], truncated=row["truncated"],
    )


class DbIntakeStore:
    """`community_post_intake.IntakeStore` 의 DB 구현."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def get(self, post_id: str) -> IntakeRecord | None:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM engine.peripheral_post_intake WHERE post_id = %s", (post_id,))
            row = cur.fetchone()
        return _record(row) if row else None

    def put(self, record: IntakeRecord) -> None:
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute("SELECT attempts FROM engine.peripheral_post_intake WHERE post_id = %s", (record.post_id,))
                before = cur.fetchone()
                cur.execute(
                    """INSERT INTO engine.peripheral_post_intake
                         (post_id, status, requested_at, started_at, processed_at, attempts, last_error, analyzed_hash, truncated)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (post_id) DO UPDATE SET status = EXCLUDED.status, requested_at = EXCLUDED.requested_at,
                         started_at = EXCLUDED.started_at, processed_at = EXCLUDED.processed_at, attempts = EXCLUDED.attempts,
                         last_error = EXCLUDED.last_error, analyzed_hash = EXCLUDED.analyzed_hash,
                         truncated = EXCLUDED.truncated""",
                    (record.post_id, record.status, record.requested_at, record.started_at, record.processed_at,
                     record.attempts, record.last_error, record.analyzed_hash, record.truncated),
                )
                # 분석 시작 = 시도 횟수가 늘면서 processing 이 된 것. 종료 처리는 횟수를 늘리지 않으므로 세지 않는다.
                if record.status == "processing" and record.started_at and record.attempts > (before[0] if before else 0):
                    cur.execute("INSERT INTO engine.peripheral_post_analysis_log (post_id, started_at) VALUES (%s, %s)",
                                (record.post_id, record.started_at))

    def pending_oldest_first(self, limit: int) -> list[IntakeRecord]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM engine.peripheral_post_intake WHERE status = 'pending' "
                "ORDER BY requested_at NULLS FIRST, post_id LIMIT %s", (limit,))
            return [_record(r) for r in cur.fetchall()]

    def analyses_started_since(self, since: datetime) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM engine.peripheral_post_analysis_log WHERE started_at >= %s", (since,))
            return cur.fetchone()[0]

    # ── 이미 본 변경 신호 ────────────────────────────────────────────────
    def known_signals(self) -> dict[str, str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT post_id, change_signal FROM engine.peripheral_post_intake WHERE change_signal IS NOT NULL")
            return {str(pid): sig for pid, sig in cur.fetchall()}

    def set_signals(self, signals: dict[str, str], forget: Sequence[str] = ()) -> None:
        """대기에 올린 글의 변경 신호를 기록한다. `forget` 은 신호에서 사라진 글(하드 삭제) — 다시 "사라졌다"고 반복하지 않게 비운다."""
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                if signals:
                    cur.executemany(
                        "UPDATE engine.peripheral_post_intake SET change_signal = %s WHERE post_id = %s",
                        [(sig, pid) for pid, sig in signals.items()])
                if forget:
                    cur.execute("UPDATE engine.peripheral_post_intake SET change_signal = NULL WHERE post_id = ANY(%s::uuid[])",
                                (list(forget),))


class DbObservationStore:
    """`peripheral_post_pipeline.ObservationStore` 의 DB 구현(확정된 근거 문장)."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def replace_post(self, post_id: str, items: list[tuple[str, FeelObservation]]) -> None:
        """그 글의 행을 모두 지우고 다시 넣는다(글을 다시 분석했을 때). 한 트랜잭션이라 중간 상태가 보이지 않는다."""
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM engine.peripheral_post_evidence WHERE post_id = %s", (post_id,))
                rows = [
                    (post_id, o.quote_id or "", o.product_id, kind, o.attribute, o.direction, o.side, o.author_id,
                     sorted(o.purposes), sorted(o.situations), o.hand_size, sorted(o.evaluated_in), o.is_example,
                     o.written_at, o.sentence or "", o.photo_url)
                    for kind, o in items
                ]
                if rows:
                    cur.executemany(
                        """INSERT INTO engine.peripheral_post_evidence
                             (post_id, quote_id, product_id, kind, attribute, direction, side, author_id, purposes, situations,
                              hand_size, evaluated_in, is_example, written_at, sentence, photo_url)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (post_id, quote_id, product_id, attribute) DO NOTHING""", rows)

    def remove_post(self, post_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM engine.peripheral_post_evidence WHERE post_id = %s", (post_id,))

    def by_kind(self, product_ids: Sequence[str] | None = None) -> dict[str, list[FeelObservation]]:
        """점수 계산에 쓰는 관측(속성이 붙은 문장)을 종류별로. `product_ids` 가 있으면 그 제품만 읽는다."""
        sql = ("SELECT kind, author_id, product_id, attribute, direction, side, purposes, situations, hand_size, evaluated_in,"
               " is_example, written_at, post_id, quote_id, sentence, photo_url"
               " FROM engine.peripheral_post_evidence WHERE attribute <> 'other'")
        params: tuple = ()
        if product_ids is not None:
            sql += " AND product_id = ANY(%s::uuid[])"
            params = (list(product_ids),)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql + " ORDER BY post_id, quote_id, attribute", params)
            rows = cur.fetchall()
        out: dict[str, list[FeelObservation]] = {}
        for r in rows:
            out.setdefault(r["kind"], []).append(FeelObservation(
                author_id=str(r["author_id"]), product_id=str(r["product_id"]), attribute=r["attribute"],
                direction=r["direction"], side=r["side"], purposes=frozenset(r["purposes"]),
                situations=frozenset(r["situations"]), hand_size=r["hand_size"], evaluated_in=frozenset(r["evaluated_in"]),
                written_at=r["written_at"], is_example=r["is_example"], post_id=str(r["post_id"]), quote_id=r["quote_id"],
                sentence=r["sentence"], photo_url=r["photo_url"],
            ))
        return out

    # ── 문장 임베딩 ──────────────────────────────────────────────────────
    def list_missing_embeddings(self, limit: int, exclude_ids: Sequence[str] = ()) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT e.id, e.sentence FROM engine.peripheral_post_evidence e "
                "LEFT JOIN engine.peripheral_post_evidence_embedding v ON v.evidence_id = e.id "
                "WHERE v.evidence_id IS NULL AND NOT (e.id = ANY(%s::uuid[])) ORDER BY e.created_at, e.id LIMIT %s",
                (list(exclude_ids), limit))
            return cur.fetchall()

    def count_missing_embeddings(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM engine.peripheral_post_evidence e "
                        "LEFT JOIN engine.peripheral_post_evidence_embedding v ON v.evidence_id = e.id "
                        "WHERE v.evidence_id IS NULL")
            return cur.fetchone()[0]

    def upsert_embeddings(self, rows: list[tuple[str, list[float]]], model: str) -> None:
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO engine.peripheral_post_evidence_embedding (evidence_id, embedding, model) "
                    "VALUES (%s, %s::vector, %s) ON CONFLICT (evidence_id) DO UPDATE SET embedding = EXCLUDED.embedding, "
                    "model = EXCLUDED.model",
                    [(eid, _vector_literal(vec), model) for eid, vec in rows])

    def nearest(self, query_vector: Sequence[float], *, limit: int, kind: str | None = None) -> list[dict]:
        """질문 벡터와 코사인 거리가 가까운 문장(속성 문장과 기타 문장 모두)을 가까운 순으로. 정확 검색이다."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT e.id, e.post_id, e.quote_id, e.product_id, e.kind, e.attribute, e.sentence, e.is_example,"
                " v.embedding <=> %(q)s::vector AS distance"
                " FROM engine.peripheral_post_evidence_embedding v JOIN engine.peripheral_post_evidence e ON e.id = v.evidence_id"
                " WHERE (%(kind)s::text IS NULL OR e.kind = %(kind)s) ORDER BY distance, e.id LIMIT %(limit)s",
                {"q": _vector_literal(query_vector), "kind": kind, "limit": limit})
            return cur.fetchall()
