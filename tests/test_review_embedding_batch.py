"""review_embedding_batch.run() — 배치 단위 커밋·부분 실패·dry_run·rebuild.

시드된 테스트 DB에는 evidence.review_document가 이미 많이 있을 수 있고, 이 배치는 전체 테이블을
"임베딩 없는 리뷰" 기준으로 훑는다(src.repo.review_embedding_repo.list_missing에 범위 필터가
없다) — 그래서 각 테스트는 바깥 트랜잭션 하나(clean_conn)로 감싸고, 시작할 때 기존에 비어 있던
행을 먼저 채워 count_missing()을 0으로 만든 뒤 이 테스트가 넣은 문서만 대상이 되게 한다. 바깥
트랜잭션은 끝에 통째로 롤백하므로(이 파일만의 임시 조치) 다른 테스트/모듈에는 아무 영향이 없다.
run() 내부의 배치별 conn.transaction()은 이미 열린 바깥 트랜잭션 안에서는 SAVEPOINT가 되므로,
"배치 하나 실패해도 다른 배치는 남는다"는 동작은 그대로 검증된다.

맨 아래 두 테스트(test_run_rejects_plain_nonautocommit_idle_connection,
test_batch_commits_are_durable_with_autocommit_connection)는 일부러 clean_conn을 쓰지 않는다 —
"배치마다 진짜로 커밋되는지"와 "평범한 커넥션은 거절하는지" 자체가 검증 대상이라, 거꾸로 격리용
바깥 트랜잭션에 감싸면 그 진짜 커밋을 관찰할 수 없다. 그래서 실제 커밋이 생기는 쪽은 자신이 만든
행만 끝에 직접 지운다.
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from src.rag.contracts import EmbeddingError
from src.repo.review_embedding_repo import ReviewEmbeddingRepo
from src.workers import review_embedding_batch

pytestmark = pytest.mark.db


def _vector_literal(values):
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _placeholder_vector(dimensions=1536):
    vec = [0.0] * dimensions
    vec[0] = 1.0
    return vec


class _Rollback(Exception):
    pass


@pytest.fixture
def clean_conn():
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn)
    if "test" not in conn.info.dbname.lower():
        conn.close()
        raise AssertionError(f"review embedding batch fixtures require a test database, got {dsn!r}")
    try:
        with conn.transaction():
            # 기존에 임베딩이 없던 행을 전부 채워 이번 테스트의 대상에서 뺀다(한 번의 SQL, 빠르다).
            conn.execute(
                "INSERT INTO evidence.review_embedding (review_id, embedding) "
                "SELECT d.id, %s::vector FROM evidence.review_document d "
                "LEFT JOIN evidence.review_embedding e ON e.review_id = d.id "
                "WHERE e.review_id IS NULL",
                (_vector_literal(_placeholder_vector()),),
            )
            yield conn
            raise _Rollback()
    except _Rollback:
        pass
    finally:
        conn.close()


def _add_product(conn):
    product_id = uuid4()
    conn.execute(
        "INSERT INTO catalog.product(id,name,brand,model,product_type) VALUES (%s,%s,%s,%s,'gpu')",
        (product_id, f"batch-test-{product_id}", "TestBrand", str(product_id)),
    )
    return product_id


def _add_document(conn, product_id, body):
    doc_id = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,'unit-test',true,%s)",
        (doc_id, product_id, body),
    )
    return doc_id


class _FakeEmbedder:
    dimensions = 1536

    def __init__(self, fail_bodies=None):
        self.fail_bodies = set(fail_bodies or [])
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if any(text in self.fail_bodies for text in texts):
            raise EmbeddingError("embedding_unavailable")
        vectors = []
        for text in texts:
            vec = [0.0] * self.dimensions
            vec[abs(hash(text)) % self.dimensions] = 1.0
            vectors.append(vec)
        return vectors


def test_run_fills_all_missing_then_is_idempotent(clean_conn):
    conn = clean_conn
    product_id = _add_product(conn)
    doc_ids = [_add_document(conn, product_id, f"body {i}") for i in range(3)]
    repo = ReviewEmbeddingRepo(conn)
    assert repo.count_missing() == 3

    embedder = _FakeEmbedder()
    result = review_embedding_batch.run(conn, embedder, batch_size=2)
    assert result["embedded"] == 3
    assert result["failed"] == 0
    assert result["remaining"] == 0
    assert result["batches"] == 2  # ceil(3/2)
    assert repo.count_missing() == 0
    assert {row["id"] for row in repo.list_missing(100)} == set()

    second = review_embedding_batch.run(conn, embedder, batch_size=2)
    assert second == {"embedded": 0, "failed": 0, "remaining": 0, "batches": 0}


def test_run_isolates_failing_batch_and_rerun_fills_the_rest(clean_conn):
    conn = clean_conn
    product_id = _add_product(conn)
    ok_bodies = ["ok-0", "ok-2", "ok-3"]
    fail_body = "fail-1"
    doc_by_body = {body: _add_document(conn, product_id, body) for body in ok_bodies + [fail_body]}
    repo = ReviewEmbeddingRepo(conn)
    assert repo.count_missing() == 4

    embedder = _FakeEmbedder(fail_bodies={fail_body})
    result = review_embedding_batch.run(conn, embedder, batch_size=1)
    assert result["embedded"] == 3
    assert result["failed"] == 1
    assert result["batches"] == 4
    assert result["remaining"] == 1

    missing_ids = {row["id"] for row in repo.list_missing(100)}
    assert missing_ids == {doc_by_body[fail_body]}
    for body in ok_bodies:
        assert doc_by_body[body] not in missing_ids

    # Re-run with a working embedder must fill exactly the one that failed before.
    working_embedder = _FakeEmbedder()
    rerun = review_embedding_batch.run(conn, working_embedder, batch_size=1)
    assert rerun["embedded"] == 1
    assert rerun["failed"] == 0
    assert rerun["remaining"] == 0
    assert repo.count_missing() == 0


def test_dry_run_writes_nothing_and_never_calls_embedder(clean_conn):
    conn = clean_conn
    product_id = _add_product(conn)
    _add_document(conn, product_id, "dry run body one")
    _add_document(conn, product_id, "dry run body two")
    repo = ReviewEmbeddingRepo(conn)
    before = repo.count_missing()
    assert before == 2

    embedder = _FakeEmbedder()
    result = review_embedding_batch.run(conn, embedder, dry_run=True)
    assert result == {"embedded": 0, "failed": 0, "remaining": before, "batches": 0}
    assert embedder.calls == []
    assert repo.count_missing() == before


def test_rebuild_reembeds_everything(clean_conn):
    conn = clean_conn
    product_id = _add_product(conn)
    doc_id = _add_document(conn, product_id, "rebuild target body")
    repo = ReviewEmbeddingRepo(conn)

    # rebuild wipes the WHOLE evidence.review_embedding table, not just our scope — so after
    # rebuild every evidence.review_document row (including the ones this test's clean_conn
    # fixture already filled in as a drain placeholder) becomes "missing" again. Scope the
    # expectation to the real total instead of pretending this test owns the whole table.
    total_documents = conn.execute("SELECT count(*) FROM evidence.review_document").fetchone()[0]

    first_embedder = _FakeEmbedder()
    review_embedding_batch.run(conn, first_embedder, batch_size=2000)
    assert repo.count_missing() == 0
    before_text = conn.execute(
        "SELECT embedding::text FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0]

    class _DifferentEmbedder:
        dimensions = 1536

        def embed(self, texts):
            vectors = []
            for _ in texts:
                vec = [0.0] * self.dimensions
                vec[42] = 1.0
                vectors.append(vec)
            return vectors

    result = review_embedding_batch.run(conn, _DifferentEmbedder(), batch_size=2000, rebuild=True)
    assert result["embedded"] == total_documents
    assert result["failed"] == 0
    assert result["remaining"] == 0

    after_text = conn.execute(
        "SELECT embedding::text FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0]
    assert after_text != before_text


def test_rebuild_with_dry_run_raises_value_error(clean_conn):
    conn = clean_conn
    with pytest.raises(ValueError):
        review_embedding_batch.run(conn, _FakeEmbedder(), dry_run=True, rebuild=True)


def test_run_rejects_plain_nonautocommit_idle_connection():
    """autocommit=False이고 아직 어떤 문장도 실행하지 않은(IDLE) '평범한' 커넥션으로 부르면,
    배치마다 커밋한 것처럼 보여도 실제로는 이 커넥션이 나중에 commit/close될 때 한 번에
    커밋된다 — run()은 그 모양을 미리 ValueError로 막아야 한다(아무것도 쓰기 전에)."""
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn)  # autocommit 기본값 False, 아직 아무 문장도 실행 안 함 → IDLE
    try:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"guard test requires a test database, got {dsn!r}")
        assert conn.autocommit is False
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        with pytest.raises(ValueError):
            review_embedding_batch.run(conn, _FakeEmbedder())

        # 가드가 아무 SQL도 실행하기 전에 걸렸어야 한다 — 여전히 트랜잭션 밖(IDLE)이다.
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    finally:
        conn.rollback()
        conn.close()


class _CrashingEmbedder:
    """첫 배치는 성공, 두 번째 배치는 EmbeddingError가 아닌 예외(RuntimeError, 실제 장애를
    흉내)로 죽는다 — run()은 이 예외를 잡지 않고(실패 추적은 EmbeddingError만) 그대로 올려야
    하고, 이미 성공한 첫 배치는 커밋된 채 남아 있어야 한다(배치별 내구성)."""

    dimensions = 1536

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        if self.calls == 1:
            vec = [0.0] * self.dimensions
            vec[0] = 1.0
            return [vec]
        raise RuntimeError("simulated mid-run crash")


def test_batch_commits_are_durable_with_autocommit_connection():
    """진짜 autocommit=True 커넥션으로, 두 배치 중 두 번째가 (EmbeddingError가 아닌) 예외로
    죽을 때 run()이 그 예외를 그대로 올리면서도 첫 배치는 이미 디스크에 커밋돼 있는지 확인한다.
    시드된 테스트 DB에는 임베딩 없는 리뷰가 많으므로 list_missing으로 run()이 고를 두 개를
    미리 내다보고, 그 두 id로만 결과를 확인한다 — 끝나면 이 테스트가 만든 임베딩 행만 지운다."""
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn, autocommit=True)
    first_id = None
    try:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"durability test requires a test database, got {dsn!r}")
        repo = ReviewEmbeddingRepo(conn)
        preview = repo.list_missing(2)
        assert len(preview) == 2, "시드된 테스트 DB에 임베딩 없는 리뷰가 2개 이상 있어야 한다"
        first_id, second_id = preview[0]["id"], preview[1]["id"]

        embedder = _CrashingEmbedder()
        with pytest.raises(RuntimeError):
            review_embedding_batch.run(conn, embedder, limit=2, batch_size=1)
        assert embedder.calls == 2

        assert conn.execute(
            "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (first_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (second_id,)
        ).fetchone()[0] == 0

        # 이 커넥션의 캐시가 아니라 진짜 디스크에 남았는지 — 별도 커넥션으로 다시 확인한다.
        with psycopg.connect(dsn, autocommit=True) as fresh:
            assert fresh.execute(
                "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (first_id,)
            ).fetchone()[0] == 1
    finally:
        if first_id is not None:
            conn.execute("DELETE FROM evidence.review_embedding WHERE review_id=%s", (first_id,))
        conn.close()
