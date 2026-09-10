"""evidence_search(domain, query, filters) — RAG 근거 검색 @tool.

실제: pgvector 하이브리드 쿼리
    WHERE domain=? AND (product_key=? OR product_key IS NULL) [AND age_month_range @> ?]
    ORDER BY embedding <=> :qvec LIMIT k
데모: 시나리오가 넘겨준 미니 코퍼스에서 축(axis) 키워드로 매칭.
저작권: 원문 미저장 — 발췌 요약 + 출처 링크만 보관.
"""
from __future__ import annotations

from typing import Any

from src.config import MOCK_MODE

# 시나리오 로더가 주입하는 미니 코퍼스 (list[dict]: {domain, axis, text, source_url, collected_at})
_MINI_CORPUS: list[dict[str, Any]] = []


def load_mini_corpus(chunks: list[dict[str, Any]]) -> None:
    """시나리오 파일의 corpus 배열을 인메모리 코퍼스로 적재 (데모 전용)."""
    global _MINI_CORPUS
    _MINI_CORPUS = list(chunks)


def evidence_search(domain: str, query: str, filters: dict | None = None, k: int = 3) -> list[dict]:
    """근거 청크 검색.

    Returns:
        각 dict: text(발췌 요약), source_url, collected_at, score. 0건이면 빈 리스트("회색").
    """
    if not MOCK_MODE:
        # TODO: 실제 로직 구현 필요 — 임베딩 쿼리 + pgvector 하이브리드 검색
        raise NotImplementedError("evidence_search: 실제 pgvector 검색 미구현 (MOCK_MODE=0)")

    filters = filters or {}
    axis = filters.get("axis", "")
    hits = [
        {
            "text": c["text"],
            "source_url": c.get("source_url", ""),
            "collected_at": c.get("collected_at", ""),
            "score": round(0.9 - i * 0.1, 2),
        }
        for i, c in enumerate(_MINI_CORPUS)
        if c.get("domain") == domain and (not axis or c.get("axis") == axis)
    ]
    print(f"[MOCK] evidence_search(domain={domain!r}, axis={axis!r}) → {len(hits)}건")
    return hits[:k]
