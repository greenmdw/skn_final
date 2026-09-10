"""텍스트 → 임베딩 벡터 (관리형 임베딩 모델).

활성 embedding_profile 하나만 운영 (§8.2). 질의와 청크를 같은 profile 로 임베딩.
차원 D 는 모델 확정 후 rag.chunk_embedding.embedding vector(D) 와 함께 고정.
"""
from __future__ import annotations

from src.config import MOCK_MODE


def embed(texts: list[str]) -> list[list[float]]:
    """텍스트 배치 → 벡터 배치. 전처리 버전은 embedding_profile.preprocessing_version."""
    if MOCK_MODE:
        raise NotImplementedError("embed: MOCK — evidence_search 는 미니 코퍼스 사용")
    # TODO: 실제 로직 구현 필요 — provider SDK 임베딩 호출
    raise NotImplementedError
