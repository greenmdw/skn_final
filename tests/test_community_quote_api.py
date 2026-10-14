"""GET /community/quotes/{quote_id} — 주변기기 추천이 인용한 문장을 quote_id 로 다시 찾는다(링크를 복사해 열거나 새로고침한 경우)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app
    from src.db import get_conn


def _author_id() -> str:
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"quote-{uuid4().hex[:10]}@example.test", "password": "abcd1234", "display_name": "인용",
                                     "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c.get("/auth/me").json()["user"]["id"]


def _post_with_evidence(status: str = "published") -> tuple[str, str, str]:
    """글 하나와 근거 문장 두 줄(제품 둘, 같은 quote_id)을 만든다. (post_id, quote_id, 문장)을 돌려준다."""
    quote_id, sentence = uuid4().hex[:16], "손이 작은데도 그립이 잘 맞습니다."
    with get_conn() as conn:
        author_id = _author_id()
        post_id = conn.execute(
            "INSERT INTO community.post (author_user_id, board_type, title, body, status, published_at, deleted_at) "
            "VALUES (%s, 'review', '인용 제목', '본문', %s, now(), CASE WHEN %s = 'deleted' THEN now() END) RETURNING id",
            (author_id, status, status)).fetchone()[0]
        products = [r[0] for r in conn.execute("SELECT id FROM catalog.product WHERE product_type = 'mouse' ORDER BY id LIMIT 2").fetchall()]
        for product_id in products:
            conn.execute(
                "INSERT INTO engine.peripheral_post_evidence (post_id, quote_id, product_id, kind, attribute, direction, author_id, sentence, is_example) "
                "VALUES (%s, %s, %s, 'mouse', 'grip', 'good', %s, %s, true)",
                (post_id, quote_id, product_id, author_id, sentence))
    return str(post_id), quote_id, sentence


def test_quote_lookup_returns_sentence_post_and_products_without_login():
    post_id, quote_id, sentence = _post_with_evidence()
    r = TestClient(app).get(f"/community/quotes/{quote_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quote_id"] == quote_id and body["post_id"] == post_id and body["sentence"] == sentence
    assert body["post_title"] == "인용 제목" and body["is_example"] is True and body["photo_url"] is None
    assert len(body["product_ids"]) == len(set(body["product_ids"])) >= 1


def test_unknown_quote_is_404():
    r = TestClient(app).get("/community/quotes/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("status", ["hidden", "deleted", "draft"])
def test_quotes_of_unpublished_posts_are_not_revealed(status):
    _post_id, quote_id, _ = _post_with_evidence(status)
    assert TestClient(app).get(f"/community/quotes/{quote_id}").status_code == 404


def test_overlong_quote_id_is_rejected():
    assert TestClient(app).get("/community/quotes/" + "a" * 65).status_code == 422
