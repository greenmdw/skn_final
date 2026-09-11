"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.dto import RecommendationResult


# ── auth ──
class RequestCodeIn(BaseModel):
    email: str


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class TokenOut(BaseModel):
    token: str


# ── session (S1~S3) ──
class SessionOut(BaseModel):
    list_id: str
    browser_token: str


class CategoryIn(BaseModel):
    category: Literal["computer", "baby"]
    mode: Optional[str] = None


class MessageIn(BaseModel):
    text: str


class AnswerIn(BaseModel):
    question_id: str
    selected: list[str]


class SlotPatchIn(BaseModel):
    field: str
    value: Any | None = None


class ConditionStateOut(BaseModel):
    slots: dict[str, Any]
    assumed: dict[str, Any]
    missing: list[str]
    next_questions: list[dict]
    can_recommend: bool


# ── recommend / result (S4) ──
class RecommendResultOut(BaseModel):
    """저장된 추천 실행 결과의 공개 API 계약.

    DB 행 또는 파이프라인 내부 DTO를 그대로 직렬화하지 않고
    ``recommendation_result_out``에서 이 모델로 변환한다.
    """

    recommendation_run_id: str
    list_id: str
    revision_id: str
    status: str                      # running | done | failed | conflict
    candidates: list["RecommendationCandidateOut"] = Field(default_factory=list)
    error_code: str | None = None


class RecommendationEvidenceOut(BaseModel):
    """응답 직전에 다시 권한 검사를 통과한 설명서 인용."""

    evidence_id: str
    text: str
    locator: dict[str, Any] = Field(default_factory=dict)
    file_sha256: str | None = None
    review_status: str | None = None


class RecommendationCandidateOut(BaseModel):
    product_key: str
    variant_key: str | None = None
    product_name: str
    price: int | None = None
    eligibility_status: str
    verification_status: str
    coverage_status: str
    reason: str | None = None
    evidence: list[RecommendationEvidenceOut] = Field(default_factory=list)
    error_code: str | None = None


def recommendation_result_out(result: RecommendationResult) -> RecommendResultOut:
    """서비스 내부 추천 DTO를 공개 HTTP DTO로 명시적으로 변환한다.

    저장소가 반환하는 DB 행을 API 응답으로 직접 노출하지 않도록 서비스 계층은
    먼저 ``RecommendationResult``를 만들고 이 경계를 통과해야 한다.
    """

    return RecommendResultOut(
        recommendation_run_id=result.recommendation_run_id,
        list_id=result.list_id,
        revision_id=result.revision_id,
        status=result.status,
        candidates=[
            RecommendationCandidateOut(
                product_key=candidate.product_key,
                variant_key=candidate.variant_key,
                product_name=candidate.product_name,
                price=candidate.price,
                eligibility_status=candidate.eligibility_status,
                verification_status=candidate.verification_status,
                coverage_status=candidate.coverage_status,
                reason=candidate.reason,
                evidence=[
                    RecommendationEvidenceOut(
                        evidence_id=evidence.evidence_id,
                        text=evidence.text,
                        locator=evidence.locator,
                        file_sha256=evidence.file_sha256,
                        review_status=evidence.review_status,
                    )
                    for evidence in candidate.evidence
                ],
                error_code=candidate.error_code,
            )
            for candidate in result.candidates
        ],
        error_code=result.error_code,
    )


# ── list confirm (S5-a) / report (S5-b) ──
class ConfirmIn(BaseModel):
    name: str
    planned_purchase_at: Optional[str] = None
    target_amount: Optional[int] = None


class ReportOut(BaseModel):
    list_id: str
    name: str
    items: list[dict]
    total: int
    buy_links: list[dict]
    price_watch: Optional[dict] = None


# ── reviews (A7) ──
class PartReviewIn(BaseModel):
    variant_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)
