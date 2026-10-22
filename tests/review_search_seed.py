"""리뷰 검색 테스트용 상품·리뷰·embedding.

API는 앱의 커넥션 풀로 읽으므로 테스트 데이터를 실제로 커밋해야 보인다 — 그래서 autocommit 커넥션으로
넣고, 끝나면 이 헬퍼가 만든 행만 지운다(리뷰를 지우면 embedding은 CASCADE로 같이 지워진다).
embedding은 MOCK 해시 벡터(OpenAIEmbedder(mock=True))로 만든다 — 단어가 겹치면 유사도가 높아져서
검색 결과를 미리 알 수 있다. 앱도 테스트에선 MOCK_MODE=1이라 같은 방식으로 질문을 embedding한다.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg

from src.rag.embedding import OpenAIEmbedder
from src.repo.review_embedding_repo import ReviewEmbeddingRepo


class ReviewSeed:
    def __init__(self, conn):
        self.conn = conn
        self.embedder = OpenAIEmbedder(mock=True)
        self.repo = ReviewEmbeddingRepo(conn)
        self._products: list[UUID] = []
        self._docs: list[UUID] = []

    def product(self, product_type: str = "gpu") -> UUID:
        product_id = uuid4()
        self.conn.execute(
            "INSERT INTO catalog.product(id,name,brand,model,product_type) VALUES (%s,%s,%s,%s,%s)",
            (product_id, f"review-search-test-{product_id}", "TestBrand", str(product_id), product_type),
        )
        self._products.append(product_id)
        return product_id

    def review(self, product_id: UUID, body: str, *, synthetic: bool = False, embed: bool = True) -> UUID:
        doc_id = uuid4()
        self.conn.execute(
            "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
            "VALUES (%s,%s,'review-search-test',%s,%s)",
            (doc_id, product_id, synthetic, body),
        )
        self._docs.append(doc_id)
        if embed:
            self.repo.upsert_many([(doc_id, self.embedder.embed([body])[0])])
        return doc_id

    def cleanup(self) -> None:
        with self.conn.transaction():
            if self._docs:
                self.conn.execute("DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])", (self._docs,))
            if self._products:
                self.conn.execute("DELETE FROM catalog.product WHERE id=ANY(%s::uuid[])", (self._products,))


@contextmanager
def seeded_reviews(dsn: str):
    with psycopg.connect(dsn, autocommit=True) as conn:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"review search fixtures require a test database, got {conn.info.dbname!r}")
        seed = ReviewSeed(conn)
        try:
            yield seed
        finally:
            seed.cleanup()
