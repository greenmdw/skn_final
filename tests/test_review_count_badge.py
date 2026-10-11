"""U-12 — 결과 화면의 '리뷰 N개'(items[].review.total_count)가 추천 순위가 읽는 DB 의 리뷰 문서 수와 맞는다."""
from __future__ import annotations

import os

import pytest

from src.services.recommendation_service import _review_with_db_count

DSN = os.getenv("DATABASE_URL")


def test_db_count_fills_only_when_file_store_has_no_count():
    brief = {"total_count": None, "plain": {}}
    assert _review_with_db_count(brief, 12)["total_count"] == 12
    assert _review_with_db_count({"total_count": 5}, 12)["total_count"] == 5      # 파일 산출물에 값이 있으면 그대로
    assert _review_with_db_count(brief, None)["total_count"] is None             # 문서가 없으면 모르는 값 그대로
    assert _review_with_db_count(brief, 0)["total_count"] is None
    assert _review_with_db_count(None, 3) is None


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
