"""리뷰 별점(evidence.review_document.rating) 적재 규칙: 채우기·충돌·옛 번들 차단."""
import hashlib
import json
import os
import runpy
import shutil
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/review_seed"
_mod = runpy.run_path(str(ROOT / "db/seed_review_corpus.py"))
read_bundle, load_bundle = _mod["read_bundle"], _mod["load_bundle"]
PC_TYPES = ("cpu", "gpu", "motherboard", "ram", "ssd", "psu", "case", "cooler")


@pytest.fixture()
def conn():
    # autocommit=False: 테스트가 바꾼 행은 마지막에 rollback으로 되돌린다.
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        yield c
        c.rollback()


@pytest.mark.db
def test_setup_loaded_ratings(conn):
    total, rated = conn.execute("SELECT count(*), count(rating) FROM evidence.review_document").fetchone()
    assert (total, rated) == (5653, 5571)
    missing = conn.execute(
        "SELECT count(*) FROM evidence.review_document d JOIN catalog.product p ON p.id=d.product_id "
        "WHERE p.product_type = ANY(%s) AND d.rating IS NULL", (list(PC_TYPES),)).fetchone()[0]
    assert missing == 0


def _rated_doc(conn):
    return conn.execute("SELECT id::text, rating FROM evidence.review_document "
                        "WHERE rating IS NOT NULL ORDER BY id LIMIT 1").fetchone()


@pytest.mark.db
def test_backfill_fills_null_rating_and_keeps_embedding(conn):
    doc_id, rating = _rated_doc(conn)
    conn.execute("INSERT INTO evidence.review_embedding(review_id, embedding) "
                 "VALUES (%s, (SELECT array_fill(0.1::real, ARRAY[1536])::vector)) "
                 "ON CONFLICT (review_id) DO NOTHING", (doc_id,))
    conn.execute("UPDATE evidence.review_document SET rating=NULL WHERE id=%s", (doc_id,))
    load_bundle(conn)
    assert conn.execute("SELECT rating FROM evidence.review_document WHERE id=%s", (doc_id,)).fetchone()[0] == rating
    assert conn.execute("SELECT count(*) FROM evidence.review_embedding WHERE review_id=%s", (doc_id,)).fetchone()[0] == 1


@pytest.mark.db
def test_conflicting_non_null_rating_is_rejected(conn):
    doc_id, rating = _rated_doc(conn)
    conn.execute("UPDATE evidence.review_document SET rating=%s WHERE id=%s", (rating % 5 + 1, doc_id))
    with pytest.raises(ValueError, match="conflicts with immutable bundle: " + doc_id):
        load_bundle(conn)


def test_old_bundle_without_rating_is_rejected(tmp_path):
    for p in BUNDLE.iterdir():
        if p.is_file():
            shutil.copy(p, tmp_path / p.name)
    docs = json.loads((tmp_path / "documents.json").read_text(encoding="utf-8"))
    for d in docs:
        d.pop("rating", None)
    (tmp_path / "documents.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    manifest = json.loads((tmp_path / "bundle_manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"]["documents.json"] = hashlib.sha256((tmp_path / "documents.json").read_bytes()).hexdigest()
    (tmp_path / "bundle_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="old version.*rating"):
        read_bundle(tmp_path)
