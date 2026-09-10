"""자료 추출 파이프라인 — 파일 → 텍스트/OCR/이미지 설명/표 → 청크.

ingestion_worker 가 호출. 재시도 가능(idempotency_key). 실패 청크 있는 작업을
조용히 완성 처리하지 않음(§8.1). 자료의 지시문은 실행 명령이 아니라 검색 대상 콘텐츠.
"""
from __future__ import annotations

from uuid import UUID


def run_ingestion(ingestion_id: UUID) -> None:
    """revision 의 file_object 를 파싱 → document_chunk 생성 → embedding.embed → chunk_embedding.
    완료 시 ingestion_job.status='ready'.
    """
    raise NotImplementedError
