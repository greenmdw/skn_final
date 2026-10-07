"""리뷰 임베딩 저장소 — evidence.review_embedding(review_id, embedding) 두 컬럼만 다룬다
(0008_review_aspect.sql 합의로 다른 컬럼은 추가하지 않는다).

"임베딩 행이 없는 리뷰는 임베딩이 필요하다"(0012_review_embedding_invalidate.sql 머리글, AGENTS.md)가
이 기능의 유일한 규칙이다. 이 repo는 그 규칙이 가리키는 행을 조회·쓰는 SQL만 안다 — 어떤 임베더를
쓸지, 몇 개씩 묶어 커밋할지는 배치 워커(src/workers/review_embedding_batch.py)의 책임이다.

리뷰 검색(src/services/review_search.py)이 쓰는 조회도 여기 둔다 — 상품별 가까운 리뷰(search_nearest),
상태 판정용 건수(coverage), 저장된 벡터가 지금 embedder와 같은 방식인지 확인하는 점검
(embedded_sample·stored_similarity). 검색 대상은 실제 리뷰(is_synthetic=false)뿐이다.

이 프로젝트엔 pgvector 파이썬 어댑터 의존성이 없다(pyproject.toml 확인, psycopg만 쓴다) — 그래서
벡터는 새 의존성을 추가하지 않고 pgvector가 받는 텍스트 리터럴('[v1,v2,...]')로 보내고 '::vector'로
캐스트한다. 컬럼 자체가 vector(1536)로 고정폭이라 차원이 안 맞으면 INSERT 시점에 Postgres가 에러를
낸다 — 호출자(워커)가 그보다 먼저 validate_vector()로 차원을 확인해 두는 편이 안전하다.
"""
from __future__ import annotations

from typing import Sequence
from uuid import UUID

from psycopg.rows import dict_row


def _vector_literal(values: Sequence[float]) -> str:
    """pgvector 텍스트 입력 형식('[0.1,0.2,...]')으로 직렬화한다."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class ReviewEmbeddingRepo:
    def __init__(self, conn):
        self.conn = conn

    def list_missing(self, limit: int, *, exclude_ids: Sequence[UUID] | None = None) -> list[dict]:
        """임베딩 행이 없는 리뷰를 id 순으로 최대 limit개(body 포함, 바로 임베딩할 수 있게).

        exclude_ids: 이번 실행에서 이미 실패로 처리한 id들. list_missing은 임베딩이 없는 한
        계속 같은 행을 돌려주므로, 배치 워커가 실패한 배치를 건너뛰려면 다음 호출에서 그 id들을
        빼야 한다 — 그러지 않으면 같은 실패가 무한히 반복된다."""
        exclude = list(exclude_ids or [])
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT d.id, d.body FROM evidence.review_document d "
                "LEFT JOIN evidence.review_embedding e ON e.review_id = d.id "
                "WHERE e.review_id IS NULL AND NOT (d.id = ANY(%s::uuid[])) "
                "ORDER BY d.id LIMIT %s",
                (exclude, limit),
            )
            return cur.fetchall()

    def count_missing(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM evidence.review_document d "
                "LEFT JOIN evidence.review_embedding e ON e.review_id = d.id "
                "WHERE e.review_id IS NULL"
            )
            return cur.fetchone()[0]

    def upsert_many(self, rows: list[tuple[UUID, list[float]]]) -> int:
        """(review_id, embedding 벡터) 목록을 upsert한다. body가 바뀌면 트리거(0012)가 먼저 기존
        행을 지우므로, 여기서는 "없으면 넣고 있으면 덮어쓰기"만 하면 된다 — 호출자가 이미 지워진
        상태인지 아닌지 구분할 필요가 없다."""
        if not rows:
            return 0
        with self.conn.cursor() as cur:
            for review_id, vector in rows:
                cur.execute(
                    "INSERT INTO evidence.review_embedding (review_id, embedding) "
                    "VALUES (%s, %s::vector) "
                    "ON CONFLICT (review_id) DO UPDATE SET embedding = EXCLUDED.embedding",
                    (review_id, _vector_literal(vector)),
                )
        return len(rows)

    def delete_all(self) -> int:
        """전체 재구축(rebuild) 전용 — 모든 임베딩을 지운다."""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM evidence.review_embedding")
            return cur.rowcount

    def coverage(self, product_ids: Sequence[UUID]) -> dict[UUID, dict]:
        """상품마다 카탈로그에 있는지, 실제 리뷰 수, 그중 embedding이 있는 수.

        리뷰 검색이 "리뷰 없음"과 "아직 embedding 전"을 나누고, 일부만 검색했다는 사실을 숨기지 않으려고
        쓴다. 합성 리뷰는 검색 대상이 아니라 세지 않는다."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT req.product_id, (p.id IS NOT NULL) AS product_exists, "
                "count(d.id) AS reviews, count(e.review_id) AS embedded "
                "FROM unnest(%s::uuid[]) AS req(product_id) "
                "LEFT JOIN catalog.product p ON p.id = req.product_id "
                "LEFT JOIN evidence.review_document d ON d.product_id = req.product_id AND NOT d.is_synthetic "
                "LEFT JOIN evidence.review_embedding e ON e.review_id = d.id "
                "GROUP BY req.product_id, p.id",
                (list(product_ids),),
            )
            return {
                row["product_id"]: {
                    "exists": row["product_exists"], "reviews": row["reviews"], "embedded": row["embedded"],
                }
                for row in cur.fetchall()
            }

    def search_nearest(self, query_vector: Sequence[float], product_ids: Sequence[UUID], *,
                       per_product: int) -> list[dict]:
        """상품마다 질문 벡터와 코사인 거리가 가까운 실제 리뷰를 per_product건까지(가까운 순).

        색인 없이 전부 계산한다(0008 "정확 검색부터 시작") — 상품당 리뷰가 많아야 수백 건이다. 상품별로
        자르는 이유는 두 상품을 비교하는 질문에서 리뷰가 많은 쪽이 결과를 다 차지하지 않게 하려는 것이다.
        코사인 거리(<=>)는 나중에 HNSW(vector_cosine_ops) 색인을 붙여도 그대로 맞는다."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "WITH scored AS ("
                " SELECT d.id, d.product_id, d.body, d.posted_at,"
                "  e.embedding <=> %(query)s::vector AS distance"
                " FROM evidence.review_document d"
                " JOIN evidence.review_embedding e ON e.review_id = d.id"
                " WHERE d.product_id = ANY(%(product_ids)s::uuid[]) AND NOT d.is_synthetic"
                "), ranked AS ("
                " SELECT *, row_number() OVER (PARTITION BY product_id ORDER BY distance, id) AS rn"
                " FROM scored"
                ") "
                "SELECT id, product_id, body, posted_at, 1 - distance AS similarity "
                "FROM ranked WHERE rn <= %(per_product)s ORDER BY product_id, rn",
                {"query": _vector_literal(query_vector), "product_ids": list(product_ids),
                 "per_product": per_product},
            )
            return cur.fetchall()

    def embedded_sample(self, product_ids: Sequence[UUID], limit: int) -> list[dict]:
        """embedding 일치 점검용 — 이 상품들의 embedding이 있는 실제 리뷰를 본문이 짧은 것부터
        (다시 embedding하는 비용을 줄이려고) limit건."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT d.id, d.body FROM evidence.review_document d "
                "JOIN evidence.review_embedding e ON e.review_id = d.id "
                "WHERE d.product_id = ANY(%s::uuid[]) AND NOT d.is_synthetic "
                "ORDER BY length(d.body), d.id LIMIT %s",
                (list(product_ids), limit),
            )
            return cur.fetchall()

    def stored_similarity(self, rows: Sequence[tuple[UUID, Sequence[float]]]) -> list[float]:
        """(review_id, 지금 embedder로 다시 만든 벡터)마다 저장된 벡터와의 코사인 유사도.
        저장된 행이 없는 review_id는 결과에서 빠진다."""
        if not rows:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 - (e.embedding <=> q.vector::vector) "
                "FROM unnest(%s::uuid[], %s::text[]) AS q(review_id, vector) "
                "JOIN evidence.review_embedding e ON e.review_id = q.review_id",
                ([review_id for review_id, _ in rows], [_vector_literal(vector) for _, vector in rows]),
            )
            return [row[0] for row in cur.fetchall()]
