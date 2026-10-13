"""사용기 근거 문장의 임베딩 — 채우기(backfill)와 가까운 문장 찾기.

"임베딩 행이 없는 문장은 임베딩이 필요하다"가 규칙이다(리뷰 임베딩 `review_embedding_batch` 와 같다). 글을 다시 분석하면 그 글의
문장 행이 지워지고(임베딩은 함께 지워진다) 새로 들어오므로, 다음 채우기에서 새 문장만 임베딩된다.

임베딩은 **문장 검색에만** 쓴다(반영하지 못한 말에 관련 문장을 찾아 보여 주기). 체감 점수에는 들어가지 않는다.
가까운 문장의 순위는 `peripheral_search.search_sentences` 의 `embedding_ranked` 로 넘겨 단어 일치 순위와 합친다.

MOCK_MODE 의 가짜 해시 벡터는 이름에 "test" 가 있는 DB 에만 쓴다 — 개발·운영 DB 에 저장하면 실제 질문 벡터와 비교되어 엉뚱한
결과가 오류 없이 나온다(리뷰 임베딩과 같은 이유).
"""
from __future__ import annotations

import logging
from typing import Any

from src.rag.contracts import EmbeddingError
from src.repo.peripheral_post_repo import DbObservationStore

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 64


def _require_real_vectors(conn, embedder: Any, allow_mock: bool) -> None:
    if not getattr(embedder, "mock", False) or allow_mock:
        return
    dbname = conn.info.dbname or ""
    if "test" not in dbname.lower():
        raise ValueError(
            f"MOCK_MODE 의 가짜 벡터를 테스트용이 아닌 DB({dbname!r})에 저장하려 한다. MOCK_MODE=0 과 OPENAI_API_KEY 를 "
            "설정하거나, 정말 가짜 벡터를 원하면 allow_mock=True 로 호출한다.")


def backfill(conn, embedder, *, limit: int | None = None, batch_size: int = DEFAULT_BATCH_SIZE,
             dry_run: bool = False, allow_mock: bool = False) -> dict:
    """임베딩이 없는 근거 문장을 채운다. {"embedded", "failed", "remaining", "batches"} 를 돌려준다.

    임베딩 호출(네트워크)은 쓰기 트랜잭션 밖에서 한다. 한 배치가 실패하면 그 배치의 id 만 이번 실행에서 건너뛰고 계속한다."""
    store = DbObservationStore(conn)
    if dry_run:
        return {"embedded": 0, "failed": 0, "remaining": store.count_missing_embeddings(), "batches": 0}
    _require_real_vectors(conn, embedder, allow_mock)

    embedded = failed = batches = 0
    failed_ids: list[str] = []
    budget = limit
    model = getattr(embedder, "model", "unknown")
    while budget is None or budget > 0:
        size = batch_size if budget is None else min(batch_size, budget)
        rows = store.list_missing_embeddings(size, exclude_ids=failed_ids)
        if not rows:
            break
        batches += 1
        ids = [str(r["id"]) for r in rows]
        try:
            vectors = embedder.embed([r["sentence"] for r in rows])
        except EmbeddingError:
            failed += len(rows)
            failed_ids.extend(ids)
            log.warning("근거 문장 임베딩 실패: %d건", len(rows), exc_info=True)
        else:
            store.upsert_embeddings(list(zip(ids, vectors)), model)
            embedded += len(rows)
        if budget is not None:
            budget -= len(rows)
    return {"embedded": embedded, "failed": failed, "remaining": store.count_missing_embeddings(), "batches": batches}


def nearest_quote_ids(conn, embedder, query: str, *, limit: int = 20, kind: str | None = None) -> list[str]:
    """질문과 뜻이 가까운 문장의 `quote_id` 를 가까운 순으로(중복 제거). 문장 검색의 임베딩 순위로 쓴다."""
    vector = embedder.embed([query])[0]
    seen: dict[str, None] = {}
    for row in DbObservationStore(conn).nearest(vector, limit=limit, kind=kind):
        seen.setdefault(row["quote_id"])
    return list(seen)
