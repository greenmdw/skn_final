"""U-12 — 결과 화면의 '리뷰 N개'(items[].review.total_count)가 추천 순위가 읽는 DB 의 리뷰 문서 수와 맞는다."""
from __future__ import annotations

import os

import pytest

from src.services.recommendation_service import _alternative_review, _review_with_db_stats

DSN = os.getenv("DATABASE_URL")


def test_db_stats_fill_only_what_file_store_lacks():
    brief = {"total_count": None, "rating_raw": None, "rating_count": None, "plain": {}}
    stats = {"count": 12, "rating_count": 3, "rating_avg": 4.67}
    out = _review_with_db_stats(brief, stats)
    assert (out["total_count"], out["rating_raw"], out["rating_count"]) == (12, 4.67, 3)
    assert _review_with_db_stats({"total_count": 5}, stats)["total_count"] == 5      # 파일 산출물에 값이 있으면 그대로
    assert _review_with_db_stats(brief, None)["total_count"] is None                 # 문서가 없으면 모르는 값 그대로
    assert _review_with_db_stats(brief, {"count": 0, "rating_count": 0, "rating_avg": None})["total_count"] is None
    unrated = _review_with_db_stats(brief, {"count": 2, "rating_count": 0, "rating_avg": None})
    assert unrated["total_count"] == 2 and unrated["rating_raw"] is None
    assert _review_with_db_stats(None, stats) is None


def test_alternative_review_needs_reviews():
    assert _alternative_review(None) is None and _alternative_review({"count": 0}) is None
    r = _alternative_review({"count": 7, "rating_count": 0, "rating_avg": None})
    assert r["total_count"] == 7 and r["rating_raw"] is None and r["rating_count"] is None
    r = _alternative_review({"count": 7, "rating_count": 5, "rating_avg": 4.8})
    assert (r["rating_raw"], r["rating_count"], r["rating_refined"], r["excluded_ratio"]) == (4.8, 5, None, None)


if DSN:
    from fastapi.testclient import TestClient
    from src.api import app
    from src.db import get_conn

    @pytest.mark.db
    def test_result_review_count_matches_review_documents():
        with TestClient(app) as client:
            lid = client.post("/session").json()["list_id"]
            client.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
            for f, v in [("purpose", "game"), ("budget_max", 2_000_000), ("priority", "value")]:
                assert client.patch(f"/session/{lid}/slot", json={"field": f, "value": v}).status_code == 200
            assert client.post(f"/session/{lid}/recommend", json={}).status_code == 202
            items = client.get(f"/session/{lid}/result").json()["items"]
        with get_conn() as conn:
            for it in items:
                pid = it["review_detail"]["product_id"]
                docs = conn.execute("SELECT count(*) FROM evidence.review_document WHERE product_id=%s", (pid,)).fetchone()[0]
                assert it["review"]["total_count"] == (docs or None), it["slot"]
        assert any(it["review"]["total_count"] for it in items)

        # 평점도 같은 부품의 리뷰 요약 API 와 같은 값이다(표시용, 순위에는 안 쓴다).
        with TestClient(app) as client:
            for it in items:
                if not it["review"]["total_count"]:
                    continue
                s = client.get(f"/reviews/summary/{it['product']['product_key']}").json()
                assert it["review"]["rating_raw"] == s["rating_raw"], it["slot"]
                assert it["review"]["rating_count"] == s["rating_count"], it["slot"]
        assert any(it["review"]["rating_raw"] for it in items)

    @pytest.mark.db
    def test_alternatives_carry_review_stats_with_one_stats_query(monkeypatch):
        from src.services import review_service
        calls = []
        real = review_service.db_review_stats
        monkeypatch.setattr(review_service, "db_review_stats", lambda conn, ids: (calls.append(list(ids)), real(conn, ids))[1])
        with TestClient(app) as client:
            lid = client.post("/session").json()["list_id"]
            client.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
            for f, v in [("purpose", "game"), ("budget_max", 2_000_000), ("priority", "value")]:
                assert client.patch(f"/session/{lid}/slot", json={"field": f, "value": v}).status_code == 200
            assert client.post(f"/session/{lid}/recommend", json={}).status_code == 202
            items = client.get(f"/session/{lid}/result").json()["items"]
            item = next(it for it in items if it["alternatives_count"] > 2)
            calls.clear()
            alts = client.get(f"/session/{lid}/items/{item['item_id']}/alternatives").json()["items"]
            assert len(alts) > 2 and len(calls) == 1, (len(alts), len(calls))
            reviewed = [a for a in alts if a["review"]]
            assert reviewed
            for a in reviewed:
                s = client.get(f"/reviews/summary/{a['product']['product_key']}").json()
                assert a["review"]["total_count"] == s["total_count"] > 0
                assert a["review"]["rating_raw"] == s["rating_raw"] and a["review"]["rating_count"] == s["rating_count"]
                assert a["review"]["rating_refined"] is None and a["review"]["excluded_ratio"] is None
