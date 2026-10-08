"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from src.dto import ReviewScoreDetail as ReviewScoreDetailDTO


# ── auth: 코드 로그인 (보류 — §G 재사용 예정) ──
class RequestCodeIn(BaseModel):
    email: str


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class TokenOut(BaseModel):
    token: str


# ── auth: 이메일+비밀번호 (§A-4) ──
class SignupIn(BaseModel):
    email: str
    password: str
    display_name: str
    terms_agreed: bool
    privacy_agreed: bool
    marketing_agreed: bool = False


class LoginIn(BaseModel):
    email: str
    password: str
    remember: bool = False


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    marketing_agreed: bool
    created_at: datetime


class UserEnvelopeOut(BaseModel):
    """프론트 TF_AUTH가 `data.user`로 읽는다(frontend/js/api.js) — 사용자 응답은 항상 이 봉투로 감싼다."""

    user: UserOut


class ProfilePatchIn(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    marketing_agreed: Optional[bool] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class WithdrawIn(BaseModel):
    password: str


class EmailAvailabilityOut(BaseModel):
    available: bool


# ── session (S1~S3) ──
class SessionOut(BaseModel):
    list_id: str


class CategoryIn(BaseModel):
    category: Literal["computer"]
    mode: Optional[str] = None


class MessageIn(BaseModel):
    text: str = Field(max_length=500)


class AnswerIn(BaseModel):
    question_id: str
    selected: list[Any]


class SlotPatchIn(BaseModel):
    field: str
    value: Any | None = None


# ── PC 견적 점검: 사양 텍스트 매칭 미리보기 (세션 없이 호출) ──
class OwnedPartsPreviewIn(BaseModel):
    # 슬롯 이름(원문 그대로, 예: "CPU"·"그래픽카드") -> 사용자가 적은 자유 텍스트.
    current_specs: dict[str, str] = Field(default_factory=dict)
    # 자유 형식 텍스트(업로드 파일 전체·붙여넣은 견적 설명). 있으면 슬롯별로 추출해 current_specs에
    # 채운다 — 같은 슬롯이 current_specs에도 이미 있으면 그 값(명시값)을 우선한다.
    text: str | None = None
    # 견적·부품 목록이 찍힌 화면 캡처. "data:image/png;base64,..." 형식의 데이터 URL 그대로 —
    # text와 동시에 오면 이걸 우선한다. 처리 후 저장하지 않는다(요청 처리 중에만 메모리에 존재).
    image_data_url: str | None = None


class OwnedPartsPreviewRow(BaseModel):
    part: str
    original: str
    matched: str
    matched_note: str
    state: Literal["ok", "warn"]
    # state(ok/warn)보다 세분화된 값 — 화면이 "확정"과 "모호함"을 구분해서 보여줄 때 쓴다.
    # confirmed=단일 확정 · ambiguous=후보 여럿 동점(공통값만 사용, candidate_count 참고) ·
    # candidate=가장 비슷한 제품(다른 제품일 수 있음) · inferred=글·모델명 규칙으로 일부만 읽음 ·
    # unmatched=대응 자체를 못 찾음.
    match_status: Literal["confirmed", "ambiguous", "candidate", "inferred", "unmatched"] = "confirmed"
    candidate_count: int | None = None   # match_status가 ambiguous일 때만(동점 후보 개수)
    # "live" 면 이 행의 값(전부 또는 일부)이 실시간 검색 결과다 — 카탈로그 정식 값이 아니다. 상태(ok/warn)는 그대로다.
    value_source: Literal["live"] | None = None


class OwnedPartsPreviewOut(BaseModel):
    rows: list[OwnedPartsPreviewRow] = Field(default_factory=list)


# ── PC 견적 점검: 비교 분석 결과 저장 (CHK-04·CHK-09) ──
class QuoteCompatCheckOut(BaseModel):
    axis: str
    label: str
    state: Literal["ok", "fail", "unknown", "skipped"]   # unknown = 스펙을 몰라 확인 못 함(비호환 아님)
    detail: str


class QuoteCompatOut(BaseModel):
    checks: list[QuoteCompatCheckOut] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    incompatible: list[str] = Field(default_factory=list)   # 확정된 비호환 검사(axis)만


class QuotePriceRowOut(BaseModel):
    part: str
    matched: str | None = None          # 카탈로그와 같은 제품으로 확정된 경우의 카탈로그 이름
    quoted: int | None = None           # 견적에 적힌 가격(원)
    catalog: int | None = None          # 우리 카탈로그 가격(원)
    quantity: int = 1                   # 견적 한 줄의 개수("16GB x2" = 2) — 카탈로그 가격을 이 개수에 맞춰 견줌
    diff: int | None = None
    diff_pct: float | None = None
    state: Literal["cheaper", "similar", "pricier", "no_quote_price", "no_catalog"]
    detail: str


class QuotePricesOut(BaseModel):
    available: bool                     # False = 견적에 가격이 없어 비교하지 않음(P10)
    reason: str | None = None
    rows: list[QuotePriceRowOut] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class QuoteConditionsIn(BaseModel):
    """용도 대비 균형(CHK-06)을 판단할 사용자 조건 — 추천 조건과 같은 값 체계."""
    purpose: Literal["game", "creation", "office", "study", "other"] | None = None
    resolution: Literal["FHD_144", "QHD_165", "4K"] | None = None
    priority: Literal["performance", "value", "quiet"] | None = None    # 안 주면 추천엔진 기본 가중치(우리 추천 비교용)
    games: list[str] = Field(default_factory=list, max_length=15)
    budget_max: int | None = Field(default=None, ge=0, le=100_000_000)


class QuoteReviewIn(OwnedPartsPreviewIn):
    # None = 보내지 않음(수정 시 이전 조건 유지), 값이 없는 객체({}) = 조건 지움.
    conditions: QuoteConditionsIn | None = None


class QuoteBalanceRowOut(BaseModel):
    part: str
    aspect: str                                         # 성능 등급 · VRAM · 용량 · 예산 · 예산 비중
    state: Literal["short", "excess", "ok", "unknown"]  # 부족 · 과함 · 충족 · 확인 못 함
    detail: str
    measured: float | None = None
    target: float | None = None


class QuoteBalanceOut(BaseModel):
    available: bool                                     # False = 조건이 없어 판단하지 않음
    reason: str | None = None
    requirement: dict[str, Any] | None = None           # 판단 기준(용도·해상도 → 요구 등급·용량)
    rows: list[QuoteBalanceRowOut] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class QuoteCompareSideOut(BaseModel):
    name: str | None = None
    price: int | None = None
    perf_tier: float | None = None
    confirmed: bool | None = None       # 견적 쪽만 — 카탈로그와 같은 제품으로 확정됐는가
    quantity: int | None = None


class QuoteCompareRowOut(BaseModel):
    part: str
    quote: QuoteCompareSideOut | None = None     # None = 견적에 이 부품이 없음
    ours: QuoteCompareSideOut
    same_product: bool
    price_diff: int | None = None                # 견적 − 우리 추천
    price_diff_pct: float | None = None
    price_state: Literal["cheaper", "similar", "pricier"] | None = None
    tier_diff: float | None = None
    detail: str


class QuoteCompareOut(BaseModel):
    available: bool                              # False = 같은 조건을 만들 수 없어 비교하지 않음
    reason: str | None = None
    conditions_used: dict[str, Any] | None = None
    ours: dict[str, Any] | None = None           # 우리 추천 구성(items · total · link_check · incompatible)
    rows: list[QuoteCompareRowOut] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class QuotePartCompareOut(BaseModel):
    slot: str
    baseline: dict[str, Any]                            # 견적 속 부품(이름·가격·성능 등급·리뷰)
    candidates: list[dict[str, Any]] = Field(default_factory=list)   # 비교 대상 — 스펙 표·가격 차이·호환 변화·리뷰
    unmatched_targets: list[str] = Field(default_factory=list)       # 요청했지만 카탈로그에서 못 찾은 제품
    note: str | None = None


class LiveSpecLookupOut(BaseModel):
    """DB 미보유 부품 실시간 검색 결과(docs/미보유부품_실시간스펙검색_설계.md §5).
    relevant=False거나 supported_fields가 전부 비어 있으면 화면은 "찾지 못했다"로 보여야 한다 —
    카탈로그 정식 등재 값이 아니라는 안내도 같이 표시한다(프론트 몫, 5단계)."""

    slot: str
    query: str
    relevant: bool
    supported_fields: dict[str, Any]
    source_url: str | None = None
    # 임시 부품 저장소 메타(설계 §9): 언제 확인한 값인지, 사람이 확인했는지, 저장소에서 가져왔는지.
    fetched_at: str | None = None
    status: Literal["unreviewed", "confirmed", "rejected"] = "unreviewed"
    cached: bool = False
    # 참고가(LIVE_REFERENCE_PRICE=1 이고 만료 전일 때만) — 합계·가격 비교·후보와 무관한 참고 표시용.
    reference_price: int | None = None
    reference_price_source_url: str | None = None
    reference_price_at: str | None = None


class QuoteApplyIn(BaseModel):
    # 새 계획에서 업그레이드 대상으로 삼을 부품(견적에 적힌 값은 버리고 추천이 다시 고른다).
    # 나머지 부품은 견적에 적힌 대로 유지한다.
    slots: list[str] = Field(min_length=1, max_length=8)


class QuoteApplyOut(BaseModel):
    list_id: str                            # 새로 만들어진 계획(세션) id
    slots: list[str]
    missing: list[str] = Field(default_factory=list)   # 비어 있지 않으면 이 조건들을 먼저 채워야 추천을 받을 수 있다
    run_id: str | None = None               # missing 이 비어 있으면 즉시 추천을 시작한 run id


class QuoteChatContextIn(BaseModel):
    type: Literal["saved_quote_comparison"]
    comparison_id: UUID


class QuoteChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    client_message_id: str | None = Field(default=None, max_length=100)   # 같은 요청의 재전송이면 저장된 답을 돌려준다
    context: QuoteChatContextIn | None = None                             # 저장 견적 비교에 대한 질문


class QuoteGuideRefOut(BaseModel):
    id: str
    slot: str
    kind: Literal["care", "install"]
    text: str
    score: float | None = None


class QuoteChatOut(BaseModel):
    reply: str
    evidence: list[str] = Field(default_factory=list)      # 답의 근거가 된 분석 블록(호환 검사 · 가격 비교 …)
    via: Literal["agent", "rules"]                          # 어느 경로로 답했는가
    message_id: str | None = None
    answer_id: str | None = None
    guide_refs: list[QuoteGuideRefOut] = Field(default_factory=list)
    visuals: list[dict[str, Any]] = Field(default_factory=list)     # 서버가 조립한 표·제품 카드·호환 자료
    display_target: Literal["saved_comparison_explanation", "chat"] = "chat"
    duplicate_of: str | None = None                                  # 같은 질문이면 재사용한 원래 답의 answer_id
    created_at: str | None = None


class QuoteChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    text: str
    created_at: str
    # 저장 견적 비교 질문의 복원 정보 — 새로고침 뒤에도 질문별 해설과 자료를 그대로 보인다(없으면 비어 있다).
    comparison_id: str | None = None
    answer_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    guide_refs: list[QuoteGuideRefOut] = Field(default_factory=list)
    visuals: list[dict[str, Any]] = Field(default_factory=list)
    via: Literal["agent", "rules"] | None = None
    display_target: Literal["saved_comparison_explanation", "chat"] | None = None
    duplicate_of: str | None = None


# BE-09 저장 견적 비교
class QuoteSavedComparisonIn(BaseModel):
    saved_list_id: UUID
    saved_revision_no: int | None = Field(default=None, ge=1)


class QuoteComparisonProductOut(BaseModel):
    product_id: str | None = None
    product_key: str | None = None
    name: str | None = None
    image_url: str | None = None
    quantity: int = 1
    line_total: int | None = None


class QuoteComparisonRowOut(BaseModel):
    category: str
    same_product: bool                                  # 문자열이 아니라 카탈로그 제품 키로 판정
    received: QuoteComparisonProductOut | None = None
    saved: QuoteComparisonProductOut | None = None
    price_diff: int | None = None                       # 저장 견적 − 받은 견적(품목 합계 기준)


class QuoteComparisonSummaryOut(BaseModel):
    changed_count: int
    largest_price_difference_category: str | None = None
    text: str


class QuoteSavedComparisonOut(BaseModel):
    comparison_id: str
    received_total: int
    saved_total: int
    total_diff: int                                      # 가격이 양쪽에 모두 있는 부품(comparable_categories)만의 차이(저장 − 받은)
    comparable_categories: list[str] = Field(default_factory=list)
    excluded_received_categories: list[str] = Field(default_factory=list)   # 받은 견적에 가격이 없어 합계에서 뺀 부품군
    rows: list[QuoteComparisonRowOut]
    brief_summary: QuoteComparisonSummaryOut
    saved: dict[str, Any] = Field(default_factory=dict)                      # 비교한 저장 견적(list_id·revision_no·name)
    labels: dict[str, str] = Field(default_factory=dict)                     # received/saved 쪽의 이름(견적 이름 — 없으면 받은 견적/저장 견적)
    sides: dict[str, Any] | None = None                                      # 견적끼리 비교할 때 각 견적의 합계·호환 요약
    kind: str | None = None
    computed_at: str


class QuoteChatHistoryOut(BaseModel):
    messages: list[QuoteChatMessageOut] = Field(default_factory=list)


class QuoteReviewInputOut(BaseModel):
    current_specs: dict[str, str] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    input_hash: str


class QuoteReviewOut(BaseModel):
    list_id: str
    version: int
    input: QuoteReviewInputOut
    parts: list[OwnedPartsPreviewRow] = Field(default_factory=list)   # 인식·카탈로그 매칭 표
    compat: QuoteCompatOut
    prices: QuotePricesOut | None = None    # 가격 비교(CHK-05) — 이 기능 이전에 저장된 결과에는 없다
    balance: QuoteBalanceOut | None = None  # 용도 대비 균형(CHK-06) — 이 기능 이전에 저장된 결과에는 없다
    compare: QuoteCompareOut | None = None  # 우리 추천과 비교(CHK-07) — 이 기능 이전에 저장된 결과에는 없다
    computed_at: str


# ── 받은 견적 점검: 여러 장 업로드 초안 (docs 개발요청서 BE-01~04·07) ──
class QuoteCapabilitiesOut(BaseModel):
    image_extraction: bool
    supported_types: list[str]
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    text_max_chars: int


class QuoteDraftSourceOut(BaseModel):
    id: str
    type: Literal["image", "text", "replacement", "manual"]
    file_name: str | None = None
    sort_order: int
    status: Literal["completed", "failed"]
    error_code: str | None = None


class QuoteDraftItemOut(BaseModel):
    id: str
    category: str
    raw_text: str
    normalized_name: str                                 # 상품코드·가격이 없는 이름
    product_code: str | None = None
    quantity: int = 1
    quote_unit_price: int | None = None
    quote_line_total: int | None = None
    quote_price_type: Literal["unit", "line_total", "unknown"] = "unknown"
    matched_product_id: str | None = None                # 카탈로그와 확정 대응(confirmed)일 때만
    matched_product_key: str | None = None               # 저장 견적과 "같은 제품"을 가를 때 쓰는 키(제품 ID와 한 쌍)
    matched_name: str | None = None
    image_url: str | None = None                         # catalog.product.image_url, 없으면 null
    match_status: Literal["confirmed", "ambiguous", "candidate", "inferred", "unmatched"] = "unmatched"
    candidate_count: int | None = None
    source_ids: list[str] = Field(default_factory=list)
    selected_for_analysis: bool = False
    user_edited: bool = False
    # 이 항목의 실시간 검색 값이 임시 저장소에 있다(저장되지 않는 표시 — 응답을 만들 때마다 저장소를 읽어 채운다).
    live_value: bool = False


class QuoteDraftGroupOut(BaseModel):
    """견적 묶음 — 올린 이미지(텍스트) 하나가 견적 하나. 서로 다른 견적을 올렸을 때 묶음별로 분석·비교한다."""
    id: str
    name: str
    source_ids: list[str]
    item_ids: list[str]


class QuoteDraftOut(BaseModel):
    draft_id: str
    version: int
    sources: list[QuoteDraftSourceOut]
    items: list[QuoteDraftItemOut]
    selected_item_by_category: dict[str, str] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    question: str | None = None
    partial_success: bool = False
    groups: list[QuoteDraftGroupOut] = Field(default_factory=list)
    created_at: str


class QuoteDraftAnalysisIn(BaseModel):
    source_ids: list[str] | None = Field(default=None, max_length=10)   # 주면 그 견적(이미지)의 항목만 분석


class QuoteQuoteComparisonIn(BaseModel):
    a_source_ids: list[str] = Field(min_length=1, max_length=10)
    b_source_ids: list[str] = Field(min_length=1, max_length=10)


class QuoteDraftItemEdit(BaseModel):
    id: str
    delete: bool = False                                  # true 면 이 항목을 지운다(다른 필드는 무시)
    category: str | None = None                           # 부품군을 잘못 읽었을 때 바꾼다(그 부품군 카탈로그에서 다시 맞춘다)
    normalized_name: str | None = Field(default=None, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=20)
    quote_line_total: int | None = Field(default=None, ge=0, le=100_000_000)


class QuoteDraftItemAddIn(BaseModel):
    expected_version: int
    category: str
    raw_text: str = Field(min_length=1, max_length=300)    # "제품명 수량 가격"을 적은 그대로 — 읽은 항목과 같은 방식으로 나눈다
    source_id: str | None = None                          # 주면 그 견적(이미지)의 항목으로


class QuoteDraftPatchIn(BaseModel):
    expected_version: int
    items: list[QuoteDraftItemEdit] = Field(default_factory=list, max_length=50)
    selected_item_by_category: dict[str, str] | None = None


class QuotePriceExcludedOut(BaseModel):
    category: str
    item_id: str
    reason: str


class QuotePriceRowOut(BaseModel):
    category: str
    item_id: str
    quantity: int
    quote_unit_price: int | None = None
    quote_line_total: int | None = None
    quote_price_type: Literal["unit", "line_total", "unknown"] = "unknown"
    catalog_unit_price: int | None = None
    catalog_line_total: int | None = None
    catalog_checked_at: str | None = None
    catalog_status: Literal["available", "out_of_stock", "no_price", "unmatched"]
    diff_line_total: int | None = None


class QuoteDraftAnalysisOut(QuoteReviewOut):
    used_items: list[QuoteDraftItemOut] = Field(default_factory=list)   # 분석에 쓴 항목(분석 기준으로 고른 것)
    question: str | None = None
    draft_version: int
    price_excluded: list[QuotePriceExcludedOut] = Field(default_factory=list)   # 가격이 없어 합계에서 뺀 항목
    price_rows: list[QuotePriceRowOut] = Field(default_factory=list)            # 항목별 견적·카탈로그 가격(BE-08)


# BE-05 분석 전 제품 비교 · BE-06 교체 영향 미리보기
class QuoteCompareProductOut(BaseModel):
    product_id: str | None = None
    name: str
    image_url: str | None = None
    price: int | None = None
    price_delta: int | None = None
    perf_tier: float | int | None = None
    specs: list[dict[str, Any]] = Field(default_factory=list)
    compat_changes: list[dict[str, Any]] = Field(default_factory=list)
    incompatible: list[str] = Field(default_factory=list)
    additional_replacements: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] | None = None
    reason: str = ""


class QuoteDraftComparisonOut(BaseModel):
    category: str
    baseline_item_id: str
    recognized: list[dict[str, Any]] = Field(default_factory=list)
    recommended: list[QuoteCompareProductOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QuoteReplacementIn(BaseModel):
    category: str
    candidate_product_id: str


class QuoteReplacementsPreviewIn(BaseModel):
    replacements: list[QuoteReplacementIn] = Field(min_length=1, max_length=8)


class QuoteReplacementsApplyIn(QuoteReplacementsPreviewIn):
    expected_version: int


class QuoteReplacementPreviewOut(BaseModel):
    before_total: int
    after_total: int
    total_diff: int
    new_issues: list[dict[str, Any]] = Field(default_factory=list)
    resolved_issues: list[dict[str, Any]] = Field(default_factory=list)
    additional_replacements: list[dict[str, Any]] = Field(default_factory=list)
    replaced_items: list[dict[str, Any]] = Field(default_factory=list)
    price_excluded: list[QuotePriceExcludedOut] = Field(default_factory=list)


# ── 조건 대화 (§D-4-1) ──
class MessageOut(BaseModel):
    id: str
    role: str
    text: str
    created_at: str


class FieldOut(BaseModel):
    key: str
    label: str
    value: Any = None
    display: str | None = None
    status: str            # confirmed | assumed | missing
    editable: bool = True


class NextQuestionOut(BaseModel):
    id: str
    field: str
    text: str
    select: str             # single | multi | free
    options: list[dict] = Field(default_factory=list)


class BudgetWarningOut(BaseModel):
    """추천 전 예산 사전 경고 — 요구 성능의 최저가 합계(하한)가 예산과 어떻게 맞는지."""

    level: Literal["tight", "infeasible", "ok"]   # ok 는 예산 문제는 없고 message 만 있는 경우(요구를 채우는 후보 없음)
    message: str | None = None
    estimated_min: int
    budget: int


class ConditionState(BaseModel):
    list_id: str
    category: str | None = None
    mode: str | None = None
    revision_id: str | None = None
    lock_version: int | None = None
    messages: list[MessageOut] = Field(default_factory=list)
    fields: list[FieldOut] = Field(default_factory=list)
    next_question: NextQuestionOut | None = None
    can_recommend: bool = False
    accepts_spec_file: bool = False
    budget_warning: BudgetWarningOut | None = None   # 예산이 빠듯/불가능할 때만 채운다


class PreviousFieldOut(BaseModel):
    key: str
    label: str | None = None
    display: str


class PreviousConditionsOut(BaseModel):
    """GET /session/previous — 지난 목록에서 이어 쓸 조건(A1). 값은 resume 을 부를 때만 복사된다."""
    list_id: str
    name: str
    confirmed: bool
    last_active_at: str
    fields: list[PreviousFieldOut]
    summary: str


class PreferenceHintOut(BaseModel):
    """GET /session/previous — 반복 행동에서 추론한 선호 신호(B4, docs/사용자_선호비선호_기록_설계.md).
    자동 적용하지 않는다 — 사용자가 응답해야(POST .../preference-hint/{id}/respond) 조건에 반영된다."""
    id: str
    dimension: str
    slot: str
    value: str
    direction: str
    # "예"를 누르면 이번 목록 조건(brand_pref)에 실제로 담기는지 — 아니면 문구가 묻지 않고 알리기만 한다
    actionable: bool = False
    summary: str


class PreviousLookupOut(BaseModel):
    previous: PreviousConditionsOut | None = None
    preference_hint: PreferenceHintOut | None = None


class PreferenceHintRespondIn(BaseModel):
    accepted: bool


class ResumeIn(BaseModel):
    from_list_id: UUID


class PreviousComparisonOut(BaseModel):
    """GET /session/{id}/previous-comparison — 이전 견적과 비교(B1). available=False 면 reason 만 있다.
    reasons 는 {slot, label, kind(requirement|unexplained), claim, evidence[], source} — 문장(text)은 이것만 가지고 만든다."""
    available: bool
    reason: str | None = None
    text: str
    previous_list_id: str | None = None
    previous_label: str | None = None
    condition_changes: list[dict] = Field(default_factory=list)
    part_changes: list[dict] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    reasons: list[dict] = Field(default_factory=list)
    totals: dict | None = None
    caveats: list[str] = Field(default_factory=list)


# ── recommend / result (§D-4-2) ──
class RecommendIn(BaseModel):
    strategy: Optional[Literal["default", "alternative"]] = "default"


class RecommendAcceptedOut(BaseModel):
    """POST /recommend 의 202 응답 — 실행을 접수했을 뿐, 결과는 GET /result 로 폴링."""

    run_id: str
    status: str = "running"


class ProgressStepOut(BaseModel):
    step: str
    label: str
    status: str          # done | running | pending


class TextStatusOut(BaseModel):
    """LLM 등 비동기로 채워지는 문장 필드 공통 모양."""

    status: str           # pending | ready | failed
    text: str | None = None


class ExplanationOut(BaseModel):
    status: str            # pending | ready | failed
    headline: str | None = None
    text: str | None = None
    # 추천 당시 구성이 어느 축(가격·성능·밸런스·리뷰·호환여유)에서 점수를 얻었는지, 합 100(%). 교체 뒤에도 그대로다.
    contribution: dict[str, int] | None = None


class ProductOut(BaseModel):
    product_key: str
    variant_id: str | None = None
    name: str
    brand: str = ""
    spec_summary: str | None = None
    image_url: str | None = None
    purchase_url: str | None = None


class ReviewSignalRatioOut(BaseModel):
    ratio: float
    median: float | None = None          # 대조군(비슷한 부품) 중앙값 — 막대그래프 기준선용


class ReviewSignalBurst7Out(BaseModel):
    count: int
    ratio: float
    launch_week: bool
    median: float | None = None


class ReviewSignalCountRatioOut(BaseModel):
    count: int
    ratio: float
    baseline: float | None = None        # 데모 상품 전체의 2개+ 비율 — 이 지표는 중앙값이 아니라 기준선과 비교한다


class ReviewSignalSharedReviewersOut(BaseModel):
    count: int
    linked_products: int
    median_count: int | None = None
    median_linked_products: int | None = None


class ReviewSignalsOut(BaseModel):
    """관계·행동 축 관측값을 문장이 아니라 숫자로 — 프론트가 막대그래프를 그리는 데 쓴다
    (docs/개발요청_리뷰클렌징_요약_구조화.md 요청 A). 개별 신호를 못 채우면 그 키만 None.
    median·baseline 은 "비슷한 부품은 보통 얼마인가" — 값만 있으면 유저가 크고 작음을 판단할 수 없다."""

    rating5_share: ReviewSignalRatioOut | None = None
    burst7: ReviewSignalBurst7Out | None = None
    suspect_2plus: ReviewSignalCountRatioOut | None = None
    shared_reviewers: ReviewSignalSharedReviewersOut | None = None


class ReviewPlainOut(BaseModel):
    """관측을 유저가 읽을 문장으로 (docs/리뷰관측_문장_초안.md). 숫자는 signals 와 같은 산출물, 말은 템플릿.

    3층: headline(한 줄) → points(사기 전에 살펴볼 점 — 중앙값을 넘어 뽑힌 것만) → details(나머지 지표) +
    sources(산출물 원문 — GET /reviews/summary 의 summaries 와 같은 문장, 검토자용) + verify_url.
    reason 이 있으면 관측이 없는 경우 — headline 이 그 사유 한 줄이고 points·details·sources 는 비어 있다.
    """

    headline: str
    points: list[str] = []
    details: list[str] = []
    sources: list[str] = []
    verify_url: str | None = None
    reason: str | None = None            # below_threshold | out_of_period | no_match | unmapped | unavailable


class ReviewBriefOut(BaseModel):
    total_count: int | None = None       # 관측 산출물에 없는 상품은 모르는 값 — None (표시용 추정값을 넣지 않는다)
    # 정제 전/후 비교는 판정기가 없어 못 낸다(docs/decisions/0001) — 항상 null.
    excluded_ratio: float | None = None
    rating_refined: float | None = None
    signals: ReviewSignalsOut | None = None
    cleansing_summary: TextStatusOut | None = None
    plain: ReviewPlainOut | None = None


class RecommendationReviewOut(BaseModel):
    """추천 당시 snapshot. 별점/리뷰 총수 및 설명 생성 상태와 독립적이다."""

    status: Literal["ready", "unavailable", "failed"] = "unavailable"
    reason: str | None = "snapshot_missing"
    source_run_id: str | None = None
    product_id: str | None = None
    variant_id: str | None = None
    selection_source: Literal["automatic", "user_swap", "alternative"] = "automatic"
    applied_to_ranking: bool = False
    request_conditions: dict[str, Any] = Field(default_factory=dict)
    rank_weight: float | None = None
    rank_contribution: float | None = None
    rank_score: float | None = None
    detail: ReviewScoreDetailDTO | None = None


class ItemOut(BaseModel):
    item_id: str
    slot: str
    slot_label: str
    product: ProductOut
    price: int
    price_source: str = "synthetic"       # synthetic | observed
    price_observed_at: str | None = None
    qty: int = 1
    selected: bool = True
    budget_share: float | None = None
    review: ReviewBriefOut | None = None
    review_detail: RecommendationReviewOut = Field(default_factory=RecommendationReviewOut)
    original_review_detail: RecommendationReviewOut | None = None
    reason: TextStatusOut
    checks: TextStatusOut
    alternatives_count: int = 0


class TotalsOut(BaseModel):
    selected_price: int
    selected_units: int
    budget_remaining: int | None = None
    over_budget: bool = False


class VerificationIssueOut(BaseModel):
    axis: str
    severity: str            # minor | major
    text: str


class VerificationOut(BaseModel):
    status: str               # pending | ready | failed
    confidence: int | None = None
    issues: list[VerificationIssueOut] = Field(default_factory=list)


class ItemPatchIn(BaseModel):
    selected: Optional[bool] = None
    qty: Optional[int] = Field(default=None, ge=1, le=99)


class AlternativeOut(BaseModel):
    candidate_id: str
    label: str
    current: bool = False
    product: ProductOut
    price: int
    price_delta: int
    review: ReviewBriefOut | None = None
    review_detail: RecommendationReviewOut = Field(default_factory=RecommendationReviewOut)


class AlternativesOut(BaseModel):
    items: list[AlternativeOut] = Field(default_factory=list)


class PeripheralsRecommendIn(BaseModel):
    """개발요청 6번 — 주변기기 추천. PC 견적 대화(category 선택)를 거치지 않고 바로 호출한다."""

    kinds: list[Literal["monitor", "keyboard", "mouse", "speaker"]] = Field(min_length=1)
    budget_max: Optional[int] = Field(default=None, ge=0)
    purpose: Optional[str] = None
    priority: Optional[str] = None
    noise_sensitive: Optional[bool] = None
    resolution: Optional[str] = None
    # 주면 그 PC 견적의 해상도·GPU 스펙을 pc_context로 묶어 모니터 교차검사를 추가로 켠다
    # (principal 소유가 아니거나 못 찾으면 조용히 무시 — 독립 추천으로 그냥 진행한다).
    pc_list_id: Optional[str] = None


class PeripheralProductOut(BaseModel):
    name: str
    brand: str
    variant_id: str | None = None
    product_url: str | None = None
    image_url: str | None = None


class PeripheralRequirementRowOut(BaseModel):
    key: str
    label: str
    value: str


class PeripheralCheckOut(BaseModel):
    axis: str
    label: str
    state: str          # ok | unknown | fail
    detail: str


class PeripheralAlternativeOut(BaseModel):
    name: str
    price: int
    diff: int
    review: ReviewScoreDetailDTO | None = None
    review_weight: float = 0.0
    review_note: str = "리뷰 점수 미반영"


class PeripheralItemOut(BaseModel):
    kind: Literal["monitor", "keyboard", "mouse", "speaker"]
    kind_label: str
    product: PeripheralProductOut
    price: int
    price_source: str
    price_note: str
    requirement: list[PeripheralRequirementRowOut] = Field(default_factory=list)
    checks: list[PeripheralCheckOut] = Field(default_factory=list)
    reason: TextStatusOut
    alternatives: list[PeripheralAlternativeOut] = Field(default_factory=list)
    guide: TextStatusOut
    review: ReviewScoreDetailDTO | None = None
    review_weight: float = 0.0
    review_note: str


class PeripheralEmptyOut(BaseModel):
    kind: str
    reason: str


class PeripheralTotalsOut(BaseModel):
    reference_price: int
    note: str


class PeripheralsOut(BaseModel):
    status: Literal["ready", "empty", "skipped"]
    items: list[PeripheralItemOut] = Field(default_factory=list)
    empty: list[PeripheralEmptyOut] = Field(default_factory=list)
    totals: PeripheralTotalsOut


class SwapIn(BaseModel):
    candidate_id: str


class ResultMessageIn(BaseModel):
    text: str = Field(max_length=300)


class SpecFileIn(BaseModel):
    file_name: str
    content: str = Field(max_length=1_000_000)


class RecommendErrorOut(BaseModel):
    code: str
    message: str


class CompatCheckOut(BaseModel):
    """호환 검사 1건 — 무엇을 무엇과 비교했고 결과가 어땠는지(화면의 "호환성 점검 상세")."""
    axis: str                 # socket | memory | motherboard_case | gpu_len | cooler_height | cooler_socket | bios | power | psu_form | gpu_connector | budget
    label: str
    state: str                # ok | unknown(스펙을 몰라 확인 못 함) | fail(확정 비호환) | skipped(이번 견적에서 바뀌지 않는 부품이라 보지 않음)
    detail: str


class BudgetNoticeOut(BaseModel):
    """예산을 많이 남긴 이유 안내 — 우선순위(가성비·저소음·성능)와 상관없이 예산을 많이 남긴 새 구성에 채운다."""

    message: str
    budget: int
    spent: int
    remaining: int
    # 남은 예산으로 성능을 올리려면 다시 추천받을 우선순위. 이미 성능 우선이면 null(다시 추천받을 우선순위가 없다)
    suggest_priority: Literal["performance"] | None = "performance"


class RecommendResultOut(BaseModel):
    """저장된 추천 실행 결과의 공개 API 계약 (docs/frontend_외부수정요청.md §D-4-2)."""

    list_id: str
    revision_id: str | None = None
    lock_version: int | None = None
    run_id: str
    status: str                      # running | done | failed
    progress: list[ProgressStepOut] = Field(default_factory=list)
    category: str
    conditions_summary: str = ""
    budget_max: int | None = None
    items: list[ItemOut] = Field(default_factory=list)
    totals: TotalsOut | None = None
    verification: VerificationOut = Field(default_factory=lambda: VerificationOut(status="pending"))
    compat_checks: list[CompatCheckOut] = Field(default_factory=list)     # PC 호환 검사별 상세 (done 일 때만)
    explanation: ExplanationOut = Field(default_factory=lambda: ExplanationOut(status="pending"))
    budget_notice: BudgetNoticeOut | None = None       # 예산이 많이 남았고 그 이유가 우선순위일 때만 (done 일 때만)
    reasoning_log: list[dict] = Field(default_factory=list)
    data_notice: str = "상품·가격·리뷰는 합성 데이터입니다."
    # 04 리스트 확정 "메모" 초기값 — 조건·구성·직접 바꾼 것·확인 필요 사항을 코드가 정리한 문장 (done 일 때만)
    memo_suggestion: str = ""
    error: RecommendErrorOut | None = None


class ResultMessageOut(BaseModel):
    reply: str
    result: RecommendResultOut


# ── 사이드바 목록 · 확정(S5-a) · 리포트(S5-b) · 가격 알림 (§D-4-3) ──
class ReportSummaryOut(BaseModel):
    """목록 하나에 딸린 확정 견적서 하나(= 확정된 revision). revision_no 로 리포트·히스토리를 연다."""

    revision_no: int
    name: str
    confirmed_at: datetime
    total: int
    item_count: int            # 본체 부품 수만(개발요청 11번)
    peripheral_count: int = 0  # 주변기기 수(개발요청 11번)
    planned_purchase_at: str | None = None


class ListSummaryOut(BaseModel):
    list_id: str
    name: str
    category: Optional[str] = None
    stage: Literal["category", "conditions", "results", "report"]   # 현재 revision 기준(새 견적서 작성 중이면 그 단계)
    updated_at: datetime
    # 대화 목록(패널 "대화 내역")용 — 제목 대신 첫 사용자 말, 대화까지 포함한 마지막 활동, 조건 요약
    last_active_at: datetime | None = None
    first_message: str | None = None
    conditions_summary: str = ""
    # 가장 최근 확정 견적서 기준 — 목록에서 리포트를 따로 부르지 않아도 되게(개발요청 6번)
    total: int | None = None
    planned_purchase_at: str | None = None
    item_count: int | None = None
    reports: list[ReportSummaryOut] = Field(default_factory=list)


class ListsOut(BaseModel):
    items: list[ListSummaryOut] = Field(default_factory=list)


class ListRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ReportRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class NewRevisionIn(BaseModel):
    """개발요청 14번 — 안 주면(기본) 지금처럼 현재 견적서를 복사한다."""

    from_revision_no: Optional[int] = Field(default=None, ge=1)


class ConfirmPeripheralIn(BaseModel):
    """개발요청 11번 — 확정 시 같이 얼릴 주변기기 1건. 가격은 서버가 variant_id로 다시 조회해
    매긴다(클라이언트가 보낸 가격은 안 믿는다)."""

    kind: Literal["monitor", "keyboard", "mouse", "speaker"]
    variant_id: str
    qty: int = Field(default=1, ge=1, le=99)


class ConfirmIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    planned_purchase_at: Optional[str] = None
    target_amount: Optional[int] = Field(default=None, ge=0)
    memo: str = Field(default="", max_length=1000)
    peripherals: list[ConfirmPeripheralIn] = Field(default_factory=list)


class ReportProductOut(BaseModel):
    product_key: str
    name: str
    image_url: str | None = None
    purchase_url: str | None = None


class ReportItemOut(BaseModel):
    slot: str
    slot_label: str
    product: ReportProductOut
    price: int            # 단가 — 줄 금액은 price × qty
    qty: int = 1
    review: ReviewBriefOut | None = None
    review_detail: RecommendationReviewOut = Field(default_factory=RecommendationReviewOut)
    original_review_detail: RecommendationReviewOut | None = None
    evidence_text: str | None = None


class ReportPeripheralOut(BaseModel):
    """개발요청 11번 — 확정 견적서에 같이 얼린 주변기기 한 줄."""

    kind: Literal["monitor", "keyboard", "mouse", "speaker"]
    product: ReportProductOut
    price: int            # 단가 — 줄 금액은 price × qty, 참고가(reference_snapshot)
    qty: int = 1


class PriceWatchOut(BaseModel):
    enabled: bool
    target_amount: int | None = None
    status: Literal["waiting", "tracking", "reached"] = "waiting"
    latest_total: int | None = None
    observed_at: str | None = None


class ReportOut(BaseModel):
    list_id: str
    revision_no: int = 1
    name: str
    category: str
    owner_display_name: str
    planned_purchase_at: str | None = None
    target_amount: int | None = None
    memo: str = ""
    total: int             # 본체 + 주변기기 합계(개발요청 11번)
    confirmed_at: str
    items: list[ReportItemOut] = Field(default_factory=list)
    peripherals: list[ReportPeripheralOut] = Field(default_factory=list)
    price_watch: PriceWatchOut
    data_notice: str = "상품·가격·리뷰는 합성 데이터입니다."


class HistoryEventOut(BaseModel):
    at: str
    kind: str          # condition | request | recommend | swap | remove | confirm
    text: str          # 그 결과 — 알아들은 조건, 바뀐 부품("GPU A → B"), "바뀐 것 없음" …
    quote: str | None = None   # 그 결과를 만든 사용자 말


class HistoryStepOut(BaseModel):
    """이렇게 정해졌어요 — 결과를 바꾼 것만 한 단계씩(src/services/history_journey.py)."""

    kind: str          # start | change | swap | remove | unapplied | confirm
    text: str
    quote: str | None = None                                  # 그 단계를 만든 사용자 말
    changes: list[str] = Field(default_factory=list)          # 바뀐 부품(무엇 → 무엇, 가격 차이)
    notes: list[str] = Field(default_factory=list)            # 까닭·기본값·반영 못 한 것


class ListHistoryOut(BaseModel):
    """견적 리스트 히스토리 — 확정된 목록이 만들어진 여정. 단계·사건은 코드가, 요약 문장은 LLM(폴백 규칙)이."""

    summary: TextStatusOut
    steps: list[HistoryStepOut] = Field(default_factory=list)
    events: list[HistoryEventOut] = Field(default_factory=list)


class AlertIn(BaseModel):
    enabled: bool
    target_amount: Optional[int] = None


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
    axis_scores: dict[str, Any] = Field(default_factory=dict)
    telemetry: Optional[ReviewTelemetry] = None


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)
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
    """S5 리뷰 상세 — 프론트 계약(`docs/frontend_외부수정요청.md` §D-4-2 `ReviewSummary`) 의 이름을 따른다.

    **못 내는 값도 이름을 바꾸지 않고 null 로 둔다.** 전에는 이름을 달리 지었는데(`total_reviews`·
    `orig_rating`), 화면이 계약 이름을 읽으므로 실제로 낼 수 있는 리뷰 건수까지 **"리뷰 0건"** 으로
    나갔다. 없는 값을 0 으로 단정하는 것이 빈 칸보다 나쁘다.

    낼 수 없는 것과 이유:

    - `excluded_count` · `excluded_ratio` · `rating_refined` — 판정기가 없다(`docs/decisions/0001`).
      관계·행동 축은 상품 단위 신호라 **개별 리뷰를 하나도 빼지 않는다.** 몰림 15건을 `excluded_count`
      에 넣으면 화면이 "449건 중 15건 제외" 로 그려서 우리가 그 15건을 조작으로 판정하고 뺐다는
      말이 된다. 몰림은 출시·이벤트·인플루언서 언급·재입고로도 생긴다(몰림 2배 초과 상품 915개 중
      109개(11.9%)가 출시 첫 주였고, 그 밖의 설명은 이 데이터로 가릴 수 없다)
    - `distribution_refined` — "후" 가 없으므로 없다
    - `distribution_raw` — 산출물에 5점·1점 비율만 있고 4·3·2 가 없다. 부분만 내면 화면이 나머지를
      0% 로 그려서 없는 분포를 단정한다

    실측과 합성은 섞지 않는다 — 합성값은 `synthetic_demo` 안에만, `is_synthetic` 표지와 함께.

    P8: `excluded_count`·`excluded_ratio`·`rating_refined`·`distribution_refined`는
    더 이상 항상 null이 아니다 — evidence.review_aggregate에 검수 승인된 파일 기반
    분석(review_service._db_backed_analysis)이 있으면 실제 값을 낸다. 판정기가 없는
    관계·행동 축 관측 경로(PC 부품)는 그 분석이 없으므로 계속 null만 낸다 — 필드
    타입만 넓혔을 뿐 기존 PC 경로의 동작은 바뀌지 않는다.
    """
    product_key: str
    total_count: int = 0
    excluded_count: Optional[int] = None
    excluded_ratio: Optional[float] = None
    rating_raw: Optional[float] = None
    rating_refined: Optional[float] = None
    distribution_raw: dict[str, float] = {}
    distribution_refined: dict[str, float] = {}
    summaries: list[dict[str, Any]] = []
    data_notice: str
    analysis_version: Optional[str] = None
    status: str = "unavailable"          # unavailable | ready — DB 분석 유무
    # ── 계약 밖 추가 ──
    product_name: Optional[str] = None
    product_manipulation_risk: ProductRiskOut
    synthetic_demo: Optional[SyntheticDemoOut] = None


# ── 리뷰 검색 (GET /reviews/search) ──
class ReviewSearchHitOut(BaseModel):
    review_id: str
    body: str                                  # 리뷰 원문 전체 — 실제 리뷰는 중앙값 50자라 발췌하지 않는다
    posted_at: Optional[datetime] = None
    similarity: float                          # 질문과의 코사인 유사도. 정렬·하한에만 쓰고 추천 점수가 아니다


class ReviewSearchCoverageOut(BaseModel):
    reviews: int                               # 이 상품의 실제 리뷰 수(합성 제외)
    embedded: int                              # 그중 검색 준비(embedding)가 된 수 — reviews보다 작으면 일부만 검색했다


class ReviewSearchProductOut(BaseModel):
    product_id: str
    # ok: 관련 리뷰 있음 · no_match: 리뷰는 있으나 관련 리뷰 없음(평가가 나쁘다는 뜻이 아니다)
    # no_reviews: 실제 리뷰 없음 · not_indexed: 리뷰는 있으나 아직 embedding 전
    status: Literal["ok", "no_match", "no_reviews", "not_indexed"]
    coverage: ReviewSearchCoverageOut
    hits: list[ReviewSearchHitOut] = Field(default_factory=list)


class ReviewSearchOut(BaseModel):
    """상품별로 질문과 뜻이 가까운 실제 리뷰(src/services/review_search.py). products는 요청한 순서를 따른다."""
    query: str                                 # 정규화한 질문(NFKC·공백 정리)
    min_similarity: float                      # 이번 검색에 적용한 관련도 하한
    products: list[ReviewSearchProductOut]
