"""파이프라인 단계 입출력 DTO (pydantic v2).

경계를 넘는 값(단계 간 전달 / LLM JSON / HTTP / DB 행)은 전부 여기에 정의한다.
경계를 넘지 않는 순수 내부 값은 그냥 dataclass/tuple 로 둔다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["computer"]
Mode = Literal["build", "upgrade"]
Verdict = Literal["Pass", "Fail", "Pending"]
# E8 — 모니터/키보드/마우스/스피커. 독립 카테고리가 아니라 computer 요청의 부속 결과라
# Category에는 안 넣는다(config/peripherals.yaml이 config/categories/ 밖에 있는 이유와 같다).
PeripheralKind = Literal["monitor", "keyboard", "mouse", "speaker"]


# ── [1] 의도 분해 · 슬롯필링 ──────────────────────────────────────────────
class SlotFillResult(BaseModel):
    """LLM `fill_slots` tool 출력 스키마."""

    confirmed: dict[str, Any] = Field(default_factory=dict)
    assumed: dict[str, Any] = Field(default_factory=dict)
    assumed_reason: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class Slots(BaseModel):
    """확정 + 가정을 병합한 최종 조건 세트."""

    category: Category
    mode: Mode
    objective_text: str
    values: dict[str, Any] = Field(default_factory=dict)       # confirmed > assumed > defaults
    assumed_keys: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    def can_recommend(self, required_inputs: list[str]) -> bool:
        return not (set(required_inputs) & set(self.missing))


# ── [2] 요구사양 빌드 ────────────────────────────────────────────────────
class RequirementSpec(BaseModel):
    list_id: str
    category: Category
    mode: Mode
    targets: dict[str, dict[str, Any]] = Field(default_factory=dict)   # slot -> 제약 floor
    link_rules: list[str] = Field(default_factory=list)               # computer
    chain_warnings: list[str] = Field(default_factory=list)           # upgrade
    # 업그레이드에서 사용자가 그대로 쓰는 부품 — slot -> {name, specs, source(catalog|text|unverified)}.
    # 견적에는 안 넣고 호환성 검사(소켓·메모리·전력 …)에만 쓴다. 모르는 부품은 키가 없다.
    owned: dict[str, dict[str, Any]] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)              # total, alloc, feasibility
    flags: list[str] = Field(default_factory=list)
    unresolved: list[dict[str, str]] = Field(default_factory=list)
    # E7 — 인식된 게임 제목별 출처·승인 상태. 항목: {"key", "label", "status", "source"}.
    # status 는 provisional|approved, source 는 {url, excerpt, checked_at} 또는 None.
    games: list[dict[str, Any]] = Field(default_factory=list)
    # 2단계 파워 최소 용량 요구 산정의 기록 — {"estimated_power_w": {cpu, gpu, other}, "headroom_multiplier", "required_w"}.
    # 조합 여유 평가(build_margins)가 "무엇을 했는지"만 적는 데 쓴다. 판정에는 쓰지 않는다.
    power_sizing: dict[str, Any] = Field(default_factory=dict)


class ReviewRequirementAttribute(BaseModel):
    aspect_code: str
    context_code: str
    alpha: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    selection_reason: str
    preference_source: str = "default"
    selected_rule_id: str | None = None


class ReviewRequirementProfile(BaseModel):
    profile_version: str
    analysis_version: str
    part_type: str
    attributes: list[ReviewRequirementAttribute] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ReviewEvidenceMember(BaseModel):
    observation_id: str
    document_id: str
    source_code: str
    direction: Literal["positive", "negative", "mixed"]
    observation_text: str
    evidence_sentences: list[str] = Field(default_factory=list)


class ReviewAspectContribution(BaseModel):
    aspect_code: str
    context_code: str
    rule_id: str | None = None
    aggregate_id: str | None = None
    alpha: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    p: int = Field(default=0, ge=0)
    n: int = Field(default=0, ge=0)
    mixed: int = Field(default=0, ge=0)
    k: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    q: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    alpha_q: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence_state: Literal[
        "observed", "balanced", "mixed_only", "no_observations",
        "selected_rule_missing", "product_id_missing",
    ]
    neutral_reason: str | None = None
    members: list[ReviewEvidenceMember] = Field(default_factory=list)


class ReviewScoreDetail(BaseModel):
    profile: ReviewRequirementProfile
    value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    contributions: list[ReviewAspectContribution] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)


class FeelQuote(BaseModel):
    """체감 근거로 보여 줄 인용 문장 하나. `quote_id` 로 글 상세에서 그 문장 위치를 찾는다(작업지시서 W-3)."""

    quote_id: str
    post_id: str
    sentence: str
    is_example: bool = False
    photo_url: str | None = None


class FeelAttributeDetail(BaseModel):
    """체감 적합도(R)에 들어간 속성 하나. 성향 축이면 good/bad 는 요청자가 고른 쪽과 같은/다른 쪽 표의 수다."""

    code: str
    label: str
    type: Literal["rating", "taste"]
    alpha: float
    value: float
    state: Literal["same_condition", "other_condition", "external_only", "no_evidence"]
    same_good: int = 0
    same_bad: int = 0
    rest_good: int = 0
    rest_bad: int = 0
    external_p: int | None = None
    external_n: int | None = None
    external_score: float | None = None
    split: bool = False          # 의견(또는 쪽)이 갈린다
    mismatch: bool = False       # 성향이 한쪽으로 모였는데 요청자가 고른 쪽과 다르다
    situational: int = 0         # 상황에 따라 다르다고 해서 표로 세지 않은 작성자 수
    quotes: list[FeelQuote] = Field(default_factory=list)    # 이 평가를 뒷받침하는 문장(같은 조건 먼저, 최근 순)
    side_counts: dict[str, int] = Field(default_factory=dict)   # 성향 축이면 쪽별 작성자 수, 평가 속성이면 good/bad 수


class FeelDetail(BaseModel):
    """체감 적합도 R(개발_확정사양.md 6장). 사용기 근거가 없으면 외부 리뷰 출발값만으로 계산한 값이다."""

    value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    attributes: list[FeelAttributeDetail] = Field(default_factory=list)
    basis: Literal["community", "example", "external_only"] = "external_only"
    recent_authors: int = 0      # 최근 N개월 안에 이 제품의 사용기를 쓴 작성자 수(0 이면 표시하지 않는다)


# ── [3-0]~[3-B] 후보 ────────────────────────────────────────────────────
class Candidate(BaseModel):
    product_key: str
    slot: str
    name: str
    variant_id: str | None = None
    product_id: str | None = None
    offer_observation_id: str | None = None
    brand: str = ""
    price: int = 0
    # RAM 2개 구성(정책 §2.5): price 는 구성 전체 가격, unit_price 는 상품 1개 가격, purchase_qty 는 상품 개수.
    purchase_qty: int = 1
    unit_price: int | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    # E5 — 카탈로그 출처(어느 URL·언제 확인한 값인가). specs 에는 섞지 않는다 — 섞으면
    # 스펙 키를 세는 로직(빈 스펙 카운트 등)이 메타데이터 키를 스펙으로 셀 수 있다.
    # {"spec_url", "checked_at"(ISO 날짜 문자열), "by_key": {엔진 spec 키: 그 값을 뒷받침하는 URL}}.
    # by_key 는 테이블에 전용 출처 컬럼이 있는 키만 담는다(예: gpu.dimension_source_url → length_mm/
    # height_mm/slot_thickness) — 확실하지 않은 키는 넣지 않고 evidence 생성 쪽에서 spec_url로 대체한다.
    provenance: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict = "Pass"
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    score: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    score_notes: list[str] = Field(default_factory=list)   # 점수 계산 중 남긴 표식(예: neutral:성능)
    review_detail: ReviewScoreDetail | None = None
    feel_detail: FeelDetail | None = None     # 주변기기 체감 적합도(R). 순위의 "리뷰" 축 값이 된다
    rank: int = 0
    # E8/E9 — 가격 출처. PC 후보는 기존대로 offer_observation 기반 "observed"(기본값,
    # 동작 불변). 주변기기 로더(E9)는 peripheral_price_snapshot만 있어 "reference_snapshot"을
    # 쓴다 — 판매처·관측일을 모르는 참고가라는 뜻이고, PC 총액에 합산하지 않는다(계획 §3.3, R-3).
    # "synthetic"은 예비값(현재 생성자 없음).
    price_source: Literal["observed", "synthetic", "reference_snapshot"] = "observed"
    price_observed_at: str | None = None   # ISO 날짜/시각 문자열. observed가 아니면 보통 None


class HardFilterResult(BaseModel):
    slots: dict[str, list[Candidate]] = Field(default_factory=dict)          # Pass만 (보완 뒤 재판정 포함)
    held: dict[str, list[Candidate]] = Field(default_factory=dict)           # 보완 뒤에도 Pending인 후보(평가 제외)
    # slot -> pool/pass/fail/pending 개수 + pending_reasons({사유: 개수}) / fail_reasons({사유 접두어: 개수})
    stats: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # 보완 시도 기록: slot, product_key, missing_keys, source, status(filled/not_found/no_path/failed), detail
    enrichment: list[dict[str, Any]] = Field(default_factory=list)


class RankResult(BaseModel):
    slots: dict[str, dict[str, Any]] = Field(default_factory=dict)           # slot -> ideal_tier/ranked/bottleneck_hint
    weights_used: dict[str, float] = Field(default_factory=dict)
    weight_adjustments: list[str] = Field(default_factory=list)


# ── [4] 세트 최적화 / 예산 배분 ─────────────────────────────────────────
class BuildItem(BaseModel):
    slot: str
    product_key: str
    name: str
    variant_id: str | None = None
    offer_observation_id: str | None = None
    price: int   # 구성 전체 가격(= unit_price × qty, 키트는 가격 그대로). 합계·예산 계산에 쓴다
    qty: int = 1
    unit_price: int | None = None
    perf_tier: float = 0.0
    score: float = 0.0
    rank_from_3b: int = 1


class BuildResult(BaseModel):
    list_id: str
    items: list[BuildItem] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    link_check: dict[str, str] = Field(default_factory=dict)
    balance: dict[str, Any] = Field(default_factory=dict)
    alternatives: dict[str, int] = Field(default_factory=dict)
    round: int = 1
    # 정상 추천 가능 여부 — 신뢰도와 별개다. {"status": "recommendable"|"not_recommendable", "reasons": [{"code", "axes", "missing"?}]}
    eligibility: dict[str, Any] = Field(default_factory=lambda: {"status": "recommendable", "reasons": []})
    # 조합의 전력·냉각·크기 여유 기록(engine/build_margins.evaluate_margins) — 점수·적격성과 무관한 기록. 계산 전이면 빈 dict.
    margins: dict[str, Any] = Field(default_factory=dict)


class BasketLine(BaseModel):
    category: str
    sub_item: str
    product_key: str
    name: str
    price: int
    qty: int = 1
    score: float = 0.0


class BasketResult(BaseModel):
    list_id: str
    buy_now: list[BasketLine] = Field(default_factory=list)
    buy_later: list[BasketLine] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    adjustments: list[str] = Field(default_factory=list)


# ── [3-C] 적대적 검증 ───────────────────────────────────────────────────
class Issue(BaseModel):
    axis: str
    text: str = ""          # 사용자에게 보이는 중립 서술. 판정(judge)과 분리한다
    prosecutor: str = ""    # 미사용 — 디베이트 제거 이전 설계 (기획서 §10-12)
    defender: str = ""      # 〃
    tool_result: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    judge: str = ""
    penalty: int = 0


class VerificationTarget(BaseModel):
    subject: str
    confidence: int = 0
    passed: bool = False
    rounds: int = 1
    issues: list[Issue] = Field(default_factory=list)
    gray_axes: list[str] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    # 적격 여부 — passed 는 신뢰도 기준 AND eligible 이다. blocking: 탈락 사유 [{"code", "axis"?, "missing"?}]
    eligible: bool = True
    blocking: list[dict[str, Any]] = Field(default_factory=list)


class VerificationResult(BaseModel):
    list_id: str
    category: Category
    mode: Literal["set", "per_item"]
    targets: list[VerificationTarget] = Field(default_factory=list)


# ── 주변기기(모니터·키보드·마우스·스피커) — 계획 §3.3 E8~E13 ────────────────
class PeripheralRequirement(BaseModel):
    """[2] 종류별 요구사양(E10). PC의 RequirementSpec.targets에 대응하는 주변기기 버전."""

    kind: PeripheralKind
    hard: dict[str, Any] = Field(default_factory=dict)     # 탈락 가능 조건(예: 모니터 해상도 등급)
    soft: dict[str, Any] = Field(default_factory=dict)     # 랭킹에만 쓰는 선호(예: 패널 종류)
    filters: list[dict[str, Any]] = Field(default_factory=list)   # 사용자가 직접 말해서 거르는 조건({key, op, value})
    assumed: list[str] = Field(default_factory=list)       # 조건 없이 기본값을 썼다고 표시할 키
    notes: list[str] = Field(default_factory=list)         # 화면 안내용 보조 문구(잠정값 등)


class PeripheralPick(BaseModel):
    """[3-A]~[4] 종류별 1위 후보(E11). peripheral_payload의 items[] 항목 하나에 대응."""

    kind: PeripheralKind
    candidate: Candidate
    score: float = 0.0
    verdict: Verdict = "Pass"
    checks: list[dict[str, Any]] = Field(default_factory=list)        # peripheral_payload().items[].checks
    alternatives: list[Candidate] = Field(default_factory=list)       # 차순위 후보(payload 가공 시 상위 2개만 노출)


class PeripheralResult(BaseModel):
    """run_peripherals()의 전체 출력(E11~E13). peripheral_payload()가 이 값을 공개 계약 모양 dict로 가공한다."""

    # "ready" = 하나 이상 pick / "empty" = 요청은 있었지만 조건에 맞는 후보가 0건(C6, 조용히 완화하지 않음)
    # / "skipped" = peripherals 조건이 아예 없어 이 단계를 돌리지 않음(기존 PC 결과 불변 원칙)
    status: Literal["ready", "empty", "skipped"] = "skipped"
    picks: list[PeripheralPick] = Field(default_factory=list)
    empty: list[dict[str, str]] = Field(default_factory=list)     # [{"kind", "reason"}] — peripheral_payload().empty
    counts: dict[str, Any] = Field(default_factory=dict)          # 종류별 pool/pass/fail/pending, 조합 탐색 절단 여부
    budget: dict[str, Any] | None = None                          # peripheral_budget_max 적용 시 조합 탐색 결과(합계 등)
    # E11 — [3-C] 품목별 검증 결과(mode="per_item"). status가 "ready"일 때만 채워진다.
    verification: VerificationResult | None = None
    # E13 — [2]가 낸 품목별 요구사양([2] build_requirements 결과). status가 "ready"일 때만
    # picks에 있는 종류만큼 채워진다. peripheral_payload()가 requirement/reason을 만드는 재료다
    # — payload가 [1]의 원본 조건(values)을 다시 안 받아도 되게 여기 실어 둔다.
    requirements: dict[str, PeripheralRequirement] = Field(default_factory=dict)
    # 종류 → 체감 근거 블록(peripheral_evidence.build_feel_block). 보여 줄 근거가 없는 종류는 키가 없다.
    feel: dict[str, Any] = Field(default_factory=dict)


# ── [5] 설명 생성 ───────────────────────────────────────────────────────
class ExplanationDraftItem(BaseModel):
    slot: str
    reason: str


class ExplanationDraft(BaseModel):
    """[5] LLM 구조화 출력 (기획서 §11-3).

    수치·부품명·통과여부는 코드가 확정해 입력으로 주므로 LLM 은 서술만 낸다 —
    그래서 Explanation 과 달리 list_id·contribution·basis·evidence 를 갖지 않는다.
    """

    headline: str = ""
    summary: str = ""          # 구성이 사용자 조건에 어떻게 맞는지·어디서 타협했는지 2~3문장 (03 요약)
    items: list[ExplanationDraftItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ExplanationItem(BaseModel):
    slot: str
    reason: str
    basis: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Explanation(BaseModel):
    list_id: str
    headline: str = ""
    summary: str = ""          # 03 화면 "추천 요약" 본문. 슬롯별 reason 은 items 에, 여기엔 반복하지 않는다
    contribution: dict[str, int] = Field(default_factory=dict)   # 축(가격·성능·리뷰) -> %, 합 100
    items: list[ExplanationItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    review_line_by_slot: dict[str, str] = Field(default_factory=dict)
    # 문장 출처 — 운영 로그에서 LLM 문장이 쓰였는지, 규칙 템플릿으로 내려갔는지(왜) 가리는 데 쓴다. 화면에는 나가지 않는다.
    text_source: str = "rule"                                    # "llm" | "rule"
    fallback_reason: str = ""                                    # 규칙으로 내려간 까닭: 예외 클래스명 또는 "check_rejected"
    rule_reason_slots: list[str] = Field(default_factory=list)   # LLM 초안을 쓰고도 이유가 규칙 문장인 슬롯


# (구 추천 결과 DTO는 §D-4-2 계약(RecommendResultOut, src/schemas.py)으로 대체되어 제거됨.
#  서비스 계층은 이제 dict를 직접 만들어 schemas.RecommendResultOut 경계를 통과시킨다.)


# ── 전체 결과 ───────────────────────────────────────────────────────────
class PipelineResult(BaseModel):
    scenario: str
    category: Category
    input_text: str
    slots: Optional[Slots] = None
    requirement: Optional[RequirementSpec] = None
    hard_filter: Optional[HardFilterResult] = None
    rank: Optional[RankResult] = None
    review_requirement_profiles: dict[str, ReviewRequirementProfile] = Field(default_factory=dict)
    build: Optional[BuildResult] = None
    basket: Optional[BasketResult] = None
    verification: Optional[VerificationResult] = None
    explanation: Optional[Explanation] = None
    # E11 — 주변기기 결과(계획 §3.3). peripherals 조건이 있을 때만 채워진다(없으면 None
    # 그대로 — 컴퓨터 결과에는 영향 없음, "기존 결과 불변 원칙" §4).
    peripherals: Optional[PeripheralResult] = None
    logs: list[str] = Field(default_factory=list)
