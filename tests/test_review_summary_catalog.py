"""결과 화면 부품의 리뷰 요약 — 10/15 QA #27·#57 ("부품별 리뷰 요약이 전부 '아직 없어요'").

결과 화면은 우리 카탈로그 키(`cooler:thermalright:…`)로 요약을 묻는데, 요약은 아마존 파일 산출물만 읽어 전부 404 였다.
추천 순위가 읽는 수집 리뷰(evidence.review_document·review_aspect_aggregate)로 리뷰 수와 항목별 관측 수를 낸다.
일회용 테스트 DB(setup_all 이 리뷰 시드 번들을 넣는다)가 필요하다."""
from __future__ import annotations

import contextlib
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app
    from src.repo.catalog_repo import pc_catalog_key

_KEY = "SELECT p.product_type, p.brand, p.model FROM catalog.product p WHERE "


def _key(where: str) -> tuple[str, str]:
    with psycopg.connect(DSN) as conn:
        row = conn.execute(_KEY + where + " ORDER BY p.id LIMIT 1").fetchone()
        assert row is not None, where
        return pc_catalog_key(*row), row


def test_a_catalog_part_with_reviews_gets_its_review_count_and_aspect_counts():
    key, _ = _key("p.product_type IN ('cpu','gpu','cooler') AND EXISTS (SELECT 1 FROM evidence.review_aspect_aggregate a "
                  "WHERE a.product_id = p.id AND a.p + a.n + a.mixed > 0)")
    with psycopg.connect(DSN) as conn:
        n = conn.execute("SELECT count(*) FROM evidence.review_document d JOIN catalog.product p ON p.id = d.product_id "
                         "WHERE lower(replace(p.product_type||':'||p.brand||':'||p.model,' ','-')) = %s", (key,)).fetchone()[0]
    r = TestClient(app).get(f"/reviews/summary/{key}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ready" and j["total_count"] == n > 0
    assert j["aspect_facts"] and all("좋다는 리뷰" in line and "아쉽다는 리뷰" in line for line in j["aspect_facts"])
    assert not any("_" in line for line in j["aspect_facts"])                 # 속성 코드가 아니라 사용자 말
    # 수집처(다나와) 구매자 별점의 단순 평균 — 검수 후 평점·제외 건수는 계속 비운다.
    with psycopg.connect(DSN) as conn:
        rn, ra = conn.execute("SELECT count(d.rating), avg(d.rating) FROM evidence.review_document d "
                              "JOIN catalog.product p ON p.id = d.product_id WHERE NOT d.is_synthetic AND "
                              "lower(replace(p.product_type||':'||p.brand||':'||p.model,' ','-')) = %s", (key,)).fetchone()
    assert rn > 0
    assert j["rating_raw"] == round(float(ra), 2) and j["rating_count"] == rn
    assert j["rating_refined"] is None and j["excluded_count"] is None and j["excluded_ratio"] is None
    assert f"{n:,}건" in j["data_notice"] and f"다나와 구매자 별점 {rn:,}건" in j["data_notice"]


def test_a_catalog_part_summary_does_not_depend_on_the_database_url_env_var(monkeypatch):
    # .env 에서 DATABASE_URL 을 주석 처리하고 띄운 서버는 config 기본 주소로 접속한다 — 그때도 요약이 나와야 한다.
    key, _ = _key("p.product_type IN ('cpu','gpu','cooler') AND EXISTS (SELECT 1 FROM evidence.review_aspect_aggregate a "
                  "WHERE a.product_id = p.id AND a.p + a.n + a.mixed > 0)")
    monkeypatch.delenv("DATABASE_URL")
    r = TestClient(app).get(f"/reviews/summary/{key}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ready" and j["total_count"] > 0 and j["aspect_facts"]


def test_a_catalog_part_without_reviews_is_still_404():
    key, _ = _key("p.product_type IN ('cpu','gpu','motherboard','psu','case','cooler','ram','ssd') AND NOT EXISTS "
                  "(SELECT 1 FROM evidence.review_document d WHERE d.product_id = p.id)")
    r = TestClient(app).get(f"/reviews/summary/{key}")
    assert r.status_code == 404, r.text


def _product_id(where: str):
    with psycopg.connect(DSN) as conn:
        row = conn.execute("SELECT p.id FROM catalog.product p WHERE " + where + " ORDER BY p.id LIMIT 1").fetchone()
        assert row is not None, where
        return row[0]


@contextlib.contextmanager
def _inserted_docs(product_id, docs):
    """앱이 다른 연결로 읽으므로 커밋해 넣고, 끝나면 지운다(일회용 테스트 DB)."""
    ids = []
    with psycopg.connect(DSN) as conn:
        for rating, synthetic in docs:
            ids.append(conn.execute(
                "INSERT INTO evidence.review_document (product_id, source_code, is_synthetic, body, rating) "
                "VALUES (%s, 'processed-jsonl-v1:computer', %s, '테스트 리뷰', %s) RETURNING id",
                (product_id, synthetic, rating)).fetchone()[0])
    try:
        yield
    finally:
        with psycopg.connect(DSN) as conn:
            conn.execute("DELETE FROM evidence.review_document WHERE id = ANY(%s)", (ids,))


def _summary(product_id):
    with psycopg.connect(DSN) as conn:
        p = conn.execute("SELECT product_type, brand, model FROM catalog.product WHERE id = %s", (product_id,)).fetchone()
    return TestClient(app).get(f"/reviews/summary/{pc_catalog_key(*p)}")


_NO_REVIEW = ("p.product_type IN ('cpu','gpu','motherboard','psu','case','cooler','ram','ssd') AND NOT EXISTS "
              "(SELECT 1 FROM evidence.review_document d WHERE d.product_id = p.id)")


def test_a_single_rated_review_still_gives_an_average_with_its_count():
    pid = _product_id(_NO_REVIEW)
    with _inserted_docs(pid, [(4, False)]):
        j = _summary(pid).json()
    assert j["rating_raw"] == 4.0 and j["rating_count"] == 1 and j["total_count"] == 1
    assert "별점 1건" in j["data_notice"]


def test_synthetic_reviews_do_not_change_the_rating_average_or_count():
    pid = _product_id(_NO_REVIEW)
    with _inserted_docs(pid, [(5, False), (1, True)]):
        j = _summary(pid).json()
    assert j["rating_raw"] == 5.0 and j["rating_count"] == 1


def test_unrated_reviews_give_no_average_and_say_so():
    pid = _product_id(_NO_REVIEW)
    with _inserted_docs(pid, [(None, False)]):
        j = _summary(pid).json()
    assert j["rating_raw"] is None and j["rating_count"] is None and j["total_count"] == 1
    assert "수집하지 못했" in j["data_notice"]
