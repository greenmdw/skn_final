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


# ── [3-0]~[3-B] 후보 ────────────────────────────────────────────────────
class Candidate(BaseModel):
    product_key: str
    slot: str
    name: str
    variant_id: str | None = None
    offer_observation_id: str | None = None
    brand: str = ""
    price: int = 0
    specs: dict[str, Any] = Field(default_factory=dict)
    # E5 — 카탈로그 출처(어느 URL·언제 확인한 값인가). specs 에는 섞지 않는다 — 섞으면
    # [3-B] data_gap 감점(빈 스펙 카운트)이 메타데이터 키를 스펙으로 셀 수 있다.
    # {"spec_url", "checked_at"(ISO 날짜 문자열), "by_key": {엔진 spec 키: 그 값을 뒷받침하는 URL}}.
    # by_key 는 테이블에 전용 출처 컬럼이 있는 키만 담는다(예: gpu.dimension_source_url → length_mm/
    # height_mm/slot_thickness) — 확실하지 않은 키는 넣지 않고 evidence 생성 쪽에서 spec_url로 대체한다.
    provenance: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict = "Pass"
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    score: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    rank: int = 0
    # E8/E9 — 가격 출처. PC 후보는 기존대로 offer_observation 기반 "observed"(기본값,
    # 동작 불변). 주변기기 로더(E9)는 peripheral_price_snapshot만 있어 "reference_snapshot"을
    # 쓴다 — 판매처·관측일을 모르는 참고가라는 뜻이고, PC 총액에 합산하지 않는다(계획 §3.3, R-3).
    # "synthetic"은 예비값(현재 생성자 없음).
    price_source: Literal["observed", "synthetic", "reference_snapshot"] = "observed"
    price_observed_at: str | None = None   # ISO 날짜/시각 문자열. observed가 아니면 보통 None


class HardFilterResult(BaseModel):
    slots: dict[str, list[Candidate]] = Field(default_factory=dict)          # Pass + 승격 Pending
    stats: dict[str, dict[str, int]] = Field(default_factory=dict)           # slot -> pool/pass/fail/pending


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
    price: int
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


class BasketLine(BaseModel):
    category: str
    sub_item: str
    product_key: str
    name: str
    price: int
    qty: int = 1
    score: float = 0.0
    timing: str = "now"


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
    contribution: dict[str, int] = Field(default_factory=dict)   # 축(가격·성능·밸런스·리뷰·호환여유) -> %, 합 100
    items: list[ExplanationItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    review_line_by_slot: dict[str, str] = Field(default_factory=dict)


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
    build: Optional[BuildResult] = None
    basket: Optional[BasketResult] = None
    verification: Optional[VerificationResult] = None
    explanation: Optional[Explanation] = None
    # E11 — 주변기기 결과(계획 §3.3). peripherals 조건이 있을 때만 채워진다(없으면 None
    # 그대로 — 컴퓨터 결과에는 영향 없음, "기존 결과 불변 원칙" §4).
    peripherals: Optional[PeripheralResult] = None
    logs: list[str] = Field(default_factory=list)
