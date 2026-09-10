"""rag.* 저장소 — ingestion_job / document_chunk / embedding_profile /
chunk_embedding / retrieval_run / retrieval_hit.

C08: 질의·결과의 모델 일치 = (retrieval_run_id,profile_id) / (chunk_id,profile_id) 복합 FK.
검색 대상은 활성 profile · embedding.status='ready' · 권한·상품 적용 필터 통과 청크만(§8.2, C07).
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class RagRepo(Repo):
    # ── 적재 ──
    def create_ingestion(self, revision_id: UUID, pipeline_version: str, idempotency_key: str) -> UUID:
        raise NotImplementedError

    def add_chunk(self, ingestion_id: UUID, *, ordinal: int, content_type: str,
                  content_text: str, locator: dict, content_hash: str,
                  search_vector) -> UUID:
        """search_vector 는 확정된 한국어 tokenizer 로 생성(§8.2)."""
        raise NotImplementedError

    def active_profile(self) -> dict | None:
        """embedding_profile.status='active' 하나."""
        raise NotImplementedError

    def upsert_embedding(self, chunk_id: UUID, profile_id: UUID, embedding: list[float],
                         input_hash: str) -> None:
        raise NotImplementedError

    def revoke_embedding(self, chunk_id: UUID, profile_id: UUID) -> None:
        """철회 시 행 삭제 대신 embedding=NULL, status='revoked'(§8.3)."""
        raise NotImplementedError

    # ── 검색 실행 기록 ──
    def start_run(self, recommendation_run_id: UUID, profile_id: UUID, *, purpose: str,
                  query_text: str, scope_snapshot: dict, retrieval_config: dict) -> UUID:
        raise NotImplementedError

    def add_hit(self, retrieval_run_id: UUID, chunk_id: UUID, profile_id: UUID, *,
                rank_no: int, vector_score=None, keyword_score=None,
                rerank_score=None, selected_for_context: bool = False) -> UUID:
        raise NotImplementedError

    def complete_run(self, retrieval_run_id: UUID, status: str = "completed") -> None:
        raise NotImplementedError

    # ── 하이브리드 검색 (evidence_search 가 호출) ──
    def hybrid_search(self, *, profile_id: UUID, query_vec: list[float], query_text: str,
                      filters: dict, k: int) -> list[dict]:
        """구조 필터(도메인·제품·월령) + 벡터 유사도 + 키워드 를 한 쿼리로.
        WHERE domain=? AND (product_key=? OR product_key IS NULL) [AND age_month_range @> ?]
        ORDER BY embedding <=> :qvec LIMIT k
        """
        raise NotImplementedError
