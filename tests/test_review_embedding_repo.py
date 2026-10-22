"""ReviewEmbeddingRepo — evidence.review_embedding 조회·upsert·CASCADE.

시드 테스트 DB(data/review_seed)에는 이미 evidence.review_document 행이 많이 있을 수 있다
(일부는 임베딩이 있고 일부는 없을 수 있다) — 그래서 절대 개수를 단언하지 않고, 이 테스트가 만든
id들로만 범위를 좁혀 검사한다.
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from src.repo.review_embedding_repo import ReviewEmbeddingRepo

pytestmark = pytest.mark.db


@pytest.fixture
def review_db():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"review embedding fixtures require a test database, got {conn.info.dbname!r}")
        ids = {"products": [], "docs": []}
        yield conn, ids
        with conn.transaction():
            if ids["docs"]:
                conn.execute("DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])", (ids["docs"],))
            if ids["products"]:
                conn.execute("DELETE FROM catalog.product WHERE id=ANY(%s::uuid[])", (ids["products"],))


def _add_product(conn, ids, *, product_type="gpu"):
    product_id = uuid4()
    conn.execute(
        "INSERT INTO catalog.product(id,name,brand,model,product_type) VALUES (%s,%s,%s,%s,%s)",
        (product_id, f"embedding-test-{product_id}", "TestBrand", str(product_id), product_type),
    )
    ids["products"].append(product_id)
    return product_id


def _add_document(conn, ids, product_id, *, body="good product, works great in games", source_code="unit-test"):
    doc_id = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,%s,true,%s)",
        (doc_id, product_id, source_code, body),
    )
    ids["docs"].append(doc_id)
    return doc_id


def _unit_vector(dimensions=1536, index=0):
    vec = [0.0] * dimensions
    vec[index] = 1.0
    return vec


def test_list_missing_and_count_missing_scoped_to_inserted_rows(review_db):
    conn, ids = review_db
    repo = ReviewEmbeddingRepo(conn)
    product_id = _add_product(conn, ids)

    before = repo.count_missing()
    doc_a = _add_document(conn, ids, product_id, body="review A body text")
    doc_b = _add_document(conn, ids, product_id, body="review B body text")
    after_insert = repo.count_missing()
    assert after_insert == before + 2

    missing = repo.list_missing(100000)
    missing_ids = {row["id"] for row in missing}
    assert doc_a in missing_ids and doc_b in missing_ids
    by_id = {row["id"]: row["body"] for row in missing}
    assert by_id[doc_a] == "review A body text"
    assert by_id[doc_b] == "review B body text"

    # Give doc_a an embedding directly — it must drop out of the missing list.
    repo.upsert_many([(doc_a, _unit_vector())])
    after_embed = repo.count_missing()
    assert after_embed == after_insert - 1
    missing_ids_after = {row["id"] for row in repo.list_missing(100000)}
    assert doc_a not in missing_ids_after
    assert doc_b in missing_ids_after


def test_list_missing_respects_limit_and_exclude_ids(review_db):
    conn, ids = review_db
    repo = ReviewEmbeddingRepo(conn)
    product_id = _add_product(conn, ids)
    doc_a = _add_document(conn, ids, product_id)
    doc_b = _add_document(conn, ids, product_id)

    one = repo.list_missing(1, exclude_ids=[doc_a])
    # With doc_a excluded, if doc_b happens to be the only/first remaining candidate among our
    # rows it must appear; we only assert doc_a is never returned.
    assert all(row["id"] != doc_a for row in one)

    excluded_both = repo.list_missing(100000, exclude_ids=[doc_a, doc_b])
    returned_ids = {row["id"] for row in excluded_both}
    assert doc_a not in returned_ids
    assert doc_b not in returned_ids


def test_upsert_inserts_then_overwrites(review_db):
    conn, ids = review_db
    repo = ReviewEmbeddingRepo(conn)
    product_id = _add_product(conn, ids)
    doc_id = _add_document(conn, ids, product_id)

    inserted = repo.upsert_many([(doc_id, _unit_vector(index=1))])
    assert inserted == 1
    row = conn.execute(
        "SELECT embedding::text FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()
    assert row is not None
    first_text = row[0]

    overwritten = repo.upsert_many([(doc_id, _unit_vector(index=2))])
    assert overwritten == 1
    row2 = conn.execute(
        "SELECT embedding::text FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()
    assert row2[0] != first_text

    # Still exactly one embedding row for this review (upsert, not duplicate insert).
    count = conn.execute(
        "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0]
    assert count == 1


def test_upsert_many_empty_list_is_noop(review_db):
    conn, ids = review_db
    repo = ReviewEmbeddingRepo(conn)
    assert repo.upsert_many([]) == 0


def test_cascade_delete_document_removes_embedding(review_db):
    conn, ids = review_db
    repo = ReviewEmbeddingRepo(conn)
    product_id = _add_product(conn, ids)
    doc_id = _add_document(conn, ids, product_id)
    repo.upsert_many([(doc_id, _unit_vector())])

    assert conn.execute(
        "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0] == 1

    conn.execute("DELETE FROM evidence.review_document WHERE id=%s", (doc_id,))
    ids["docs"].remove(doc_id)  # already gone — fixture cleanup should not try again

    assert conn.execute(
        "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0] == 0


def test_current_upsert_skips_changed_and_deleted_documents(review_db):
    conn, ids = review_db
    product = _add_product(conn, ids)
    same = _add_document(conn, ids, product, body="same body")
    changed = _add_document(conn, ids, product, body="new body")
    deleted = _add_document(conn, ids, product)
    conn.execute("DELETE FROM evidence.review_document WHERE id=%s", (deleted,))
    repo = ReviewEmbeddingRepo(conn)

    written = repo.upsert_current_many([
        (same, "same body", _unit_vector()),
        (changed, "old body", _unit_vector()),
        (deleted, "deleted body", _unit_vector()),
    ])
    assert written == 1
    assert conn.execute(
        "SELECT review_id FROM evidence.review_embedding WHERE review_id=ANY(%s::uuid[])",
        ([same, changed, deleted],),
    ).fetchall() == [(same,)]


def test_current_upsert_locks_body_through_storage_and_later_updates_invalidate(review_db, monkeypatch):
    conn, ids = review_db
    product = _add_product(conn, ids)
    doc = _add_document(conn, ids, product, body="original body")
    repo = ReviewEmbeddingRepo(conn)
    original_upsert = repo.upsert_many

    def write_while_locked(rows):
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as writer:
            writer.execute("SET lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                writer.execute("UPDATE evidence.review_document SET body='changed body' WHERE id=%s", (doc,))
        return original_upsert(rows)

    monkeypatch.setattr(repo, "upsert_many", write_while_locked)
    assert repo.upsert_current_many([(doc, "original body", _unit_vector())]) == 1
    conn.execute("UPDATE evidence.review_document SET body='changed body' WHERE id=%s", (doc,))
    assert conn.execute(
        "SELECT review_id FROM evidence.review_embedding WHERE review_id=%s", (doc,),
    ).fetchone() is None
