"""리뷰 서비스 — A7 부품 리뷰 / 전체 PC 리뷰 작성 · 게시 · 개봉/구매 인증.

부품 리뷰 = product/variant 대상, 자기신고. 전체 PC 리뷰 = pc_build_version/component 고정 +
assembled_self_reported 확인 후 게시(C11). 외부 리뷰 원문 미저장.
"""
from __future__ import annotations

from uuid import UUID

from src.schemas import ReviewTelemetry

TELEMETRY_KEY = "telemetry"


def usage_context_with_telemetry(usage_context: dict | None, telemetry: ReviewTelemetry | None) -> dict:
    """`review_revision.usage_context` 에 폼 계측값을 `telemetry` 키로 넣는다.

    없으면 키를 만들지 않는다 — 빈 dict 나 0 으로 채우면 "붙여넣기 0회 = 직접 씀" 으로 읽히는데
    그건 이 신호가 말하지 않는 것이다. 있을 때만, 정수만 들어간다(ReviewTelemetry 가 거른다).
    """
    ctx = dict(usage_context or {})
    if telemetry is not None:
        ctx[TELEMETRY_KEY] = telemetry.model_dump()
    return ctx


def write_part_review(user_id: UUID, variant_id: UUID, *, rating: int, title: str,
                      body: str, axis_scores: dict, telemetry: ReviewTelemetry | None = None) -> dict:
    """usage_context = usage_context_with_telemetry(…, telemetry) 로 add_revision 에 넘긴다."""
    raise NotImplementedError


def write_build_review(user_id: UUID, build_version_id: UUID, *, rating: int, title: str,
                       body: str, axis_scores: dict, telemetry: ReviewTelemetry | None = None) -> dict:
    """build.owner == author, build_version published, usage_status assembled_self_reported 확인.
    usage_context 는 write_part_review 와 같은 규칙."""
    raise NotImplementedError


def publish(review_id: UUID, user_id: UUID) -> None:
    raise NotImplementedError


def list_pending_for_user(user_id: UUID) -> dict:
    """A7: 작성해야 할 리뷰 / 개봉 확인 / 내가 쓴 리뷰."""
    raise NotImplementedError
