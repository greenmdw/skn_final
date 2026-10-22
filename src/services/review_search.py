"""리뷰 검색 — 상품별로 질문과 뜻이 가까운 실제 리뷰를 찾는다(GET /reviews/search).

질문을 리뷰와 같은 모델(text-embedding-3-small, 1536차원)로 embedding하고, evidence.review_embedding에서
코사인 거리가 가까운 리뷰를 상품마다 몇 건씩 고른다. 색인 없이 전부 계산한다(0008 "정확 검색부터
시작") — 실제 리뷰 5,653건, 상품당 최대 195건이라 충분하다.

검색 유사도는 점수가 아니다. 추천 점수(리뷰 속성 적합도 Q·R)는 검수된 전체 관측으로 계산하고 이 검색
결과로 대신하지 않는다(docs/추천엔진_리뷰속성_반영계획.md §2.3). 여기서 유사도는 정렬과 관련도 하한에만 쓴다.

상품별 상태를 나눠 돌려준다 — "관련 리뷰 없음"(no_match)은 평가가 나쁘다는 뜻이 아니고, "리뷰 없음"
(no_reviews)이나 "아직 embedding 전"(not_indexed)과도 다르다. 셋을 빈 목록 하나로 뭉치면 화면이
"후기 없음"으로 단정한다.

embedding을 만들 수 없으면(API 실패) 키워드 검색 등으로 몰래 바꾸지 않고 503을 낸다 — 품질이 다른 결과가
같은 모양으로 섞이기 때문이다(src/rag/embedding.py의 "실패한 호출을 다른 벡터로 대신하지 않는다"와 같은 원칙).

저장된 벡터가 지금 embedder와 같은 방식으로 만들어졌는지도 요청마다 상품별 표본으로
확인한다. review_embedding에는 모델 컬럼이 없어서(0008 합의) MOCK_MODE의 해시 벡터로 채운 DB를 실제
embedding으로 검색하거나 그 반대일 때, 데이터만 보고는 알 수 없고 오류 없이 엉뚱한 결과가 나온다. 그래서
상품마다 리뷰 몇 건을 지금 embedder로 다시 만들어 저장된 벡터와 비교하고, 거의 같지 않으면
503(review_index_mismatch)으로 멈춘다. 표본의 텍스트 벡터는 캐시해도 DB 검증 결과는 캐시하지 않는다.

DB 커넥션은 embedding 호출(네트워크) 동안 쥐고 있지 않는다 — 건수·점검 표본을 읽고 놓은 뒤 embedding을
만들고, 다시 커넥션을 받아 점검·검색한다(커넥션 풀을 외부 API 지연만큼 붙잡지 않게).
"""
from __future__ import annotations

import logging
import threading
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from typing import Iterator, Sequence
from uuid import UUID

from src.config import (
    REVIEW_SEARCH_DEFAULT_LIMIT,
    REVIEW_SEARCH_MAX_LIMIT,
    REVIEW_SEARCH_MAX_PRODUCTS,
    REVIEW_SEARCH_MAX_QUERY_CHARS,
    REVIEW_SEARCH_MIN_SIMILARITY,
)
from src.db import get_conn
from src.errors import NotFound, ServiceUnavailable, ValidationFailed
from src.rag.contracts import EmbeddingError
from src.repo.review_embedding_repo import ReviewEmbeddingRepo

log = logging.getLogger(__name__)

# 같은 텍스트를 같은 모델로 다시 만들면 코사인 유사도가 거의 1이고, MOCK 해시 벡터와 실제 벡터(또는 서로 다른
# 모델의 벡터)는 0 근처다. 그 사이 어디든 되지만, 실제 API의 미세한 비결정성을 넉넉히 덮도록 0.95로 둔다.
INDEX_CHECK_MIN_SIMILARITY = 0.95
INDEX_CHECK_SAMPLE = 3

_UNAVAILABLE_MESSAGE = "리뷰 검색을 지금 할 수 없습니다. 잠시 후 다시 시도해주세요."

_default_embedder = None


class CachedEmbedder:
    """같은 텍스트의 embedding을 프로세스 안에서 다시 쓴다(최근 maxsize개).

    채팅처럼 같은 질문이 되풀이될 때 유료 호출을 줄이려는 것이다. 캐시는 인스턴스마다 따로라,
    embedder를 바꾸면 캐시도 새로 시작한다."""

    def __init__(self, inner, maxsize: int = 256):
        self.inner = inner
        self.maxsize = maxsize
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            found = {text: self._cache[text] for text in texts if text in self._cache}
            for text in found:
                self._cache.move_to_end(text)
        missing = [text for text in dict.fromkeys(texts) if text not in found]
        if missing:
            fresh = dict(zip(missing, self.inner.embed(missing)))
            found.update(fresh)
            with self._lock:
                for text, vector in fresh.items():
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                while len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)
        return [found[text] for text in texts]


def default_embedder() -> CachedEmbedder:
    """API가 쓰는 embedder — 리뷰를 채울 때와 같은 OpenAIEmbedder(MOCK_MODE면 해시 벡터)에 캐시를 씌운 것."""
    global _default_embedder
    if _default_embedder is None:
        from src.rag.embedding import OpenAIEmbedder

        _default_embedder = CachedEmbedder(OpenAIEmbedder())
    return _default_embedder


def normalize_query(text: str) -> str:
    """NFKC로 맞추고 공백을 하나로 줄인다 — 캐시 키와 응답의 query가 같은 값을 쓴다."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def product_status(reviews: int, embedded: int, hits: int) -> str:
    if reviews == 0:
        return "no_reviews"
    if embedded == 0:
        return "not_indexed"
    return "ok" if hits else "no_match"


def _validated(product_ids: Sequence[UUID | str], query: str, limit: int) -> tuple[list[UUID], str, int]:
    try:
        ids = list(dict.fromkeys(UUID(str(pid)) for pid in product_ids))   # 순서를 지키며 중복 제거
    except ValueError:
        raise ValidationFailed("상품 ID 형식이 올바르지 않습니다.", field="product_id") from None
    if not ids:
        raise ValidationFailed("검색할 상품을 하나 이상 지정해야 합니다.", field="product_id")
    if len(ids) > REVIEW_SEARCH_MAX_PRODUCTS:
        raise ValidationFailed(f"상품은 한 번에 {REVIEW_SEARCH_MAX_PRODUCTS}개까지 검색할 수 있습니다.",
                               field="product_id")
    q = normalize_query(query)
    if not q:
        raise ValidationFailed("검색할 질문을 입력해야 합니다.", field="q")
    if len(q) > REVIEW_SEARCH_MAX_QUERY_CHARS:
        raise ValidationFailed(f"질문은 {REVIEW_SEARCH_MAX_QUERY_CHARS}자까지 입력할 수 있습니다.", field="q")
    if not 1 <= limit <= REVIEW_SEARCH_MAX_LIMIT:
        raise ValidationFailed(f"limit은 1~{REVIEW_SEARCH_MAX_LIMIT} 사이여야 합니다.", field="limit")
    return ids, q, limit


def _embed(embedder, texts: list[str]) -> list[list[float]]:
    try:
        return embedder.embed(texts)
    except EmbeddingError as exc:
        log.warning("review search: embedding failed (%s)", exc)
        raise ServiceUnavailable(_UNAVAILABLE_MESSAGE, code="review_search_unavailable") from exc


def _check_index(repo, sample: list[dict], vectors: list[list[float]]) -> None:
    """점검 표본을 지금 embedder로 다시 만든 벡터가 저장된 벡터와 거의 같은지 확인한다(모듈 docstring)."""
    similarities = repo.stored_similarity([(row["id"], vector) for row, vector in zip(sample, vectors)])
    if not similarities:        # 그 사이 표본의 embedding이 지워졌다 — 확인하지 못했으니 다음 검색에서 다시 본다
        return
    worst = min(similarities)
    if worst < INDEX_CHECK_MIN_SIMILARITY:
        log.warning(
            "review search: stored embeddings differ from the current embedder (min similarity %.4f < %.2f) — "
            "check MOCK_MODE and REVIEW_EMBEDDING_MODEL against the backfill run, or rerun it with --rebuild",
            worst, INDEX_CHECK_MIN_SIMILARITY,
        )
        raise ServiceUnavailable(_UNAVAILABLE_MESSAGE, code="review_index_mismatch")


def search_with(open_repo, embedder, *, product_ids: Sequence[UUID | str], query: str,
                limit: int = REVIEW_SEARCH_DEFAULT_LIMIT, min_similarity: float | None = None) -> dict:
    """검색 본체. open_repo()는 ReviewEmbeddingRepo를 내주는 컨텍스트 매니저다(커넥션을 두 번 나눠 받으려고).

    min_similarity: 관련도 하한. 기본은 config.REVIEW_SEARCH_MIN_SIMILARITY(실데이터 평가로 정한 0.2).
    반환: {"query", "min_similarity", "products": [{"product_id", "status", "coverage", "hits"}]} —
    products는 요청한 순서(중복 제거)를 따른다.
    """
    ids, q, per_product = _validated(product_ids, query, limit)
    threshold = REVIEW_SEARCH_MIN_SIMILARITY if min_similarity is None else min_similarity

    with open_repo() as repo:
        coverage = repo.coverage(ids)
        unknown = [str(pid) for pid in ids if not coverage[pid]["exists"]]
        if unknown:
            raise NotFound(f"카탈로그에 없는 상품입니다: {', '.join(unknown)}", field="product_id")
        searchable = [pid for pid in ids if coverage[pid]["embedded"]]
        sample = []
        for pid in searchable:
            sample.extend(repo.embedded_sample([pid], INDEX_CHECK_SAMPLE))

    hits: dict[UUID, list[dict]] = {pid: [] for pid in ids}
    if searchable:      # 검색할 벡터가 하나도 없으면 질문 embedding(유료 호출)을 만들지 않는다
        # 점검 표본과 질문을 한 번에 만든다. CachedEmbedder가 변하지 않은 본문은 재사용한다.
        vectors = _embed(embedder, [row["body"] for row in sample] + [q])
        query_vector = vectors[-1]
        with open_repo() as repo:
            if sample:
                _check_index(repo, sample, vectors[:-1])
            for row in repo.search_nearest(query_vector, searchable, per_product=per_product):
                if row["similarity"] >= threshold:
                    hits[row["product_id"]].append(row)

    return {
        "query": q,
        "min_similarity": threshold,
        "products": [
            {
                "product_id": str(pid),
                "status": product_status(coverage[pid]["reviews"], coverage[pid]["embedded"], len(hits[pid])),
                "coverage": {"reviews": coverage[pid]["reviews"], "embedded": coverage[pid]["embedded"]},
                "hits": [
                    {"review_id": str(row["id"]), "body": row["body"], "posted_at": row["posted_at"],
                     "similarity": round(float(row["similarity"]), 4)}
                    for row in hits[pid]
                ],
            }
            for pid in ids
        ],
    }


@contextmanager
def _open_repo() -> Iterator[ReviewEmbeddingRepo]:
    with get_conn() as conn:
        yield ReviewEmbeddingRepo(conn)


def search(*, product_ids: Sequence[UUID | str], query: str, limit: int = REVIEW_SEARCH_DEFAULT_LIMIT,
           min_similarity: float | None = None) -> dict:
    """GET /reviews/search가 부르는 진입점 — 풀 커넥션과 기본 embedder로 search_with를 부른다."""
    return search_with(_open_repo, default_embedder(), product_ids=product_ids, query=query,
                       limit=limit, min_similarity=min_similarity)
