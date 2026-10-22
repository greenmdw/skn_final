"""0012_review_embedding_invalidate.sql — body가 바뀐 리뷰의 임베딩만 지우는지 검증.

WHEN (OLD.body IS DISTINCT FROM NEW.body)이므로, body가 그대로거나 다른 컬럼만 바뀐 UPDATE는
임베딩을 건드리지 않아야 한다.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from src.repo.review_embedding_repo import ReviewEmbeddingRepo

pytestmark = pytest.mark.db


@pytest.fixture
def review_db():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"review embedding trigger fixtures require a test database, got {conn.info.dbname!r}")
        ids = {"products": [], "docs": []}
        yield conn, ids
        with conn.transaction():
            if ids["docs"]:
                conn.execute("DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])", (ids["docs"],))
            if ids["products"]:
                conn.execute("DELETE FROM catalog.product WHERE id=ANY(%s::uuid[])", (ids["products"],))


def _add_product(conn, ids):
    product_id = uuid4()
    conn.execute(
        "INSERT INTO catalog.product(id,name,brand,model,product_type) VALUES (%s,%s,%s,%s,'gpu')",
        (product_id, f"trigger-test-{product_id}", "TestBrand", str(product_id)),
    )
    ids["products"].append(product_id)
    return product_id


def _add_document(conn, ids, product_id, body="original review body text"):
    doc_id = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,'unit-test',true,%s)",
        (doc_id, product_id, body),
    )
    ids["docs"].append(doc_id)
    return doc_id


def _has_embedding(conn, doc_id) -> bool:
    return conn.execute(
        "SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)
    ).fetchone()[0] == 1


def _unit_vector(dimensions=1536):
    vec = [0.0] * dimensions
    vec[0] = 1.0
    return vec


def test_body_change_deletes_embedding(review_db):
    conn, ids = review_db
    product_id = _add_product(conn, ids)
    doc_id = _add_document(conn, ids, product_id, body="before the change")
    ReviewEmbeddingRepo(conn).upsert_many([(doc_id, _unit_vector())])
    assert _has_embedding(conn, doc_id)

    conn.execute("UPDATE evidence.review_document SET body=%s WHERE id=%s", ("after the change", doc_id))
    assert not _has_embedding(conn, doc_id)


def test_body_update_to_same_value_keeps_embedding(review_db):
    conn, ids = review_db
    product_id = _add_product(conn, ids)
    doc_id = _add_document(conn, ids, product_id, body="unchanged review body")
    ReviewEmbeddingRepo(conn).upsert_many([(doc_id, _unit_vector())])
    assert _has_embedding(conn, doc_id)

    conn.execute("UPDATE evidence.review_document SET body=%s WHERE id=%s", ("unchanged review body", doc_id))
    assert _has_embedding(conn, doc_id)


def test_updating_other_column_keeps_embedding(review_db):
    conn, ids = review_db
    product_id = _add_product(conn, ids)
    doc_id = _add_document(conn, ids, product_id, body="posted_at only changes")
    ReviewEmbeddingRepo(conn).upsert_many([(doc_id, _unit_vector())])
    assert _has_embedding(conn, doc_id)

    conn.execute(
        "UPDATE evidence.review_document SET posted_at=%s WHERE id=%s",
        (datetime(2026, 1, 1, tzinfo=timezone.utc), doc_id),
    )
    assert _has_embedding(conn, doc_id)
