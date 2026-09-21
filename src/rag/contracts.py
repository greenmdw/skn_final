"""RAG 경계 — 임베딩 오류 타입. 검색 관련 성공 응답이 곧 검증된 사실을 뜻하지는 않는다."""

from __future__ import annotations


class EmbeddingError(RuntimeError):
    pass
