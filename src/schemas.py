"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    list_id: str
    status: str                      # running | done | failed
    items: list[dict] = []
    totals: dict[str, Any] = {}
    reasoning_log: list[dict] = []   # S4-a 5단계
    explanation: dict = {}


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
class ReviewTelemetry(BaseModel):
    """리뷰 작성 폼의 계측값 — 횟수와 시간뿐, 타이핑 내용은 받지 않는다.

    리뷰 진위 축 중 유일하게 소급 수집이 불가능한 것이라 폼이 생기는 지금 넣는다.
    `review_revision.usage_context.telemetry` 로 저장된다 (테이블 변경 없음).
    양성 신호로만 쓴다 — "붙여넣기 없음" 은 무죄 증거가 아니다 (보고 타이핑하는 우회가 너무 쉽다).
    정수 외의 값·모르는 키는 거부한다: 본문이나 키 입력 내용이 이 경로로 들어오면 안 된다.
    """
    model_config = ConfigDict(extra="forbid")

    paste_count: int = Field(0, ge=0, description="붙여넣기 이벤트 수")
    paste_chars: int = Field(0, ge=0, description="붙여넣은 글자 수 합계 (내용 아님)")
    typing_ms: int = Field(0, ge=0, description="키 입력이 있었던 시간 합계 (ms)")
    edit_count: int = Field(0, ge=0, description="삭제·수정 이벤트 수")
    compose_ms: int = Field(0, ge=0, description="폼을 연 뒤 제출까지 (ms)")


class PartReviewIn(BaseModel):
    variant_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = {}
    telemetry: Optional[ReviewTelemetry] = None


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = {}
    telemetry: Optional[ReviewTelemetry] = None


class ProductRiskOut(BaseModel):
    """상품 단위 관측 사실. 점수 없음 — 검토자가 확인·반박할 수 있는 문장과 대조군 중앙값."""
    score: None = None
    evidence: list[str] = []
    reliable_range: Optional[bool] = None
    controls: dict[str, float] = {}
    control_scope: Optional[str] = None
    product_ref: Optional[str] = None            # 관측이 붙은 외부 상품 식별자 (예: ASIN)
    verify_url: Optional[str] = None


class SyntheticDemoOut(BaseModel):
    """합성 데모값 블록 — 화면은 반드시 '합성 데모값' 표지와 함께 보여준다. 실사용자 노출 금지."""
    is_synthetic: Literal[True] = True
    note: str
    cleaned_rating: Optional[float] = None
    cleanse_ratio: Optional[float] = None
    removed_count: Optional[int] = None
    rating_dist: dict[str, Any] = {}
    axis_scores: dict[str, Any] = {}
    top_summaries: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    collected_at: Optional[str] = None


class ReviewSummaryOut(BaseModel):
    """S5 리뷰 상세 — `get_review_authenticity` 계약(기획서 §10-6)과 같은 최상위 키.

    실측 필드(orig_rating · total_reviews · product_manipulation_risk)와 합성 데모 블록을 섞지 않는다.
    cleaned_rating · cleanse_ratio 는 판정기가 없어 항상 null 이다(docs/decisions/0001).
    """
    product_key: str
    product_name: Optional[str] = None
    orig_rating: Optional[float] = None
    cleaned_rating: None = None
    cleanse_ratio: None = None
    axis_scores: dict[str, Any] = {}             # 실측 없음 — 비어 있다. 합성값은 synthetic_demo 에
    total_reviews: int = 0
    top_summaries: list[dict[str, Any]] = []     # 위와 같음
    confidence_note: str
    product_manipulation_risk: ProductRiskOut
    synthetic_demo: Optional[SyntheticDemoOut] = None
