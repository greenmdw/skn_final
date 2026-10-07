"""리뷰 검색 서비스 단위 테스트 — DB·네트워크 없이 검증·상태 판정·캐시·점검·실패 처리를 확인한다.

repo는 같은 메서드를 가진 가짜로, embedder는 호출을 기록하는 가짜로 바꾼다(src/services/review_search.py의
search_with가 open_repo·embedder를 주입받는다). SQL 자체는 tests/test_review_search_repo.py가 본다.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.errors import NotFound, ServiceUnavailable, ValidationFailed
from src.rag.contracts import EmbeddingError
from src.services import review_search
from src.services.review_search import CachedEmbedder, normalize_query, product_status, search_with

pytestmark = pytest.mark.unit


class _FakeRepo:
    """ReviewEmbeddingRepo의 검색용 메서드만 흉내 낸다. 호출 인자를 기록한다."""

    def __init__(self, coverage, rows=(), sample=(), stored_similarity=(1.0,)):
        self._coverage = coverage
        self._rows = list(rows)
        self._sample = list(sample)
        self._stored_similarity = list(stored_similarity)
        self.calls = []

    def coverage(self, product_ids):
        self.calls.append(("coverage", list(product_ids)))
        return {pid: self._coverage.get(pid, {"exists": False, "reviews": 0, "embedded": 0}) for pid in product_ids}

    def embedded_sample(self, product_ids, limit):
        self.calls.append(("embedded_sample", list(product_ids), limit))
        return self._sample[:limit]

    def stored_similarity(self, rows):
        self.calls.append(("stored_similarity", [review_id for review_id, _ in rows]))
        return self._stored_similarity[:len(rows)]

    def search_nearest(self, query_vector, product_ids, *, per_product):
        self.calls.append(("search_nearest", list(product_ids), per_product))
        return [row for row in self._rows if row["product_id"] in product_ids]

    def called(self, name):
        return [call for call in self.calls if call[0] == name]


class _FakeEmbedder:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("embedding_unavailable")
        return [[float(len(text)), float(sum(map(ord, text)))] for text in texts]   # 텍스트마다 다른 벡터


def _row(product_id, body, similarity):
    return {"id": uuid4(), "product_id": product_id, "body": body,
            "posted_at": datetime(2026, 9, 30, tzinfo=timezone.utc), "similarity": similarity}


def _search(repo, embedder, product_ids, query="팬 소음이 심한가요", **kwargs):
    kwargs.setdefault("min_similarity", 0.3)
    return search_with(lambda: nullcontext(repo), embedder, product_ids=product_ids, query=query, **kwargs)


# ── 질문 정규화·입력 검증 ──

def test_normalize_query_applies_nfkc_and_collapses_whitespace():
    assert normalize_query("  ＲＴＸ　４０７０   코일   소음\n있나요 ") == "RTX 4070 코일 소음 있나요"


@pytest.mark.parametrize("product_ids, query, limit, field", [
    ([], "소음", 3, "product_id"),
    ([uuid4() for _ in range(6)], "소음", 3, "product_id"),
    (["not-a-uuid"], "소음", 3, "product_id"),
    ([uuid4()], "   ", 3, "q"),
    ([uuid4()], "가" * 201, 3, "q"),
    ([uuid4()], "소음", 0, "limit"),
    ([uuid4()], "소음", 11, "limit"),
])
def test_invalid_input_is_rejected_before_touching_db(product_ids, query, limit, field):
    repo = _FakeRepo({})
    embedder = _FakeEmbedder()
    with pytest.raises(ValidationFailed) as exc_info:
        _search(repo, embedder, product_ids, query=query, limit=limit)
    assert exc_info.value.field == field
    assert repo.calls == [] and embedder.calls == []


def test_duplicate_product_ids_are_collapsed_keeping_request_order():
    first, second = uuid4(), uuid4()
    repo = _FakeRepo({first: {"exists": True, "reviews": 0, "embedded": 0},
                      second: {"exists": True, "reviews": 0, "embedded": 0}})
    result = _search(repo, _FakeEmbedder(), [second, first, str(second)])
    assert [p["product_id"] for p in result["products"]] == [str(second), str(first)]
    assert repo.called("coverage") == [("coverage", [second, first])]


# ── 상태 판정 ──

@pytest.mark.parametrize("reviews, embedded, hits, expected", [
    (0, 0, 0, "no_reviews"),
    (5, 0, 0, "not_indexed"),
    (5, 5, 0, "no_match"),
    (5, 2, 1, "ok"),
])
def test_product_status(reviews, embedded, hits, expected):
    assert product_status(reviews, embedded, hits) == expected


# ── 검색 흐름 ──

def test_unknown_product_is_404_without_embedding():
    known = uuid4()
    unknown = uuid4()
    repo = _FakeRepo({known: {"exists": True, "reviews": 3, "embedded": 3}})
    embedder = _FakeEmbedder()
    with pytest.raises(NotFound) as exc_info:
        _search(repo, embedder, [known, unknown])
    assert str(unknown) in exc_info.value.message
    assert embedder.calls == []


def test_products_without_embedded_reviews_never_call_embedding_api():
    """검색할 벡터가 하나도 없으면 유료 호출(질문 embedding)을 만들지 않는다."""
    no_reviews, not_indexed = uuid4(), uuid4()
    repo = _FakeRepo({no_reviews: {"exists": True, "reviews": 0, "embedded": 0},
                      not_indexed: {"exists": True, "reviews": 4, "embedded": 0}})
    embedder = _FakeEmbedder()
    result = _search(repo, embedder, [no_reviews, not_indexed])
    assert embedder.calls == []
    assert repo.called("search_nearest") == []
    assert [(p["status"], p["coverage"], p["hits"]) for p in result["products"]] == [
        ("no_reviews", {"reviews": 0, "embedded": 0}, []),
        ("not_indexed", {"reviews": 4, "embedded": 0}, []),
    ]


def test_hits_below_threshold_are_dropped_and_status_follows():
    relevant, unrelated = uuid4(), uuid4()
    rows = [_row(relevant, "팬 소음이 조금 있지만 참을 만해요", 0.41234),
            _row(relevant, "소음 거의 없고 조용합니다", 0.125),
            _row(unrelated, "배송이 빠르고 포장이 꼼꼼해요", 0.0)]
    repo = _FakeRepo({relevant: {"exists": True, "reviews": 3, "embedded": 2},
                      unrelated: {"exists": True, "reviews": 1, "embedded": 1}},
                     rows=rows, sample=[{"id": uuid4(), "body": "짧은 리뷰"}])
    result = _search(repo, _FakeEmbedder(), [relevant, unrelated], limit=2)

    assert result["query"] == "팬 소음이 심한가요"
    assert result["min_similarity"] == 0.3
    first, second = result["products"]
    assert first["product_id"] == str(relevant) and first["status"] == "ok"
    assert first["coverage"] == {"reviews": 3, "embedded": 2}          # 일부만 검색했다는 사실을 그대로 낸다
    assert [hit["body"] for hit in first["hits"]] == ["팬 소음이 조금 있지만 참을 만해요"]
    hit = first["hits"][0]
    assert UUID(hit["review_id"]) == rows[0]["id"] and hit["similarity"] == 0.4123
    assert hit["posted_at"] == rows[0]["posted_at"]
    assert second["status"] == "no_match" and second["hits"] == []   # 관련 리뷰 없음 ≠ 리뷰 없음
    assert repo.called("search_nearest") == [("search_nearest", [relevant, unrelated], 2)]


def test_default_threshold_comes_from_config(monkeypatch):
    monkeypatch.setattr(review_search, "REVIEW_SEARCH_MIN_SIMILARITY", 0.5)
    pid = uuid4()
    repo = _FakeRepo({pid: {"exists": True, "reviews": 1, "embedded": 1}},
                     rows=[_row(pid, "팬 소음이 조금 있어요", 0.41)], sample=[{"id": uuid4(), "body": "짧은 리뷰"}])
    result = search_with(lambda: nullcontext(repo), _FakeEmbedder(), product_ids=[pid], query="소음")
    assert result["min_similarity"] == 0.5
    assert result["products"][0]["status"] == "no_match"


def test_embedding_failure_is_503_not_a_silent_fallback():
    pid = uuid4()
    repo = _FakeRepo({pid: {"exists": True, "reviews": 2, "embedded": 2}},
                     rows=[_row(pid, "팬 소음", 0.9)], sample=[{"id": uuid4(), "body": "짧은 리뷰"}])
    with pytest.raises(ServiceUnavailable) as exc_info:
        _search(repo, _FakeEmbedder(fail=True), [pid])
    assert exc_info.value.code == "review_search_unavailable"
    assert exc_info.value.http_status == 503
    assert repo.called("search_nearest") == []


# ── 저장된 벡터 일치 점검 ──

def test_each_search_checks_index_and_reuses_cached_sample_embeddings():
    pid = uuid4()
    sample = [{"id": uuid4(), "body": "짧은 리뷰"}, {"id": uuid4(), "body": "조금 더 긴 리뷰"}]
    repo = _FakeRepo({pid: {"exists": True, "reviews": 2, "embedded": 2}},
                     rows=[_row(pid, "팬 소음이 있어요", 0.8)], sample=sample, stored_similarity=[0.999, 0.998])
    inner = _FakeEmbedder()
    embedder = CachedEmbedder(inner)

    _search(repo, embedder, [pid])
    assert inner.calls == [["짧은 리뷰", "조금 더 긴 리뷰", "팬 소음이 심한가요"]]   # 표본 + 질문을 한 번에
    assert repo.called("embedded_sample") == [("embedded_sample", [pid], review_search.INDEX_CHECK_SAMPLE)]
    assert repo.called("stored_similarity") == [("stored_similarity", [row["id"] for row in sample])]

    _search(repo, embedder, [pid], query="발열은 어때요")
    assert inner.calls[-1] == ["발열은 어때요"]                                   # 표본은 텍스트 캐시에서 재사용
    assert len(repo.called("embedded_sample")) == 2
    assert len(repo.called("stored_similarity")) == 2
    _search(repo, embedder, [pid], query="발열은 어때요")
    assert len(inner.calls) == 2
    assert len(repo.called("stored_similarity")) == 3


def test_index_mismatch_is_503_and_is_rechecked_next_time():
    """MOCK 해시 벡터로 채운 DB를 실제 embedding으로 검색하는 식의 불일치 — 엉뚱한 결과 대신 멈춘다."""
    pid = uuid4()
    repo = _FakeRepo({pid: {"exists": True, "reviews": 2, "embedded": 2}},
                     rows=[_row(pid, "팬 소음", 0.9)], sample=[{"id": uuid4(), "body": "짧은 리뷰"}],
                     stored_similarity=[0.02])
    embedder = _FakeEmbedder()
    for _ in range(2):
        with pytest.raises(ServiceUnavailable) as exc_info:
            _search(repo, embedder, [pid])
        assert exc_info.value.code == "review_index_mismatch"
    assert repo.called("search_nearest") == []
    assert len(repo.called("embedded_sample")) == 2          # 실패는 기억하지 않는다 — 고친 뒤 재시작 없이 풀린다


# ── 질문 embedding 캐시 ──

def test_cached_embedder_reuses_vectors_and_keeps_order():
    inner = _FakeEmbedder()
    cached = CachedEmbedder(inner, maxsize=10)
    first = cached.embed(["소음", "발열", "소음"])
    assert inner.calls == [["소음", "발열"]]                   # 한 호출 안의 중복도 한 번만 만든다
    assert first[0] == first[2] and first[0] != first[1]
    assert cached.embed(["발열", "소음"]) == [first[1], first[0]]
    assert inner.calls == [["소음", "발열"]]                   # 두 번째는 전부 캐시


def test_cached_embedder_evicts_least_recently_used():
    inner = _FakeEmbedder()
    cached = CachedEmbedder(inner, maxsize=2)
    cached.embed(["a"])
    cached.embed(["bb"])
    cached.embed(["a"])            # a를 최근으로 올린다
    cached.embed(["ccc"])          # 가장 오래된 bb가 빠진다
    cached.embed(["a", "bb"])
    assert inner.calls == [["a"], ["bb"], ["ccc"], ["bb"]]


def test_cached_embedder_does_not_cache_failures():
    inner = _FakeEmbedder(fail=True)
    cached = CachedEmbedder(inner)
    for _ in range(2):
        with pytest.raises(EmbeddingError):
            cached.embed(["소음"])
    assert len(inner.calls) == 2
