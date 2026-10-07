"""ReviewEmbeddingRepo의 리뷰 검색 조회 — 상품별 가까운 순서, 합성 제외, 건수, 점검용 표본·유사도.

시드 테스트 DB에는 다른 리뷰가 많으므로 이 테스트가 만든 상품으로만 범위를 좁혀 확인한다.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from review_search_seed import seeded_reviews
from src.repo.review_embedding_repo import ReviewEmbeddingRepo

pytestmark = pytest.mark.db

QUERY = "팬 소음이 심한가요"


@pytest.fixture
def seed():
    with seeded_reviews(os.environ["DATABASE_URL"]) as s:
        yield s


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_coverage_counts_real_reviews_and_embedded_ones(seed):
    reviewed, empty, missing = seed.product(), seed.product(), uuid4()
    seed.review(reviewed, "팬 소음이 조금 있어요")
    seed.review(reviewed, "조용해요", embed=False)
    seed.review(reviewed, "합성 리뷰는 세지 않는다", synthetic=True)

    coverage = ReviewEmbeddingRepo(seed.conn).coverage([reviewed, empty, missing])
    assert coverage[reviewed] == {"exists": True, "reviews": 2, "embedded": 1}
    assert coverage[empty] == {"exists": True, "reviews": 0, "embedded": 0}
    assert coverage[missing] == {"exists": False, "reviews": 0, "embedded": 0}


def test_search_nearest_ranks_within_each_product_and_skips_synthetic(seed):
    first, second = seed.product(), seed.product()
    near = seed.review(first, "팬 소음이 조금 있지만 참을 만해요")
    middle = seed.review(first, "소음 거의 없고 조용합니다")
    seed.review(first, "배송이 빠르고 포장이 꼼꼼해요")
    seed.review(first, "팬 소음이 심한가요 팬 소음", synthetic=True)     # 가장 가깝지만 합성이라 빠져야 한다
    second_near = seed.review(second, "팬 소음이 커서 아쉬워요")
    seed.review(second, "발열 관리가 잘 됩니다")
    seed.review(second, "케이스 안에 쏙 들어가요")

    query_vector = seed.embedder.embed([QUERY])[0]
    rows = ReviewEmbeddingRepo(seed.conn).search_nearest(query_vector, [first, second], per_product=2)

    first_rows = [row for row in rows if row["product_id"] == first]
    second_rows = [row for row in rows if row["product_id"] == second]
    assert [row["id"] for row in first_rows] == [near, middle]             # 상품마다 가까운 순으로 2건씩
    assert len(second_rows) == 2 and second_rows[0]["id"] == second_near
    assert first_rows[0]["body"] == "팬 소음이 조금 있지만 참을 만해요"

    # SQL의 1 - 코사인 거리가 파이썬에서 계산한 코사인 유사도와 같다(벡터는 정규화돼 있다).
    expected = _dot(query_vector, seed.embedder.embed(["팬 소음이 조금 있지만 참을 만해요"])[0])
    assert first_rows[0]["similarity"] == pytest.approx(expected, abs=1e-5)
    assert first_rows[0]["similarity"] > first_rows[1]["similarity"]


def test_embedded_sample_prefers_short_embedded_real_reviews(seed):
    product = seed.product()
    long_review = seed.review(product, "아주 길게 쓴 리뷰입니다 " * 5)
    short_review = seed.review(product, "짧아요")
    seed.review(product, "짧", embed=False)                  # embedding이 없으면 점검할 수 없다
    seed.review(product, "합", synthetic=True)                # 검색 대상이 아니다

    sample = ReviewEmbeddingRepo(seed.conn).embedded_sample([product], 2)
    assert [row["id"] for row in sample] == [short_review, long_review]
    assert sample[0]["body"] == "짧아요"


def test_stored_similarity_tells_same_and_different_embedding_apart(seed):
    product = seed.product()
    body = "팬 소음이 조금 있어요"
    doc = seed.review(product, body)
    repo = ReviewEmbeddingRepo(seed.conn)

    same = seed.embedder.embed([body])[0]
    different = seed.embedder.embed(["배송이 빠르고 포장이 꼼꼼해요"])[0]
    assert repo.stored_similarity([(doc, same)])[0] > 0.999
    assert repo.stored_similarity([(doc, different)])[0] < 0.5
    assert repo.stored_similarity([(uuid4(), same)]) == []           # 저장된 행이 없으면 빠진다
    assert repo.stored_similarity([]) == []
