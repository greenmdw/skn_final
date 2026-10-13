"""GET /reviews/search — 응답 형식, 상품별 상태, 404·422·429·503.

데이터는 커밋해서 넣는다(앱은 커넥션 풀로 읽는다) — tests/review_search_seed.py가 끝나면 지운다.
embedder는 테스트마다 새 MOCK embedder로 바꿔 캐시·점검 상태가 테스트 사이에 새지 않게 하고,
관련도 하한은 config·env와 무관하게 0.3으로 고정한다.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytest.importorskip("httpx")                      # TestClient 의존성 — `uv sync --group test`
from fastapi.testclient import TestClient         # noqa: E402

from review_search_seed import seeded_reviews     # noqa: E402
from src.api import app                           # noqa: E402
from src.rag.contracts import EmbeddingError      # noqa: E402
from src.rag.embedding import OpenAIEmbedder      # noqa: E402
from src.routers import reviews as reviews_router  # noqa: E402
from src.services import review_search            # noqa: E402
from src.services.review_search import CachedEmbedder  # noqa: E402

pytestmark = pytest.mark.db

QUERY = "팬 소음이 심한가요"


@pytest.fixture
def seed(monkeypatch):
    monkeypatch.setattr(review_search, "_default_embedder", CachedEmbedder(OpenAIEmbedder(mock=True)))
    monkeypatch.setattr(review_search, "REVIEW_SEARCH_MIN_SIMILARITY", 0.3)
    with seeded_reviews(os.environ["DATABASE_URL"]) as s:
        yield s


@pytest.fixture
def client():
    return TestClient(app)


def _search(client, product_ids, q=QUERY, **params):
    return client.get("/reviews/search", params={"product_id": [str(pid) for pid in product_ids], "q": q, **params})


def test_search_returns_hits_and_a_status_per_product(seed, client):
    relevant, unrelated, no_reviews, not_indexed = (seed.product() for _ in range(4))
    hit = seed.review(relevant, "팬 소음이 조금 있지만 참을 만해요")
    seed.review(relevant, "소음 거의 없고 조용합니다")              # 겹치는 단어가 적어 하한(0.3) 아래
    seed.review(unrelated, "배송이 빠르고 포장이 꼼꼼해요")
    seed.review(not_indexed, "팬 소음이 커요", embed=False)

    response = _search(client, [relevant, unrelated, no_reviews, not_indexed], q="  팬   소음이 심한가요 ")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == QUERY and body["min_similarity"] == 0.3
    assert [(p["product_id"], p["status"]) for p in body["products"]] == [
        (str(relevant), "ok"), (str(unrelated), "no_match"),
        (str(no_reviews), "no_reviews"), (str(not_indexed), "not_indexed"),
    ]
    first = body["products"][0]
    assert first["coverage"] == {"reviews": 2, "embedded": 2}
    assert [h["review_id"] for h in first["hits"]] == [str(hit)]
    assert first["hits"][0]["body"] == "팬 소음이 조금 있지만 참을 만해요"
    assert 0.3 <= first["hits"][0]["similarity"] <= 1.0
    assert body["products"][3]["coverage"] == {"reviews": 1, "embedded": 0}


def test_limit_caps_hits_per_product(seed, client):
    product = seed.product()
    for body in ["팬 소음이 커요", "팬 소음이 조금 있어요", "팬 소음이 거슬려요"]:
        seed.review(product, body)
    response = _search(client, [product], limit=2)
    assert response.status_code == 200
    assert len(response.json()["products"][0]["hits"]) == 2


def test_unknown_product_is_404(seed, client):
    known = seed.product()
    response = _search(client, [known, uuid4()])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["field"] == "product_id"


def test_invalid_input_is_422(seed, client):
    product = seed.product()
    blank = _search(client, [product], q="   ")
    assert blank.status_code == 422
    assert blank.json()["error"] == {"code": "validation_failed", "message": "검색할 질문을 입력해야 합니다.",
                                     "field": "q"}
    assert _search(client, [product], limit=11).status_code == 422
    assert client.get("/reviews/search", params={"product_id": "not-a-uuid", "q": QUERY}).status_code == 422
    assert client.get("/reviews/search", params={"q": QUERY}).status_code == 422


def test_requests_over_the_per_ip_limit_get_429(seed, client, monkeypatch):
    monkeypatch.setattr(reviews_router, "REVIEW_SEARCH_LIMIT_PER_MIN", 2)
    product = seed.product()                       # 리뷰가 없어 embedding 호출 없이 끝나는 요청
    assert [_search(client, [product]).status_code for _ in range(2)] == [200, 200]
    over = _search(client, [product])
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "rate_limited"


class _FailingEmbedder:
    def embed(self, texts):
        raise EmbeddingError("embedding_unavailable")


class _OtherWayEmbedder:
    """저장된 MOCK 해시 벡터와 다른 방식 — 실제 모델로 검색하는데 DB는 가짜 벡터로 채워진 상황을 흉내 낸다."""

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * 1536
            vector[len(text) % 1536] = 1.0
            vectors.append(vector)
        return vectors


def test_embedding_failure_is_503(seed, client, monkeypatch):
    product = seed.product()
    seed.review(product, "팬 소음이 조금 있어요")
    monkeypatch.setattr(review_search, "_default_embedder", CachedEmbedder(_FailingEmbedder()))
    response = _search(client, [product])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_search_unavailable"


def test_embeddings_made_another_way_are_503_instead_of_wrong_results(seed, client, monkeypatch):
    product = seed.product()
    seed.review(product, "팬 소음이 조금 있지만 참을 만해요")
    monkeypatch.setattr(review_search, "_default_embedder", CachedEmbedder(_OtherWayEmbedder()))
    response = _search(client, [product])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_index_mismatch"


def _change_embedding(seed, doc, body):
    seed.repo.upsert_many([(doc, _OtherWayEmbedder().embed([body])[0])])


def test_checking_one_product_does_not_skip_mismatch_on_another(seed, client):
    good, bad = seed.product(), seed.product()
    seed.review(good, "팬이 조용해요")
    body = "팬 소음이 심해서 아쉬워요"
    doc = seed.review(bad, body)
    _change_embedding(seed, doc, body)

    assert _search(client, [good]).status_code == 200
    response = _search(client, [bad])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_index_mismatch"


def test_verified_product_is_checked_again_after_its_index_changes(seed, client):
    product = seed.product()
    body = "팬이 조용하고 냉각도 잘 됩니다"
    doc = seed.review(product, body)
    assert _search(client, [product]).status_code == 200

    _change_embedding(seed, doc, body)
    response = _search(client, [product])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_index_mismatch"


def test_comparison_checks_each_product_even_when_the_first_has_shorter_reviews(seed, client):
    good, bad = seed.product(), seed.product()
    for body in ["후기 하나", "후기 둘", "후기 셋"]:
        seed.review(good, body)
    body = "팬 소음이 너무 심해서 쓰기 불편합니다"
    doc = seed.review(bad, body)
    _change_embedding(seed, doc, body)

    response = _search(client, [good, bad])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_index_mismatch"
