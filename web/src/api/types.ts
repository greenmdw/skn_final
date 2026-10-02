import type { BudgetWarning, ChatChoice, CheckDraft, ConditionField, CurrentPlan, PartKey, PlanMode, ReviewRow, SavedSetup } from '../state/types'

// 화면이 백엔드에 기대하는 계약입니다. 실제 서버를 붙일 때는 이 인터페이스(Api)를 그대로 구현하면 됩니다.

export class ApiError extends Error {
  readonly code: string
  constructor(message: string, code = 'UNKNOWN') {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

/** 저장돼 있던 작업의 서버 세션을 찾을 수 없을 때(없어졌거나 내 것이 아님)의 오류 코드 */
export const SESSION_GONE = 'SESSION_GONE'

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback
}

// ---- 인증 ----
export interface LoginRequest { email: string; password: string; remember?: boolean }
export interface SignupRequest { name: string; email: string; password: string; marketingConsent: boolean }
export interface AuthUser { name: string; email: string }

// ---- 채팅 ----
/** 사용자의 메시지가 무엇에 대한 답변인지: 사용 목적 / 성능 목표 / 구성이 나온 뒤의 추가 질문 */
export type ChatTopic = 'intent' | 'performance' | 'followup'
export interface ChatReplyRequest {
  topic: ChatTopic
  text: string
  selectedPart: PartKey
  plan: CurrentPlan | null
}
export interface ChatReply {
  text: string
  choices?: ChatChoice[]
  /** 답하면서 구성이 바뀌었을 때(부품 교체 등) 바뀐 구성. 화면이 현재 구성을 이것으로 바꾼다 */
  plan?: CurrentPlan
}


// ---- 조건 대화(인터뷰) ----
// 새 PC를 만드는 인터뷰(용도·예산·우선순위 등)는 서버의 조건 세션(POST /session/{id}/message)이 처리한다.
// 서버는 조건 추출 에이전트(LLM, CONDITIONS_AGENT=1일 때)가 있으면 그걸로, 없으면 규칙 추출(slot_rules)로
// 자유 문장에서 예산·용도·우선순위 등을 뽑는다 — 화면은 결과(fields)만 반영하면 된다.
/** 지난 목록에서 이어 쓸 조건(GET /session/previous). summary는 서버가 규칙으로 만든 한 문장이다. */
export interface PreviousConditions {
  listId: string
  summary: string
}

export interface ConditionTurnResult {
  /** 세션이 없어서 새로 만들었으면 그 id. 이후 대화는 이 id로 이어간다. */
  sessionId: string
  /** 이번 턴에 대한 챗봇 답변(에이전트 문장 또는 다음 질문). */
  reply: string
  /** 지금까지 세션에 반영된 조건 전체(백엔드가 다시 계산해서 보낸 최신값). */
  fields: ConditionField[]
  /** 다음 질문이 객관식/다지선다면 그 선택지 — 없으면 자유 텍스트로 답해야 하는 질문이거나 더 물을 게 없다는 뜻. */
  choices?: ChatChoice[]
  /** 필수 조건을 다 채워서 지금 추천을 받을 수 있는지. */
  canRecommend: boolean
  /** 예산이 요구 성능의 최저가에 빠듯하거나 못 미칠 때의 사전 경고(추천을 막지는 않는다). */
  budgetWarning?: BudgetWarning | null
}

// ---- 추천 구성 ----
export interface RecommendRequest {
  mode: PlanMode
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  /** 인터뷰에서 이미 조건을 채워 둔 세션이 있으면 그 세션으로 그대로 추천한다(실서버 전용, 조건을 다시 만들지 않는다). */
  sessionId?: string | null
  checkSnapshot: CheckDraft | null
}

// ---- 대화 목록 · 견적서 (개발요청 10번) ----
/** 목록 하나에 딸린 확정 견적서 하나(서버 revision). 번호로 리포트·히스토리를 연다 */
/** itemCount 는 본체 부품 수, peripheralCount 는 확정할 때 같이 저장한 주변기기 수다. */
export interface ReportSummary { revisionNo: number; name: string; confirmedAt: string; total: number; itemCount: number; peripheralCount?: number }
/** 패널 "대화 내역"의 한 줄 — 서버 목록(list) 하나 */
export interface ConversationSummary {
  listId: string
  name: string
  stage: 'category' | 'conditions' | 'results' | 'report'
  lastActiveAt: string | null
  /** 첫 사용자 말(제목 대신) */
  firstMessage: string | null
  reports: ReportSummary[]
}
/** 서버에 저장된 대화 하나를 화면으로 되살릴 때 쓰는 값 */
export interface LoadedConversation {
  turn: ConditionTurnResult
  messages: { role: 'user' | 'bot'; text: string }[]
}

// ---- 견적 리스트 히스토리 ----
/** 대화 순서대로 "한 말 → 그 결과". quote 는 사용자 말(추천·버튼 교체·확정은 없음), text 는 그 결과 —
 * condition 은 알아들은 조건, request 는 바뀐 부품 또는 "바뀐 것 없음" */
export type HistoryEventKind = 'condition' | 'request' | 'recommend' | 'swap' | 'remove' | 'confirm'
export interface HistoryEvent { at: string; kind: HistoryEventKind; text: string; quote: string | null }
/** 이렇게 정해졌어요 — 결과를 바꾼 것만 한 단계씩. quote 는 그 단계를 만든 사용자 말, changes 는 바뀐 부품,
 * notes 는 까닭·말하지 않아 기본값으로 정해진 것·반영하지 못한 것 */
export type HistoryStepKind = 'start' | 'change' | 'swap' | 'remove' | 'unapplied' | 'confirm'
export interface HistoryStep { kind: HistoryStepKind; text: string; quote: string | null; changes: string[]; notes: string[] }
/** summary 는 서버가 단계 목록만 보고 쓴 요약(LLM, 실패하면 규칙 문장). 준비 전이면 null.
 * events 는 대화 순서 그대로의 사건 — "자세히"에서 보여 준다 */
export interface ListHistory { summary: string | null; steps: HistoryStep[]; events: HistoryEvent[] }

// ---- 부품 교체 ----
/** 한 부품 자리에 넣을 수 있는 대안 하나(서버 alternatives 응답). candidateId 를 swap 에 그대로 보낸다 */
export interface AlternativeOption {
  candidateId: string
  label: string
  current: boolean
  name: string
  brand: string
  specSummary: string | null
  imageUrl: string | null
  price: number
  /** 지금 고른 부품 대비 개당 가격 차이(+ 더 비쌈, - 더 쌈) */
  priceDelta: number
  rating: string
  reviews: string
}
/** qty 수량 · selected false 부품 빼기 / true 다시 넣기 */
export interface ItemPatch { qty?: number; selected?: boolean }

// ---- 내 PC·견적 점검 ----
export interface UpgradeSuggestion {
  /** 교체를 제안하는 부품 종류. 예: 'GPU' */
  part: string
  currentNote: string
  productName: string
  productNote: string
  performance: string
  extraCost: number
  power: string
  effectSummary: string
  checkConditions: string
  disclaimer: string
}

export interface QuoteConditions {
  purpose?: 'game' | 'creation' | 'office' | 'study' | 'other'
  resolution?: 'FHD_144' | 'QHD_165' | '4K'
  priority?: 'performance' | 'value' | 'quiet'
  games?: string[]
  budgetMax?: number
}

export interface QuoteReviewRequest {
  currentSpecs?: Record<string, string>
  text?: string
  imageDataUrl?: string
  conditions?: QuoteConditions
}

export interface QuoteCompatCheck {
  axis: string
  label: string
  state: 'ok' | 'fail' | 'unknown' | 'skipped'
  detail: string
}

export interface QuotePriceRow {
  part: string
  matched: string | null
  quoted: number | null
  catalog: number | null
  quantity: number
  diff: number | null
  diffPercent: number | null
  state: 'cheaper' | 'similar' | 'pricier' | 'no_quote_price' | 'no_catalog'
  detail: string
}

export interface QuoteBalanceRow {
  part: string
  aspect: string
  state: 'short' | 'excess' | 'ok' | 'unknown'
  detail: string
  measured: number | null
  target: number | null
}

export interface QuoteCompareRow {
  part: string
  quote: Record<string, unknown> | null
  ours: Record<string, unknown>
  sameProduct: boolean
  priceDiff: number | null
  priceDiffPercent: number | null
  priceState: 'cheaper' | 'similar' | 'pricier' | null
  tierDiff: number | null
  detail: string
}

export interface QuoteReviewResult {
  listId: string
  version: number
  input: { currentSpecs: Record<string, string>; conditions: Record<string, unknown>; inputHash: string }
  parts: ReviewRow[]
  compat: { checks: QuoteCompatCheck[]; summary: Record<string, number>; incompatible: string[] }
  prices: { available: boolean; reason: string | null; rows: QuotePriceRow[]; summary: Record<string, unknown> } | null
  balance: { available: boolean; reason: string | null; rows: QuoteBalanceRow[]; summary: Record<string, number>; notes: string[] } | null
  compare: { available: boolean; reason: string | null; rows: QuoteCompareRow[]; summary: Record<string, unknown>; notes: string[] } | null
  computedAt: string
}

export interface QuotePartCandidate {
  name: string
  price: number
  priceDelta: number | null
  perfTier: number | null
  specs: { key: string; label: string; unit: string; baseline: unknown; candidate: unknown; diff: number | null }[]
  incompatible: string[]
  compatChanges: { axis: string; label: string; from: string; to: string; detail: string }[]
  review: Record<string, unknown> | null
}

export interface QuotePartComparison {
  slot: string
  baseline: Record<string, unknown>
  candidates: QuotePartCandidate[]
  unmatchedTargets: string[]
  note: string | null
}

/** DB 미보유 부품 실시간 검색 결과(docs/미보유부품_실시간스펙검색_설계.md). relevant가 false거나
 * supportedFields가 전부 비어 있으면 "찾지 못했다"로 보여준다. */
export interface LiveSpecLookupResult {
  slot: string
  query: string
  relevant: boolean
  supportedFields: Record<string, unknown>
  sourceUrl: string | null
}

export interface QuoteChatMessage { id: string; role: 'user' | 'assistant' | 'system'; text: string; createdAt: string }
export interface QuoteApplyResult { listId: string; slots: string[]; missing: string[]; runId: string | null }

// ---- 저장한 구성 ----
export interface SetupsListResult {
  data: SavedSetup[]
  /** 일부 항목을 읽지 못했을 때 사용자에게 보여줄 안내. 없으면 빈 문자열 */
  warning: string
}

export interface Api {
  auth: {
    login(request: LoginRequest): Promise<AuthUser>
    signup(request: SignupRequest): Promise<AuthUser>
    /** 지금 로그인한 사용자. 로그인하지 않았으면 null */
    me(): Promise<AuthUser | null>
    logout(): Promise<void>
    /** 가입 화면의 이메일 중복 확인. 사용할 수 있으면 true */
    checkEmail(email: string): Promise<boolean>
  }
  chat: {
    reply(request: ChatReplyRequest): Promise<ChatReply>
  }
  conditions: {
    /** 인터뷰 자유 텍스트 한 턴. sessionId가 없으면 새 조건 세션을 만든다. */
    send(sessionId: string | null, text: string): Promise<ConditionTurnResult>
    /** 선택지(칩)를 눌렀을 때 — 서버 질문의 답으로 그대로 보낸다(자유 문장으로 내부 값을 보내지 않는다). */
    answer(sessionId: string, questionId: string, selected: string[]): Promise<ConditionTurnResult>
    /** 화면에서 직접 값을 바꿨을 때(예산 입력창 등) 세션에 반영한다. */
    patch(sessionId: string, field: string, value: unknown): Promise<ConditionTurnResult>
    /** 서버에 저장된 대화(메시지·조건)를 읽는다. 새로고침·지난 대화 열기에 쓴다. 없거나 내 것이 아니면 SESSION_GONE */
    load(sessionId: string): Promise<LoadedConversation>
    /** 저장돼 있던 조건 세션이 서버에 아직 있고 내 것인지. 없거나 내 것이 아니면 false (알 수 없으면 true) */
    exists(sessionId: string): Promise<boolean>
    /** 같은 사용자(계정·게스트 쿠키)의 지난 목록에서 이어 쓸 조건. 없으면 null — 값은 resume 전까지 복사되지 않는다. */
    previous(): Promise<PreviousConditions | null>
    /** 지난 목록의 조건을 이 세션에 복사한다. sessionId가 없으면 새 조건 세션을 만든다. */
    resume(sessionId: string | null, fromListId: string): Promise<ConditionTurnResult>
  }
  plans: {
    recommend(request: RecommendRequest): Promise<CurrentPlan>
    /** 목록의 저장된 추천 결과를 구성으로 읽는다(지난 대화 열기). 결과가 없으면 오류 */
    load(listId: string, base: Pick<CurrentPlan, 'mode' | 'budget' | 'conditions' | 'checkSnapshot'>): Promise<CurrentPlan>
    /** 이 브라우저에 남아 있던 구성을 서버의 최신 결과(수량·이미지·호환 검사 등)로 다시 읽는다. 읽지 못하면 오류 */
    refresh(plan: CurrentPlan): Promise<CurrentPlan>
    /** 이 부품 자리에 넣을 수 있는 대안 목록(지금 고른 것 포함) */
    alternatives(plan: CurrentPlan, itemId: string): Promise<AlternativeOption[]>
    /** 대안으로 교체하고 바뀐 구성(가격·호환 검사 다시 계산됨)을 돌려준다 */
    swap(plan: CurrentPlan, itemId: string, candidateId: string): Promise<CurrentPlan>
    /** 수량·구매 시점을 바꾸고 바뀐 구성을 돌려준다 */
    updateItem(plan: CurrentPlan, itemId: string, patch: ItemPatch): Promise<CurrentPlan>
  }
  checks: {
    suggestUpgrade(draft: CheckDraft): Promise<UpgradeSuggestion>
    /** 사양을 실제 카탈로그와 대조해 "확인된 PC 구성" 표 행으로 바꾼다. 세션·로그인 없이 부른다.
     * - currentSpecs: 슬롯 -> 이미 알고 있는 자유 문장(행 수정 등, 형식이 정해져 있을 때).
     * - text: 자유 형식 원문(업로드 파일 전체·붙여넣은 견적 설명). 서버가 슬롯별로 먼저 추출한다
     *   (LLM 추출 에이전트가 켜져 있으면 그걸로, 아니면 규칙 기반 파서로 — 형식이 안 맞으면 못 뽑을 수 있다).
     * - imageDataUrl: 견적·부품 목록이 찍힌 화면 캡처("data:image/png;base64,..." 등). text와 함께
     *   오면 이걸 우선한다. 서버에 이미지 인식(LLM)이 꺼져 있으면 에러로 알린다 — 규칙 기반 대안이
     *   없어서 조용히 빈 결과로 넘기지 않는다.
     * currentSpecs에 같은 슬롯이 있으면 그 값이 텍스트·이미지 추출값보다 우선한다. */
    previewOwnedParts(request: { currentSpecs?: Record<string, string>; text?: string; imageDataUrl?: string }): Promise<ReviewRow[]>
    createReview(request: QuoteReviewRequest): Promise<QuoteReviewResult>
    updateReview(listId: string, request: QuoteReviewRequest): Promise<QuoteReviewResult>
    getReview(listId: string): Promise<QuoteReviewResult>
    comparePart(listId: string, slot: string, direction?: 'cheaper' | 'better'): Promise<QuotePartComparison>
    /** "대응 안 됨" 부품 하나를 실시간 검색+검증한다 — 사용자가 버튼을 눌렀을 때만 부른다(자동 금지).
     * 캐시 히트면 비용 없이 바로 응답. 429면 너무 자주 눌렀다는 뜻. */
    liveLookupPart(listId: string, slot: string): Promise<LiveSpecLookupResult>
    sendMessage(listId: string, text: string): Promise<{ reply: string; evidence: string[]; via: 'agent' | 'rules' }>
    getMessages(listId: string): Promise<QuoteChatMessage[]>
    apply(listId: string, slots: string[]): Promise<QuoteApplyResult>
  }
  lists: {
    /** 이 사용자(계정 또는 게스트)의 목록 전체 — 최근 활동순 */
    list(): Promise<ConversationSummary[]>
    /** 대화(목록) 제목 바꾸기 */
    rename(listId: string, name: string): Promise<void>
    /** 견적서(확정본) 하나의 이름 바꾸기 — 대화 이름과 별개 */
    renameReport(listId: string, revisionNo: number, name: string): Promise<void>
    /** 견적서 하나만 삭제 — 대화와 다른 견적서는 그대로 */
    removeReport(listId: string, revisionNo: number): Promise<void>
  }
  setups: {
    /** 확정한 견적서가 있는 목록과 그 리포트. 이미 읽은 대화 목록(computer 만)을 주면 GET /lists 를 다시 부르지 않는다 */
    list(conversations?: ConversationSummary[]): Promise<SetupsListResult>
    /** 확정한 견적이 만들어진 여정(견적 리스트 히스토리). 로그인한 소유자의 확정 목록만. revisionNo 없으면 최근 견적서 */
    history(id: string, revisionNo?: number): Promise<ListHistory>
    /** 번호로 견적서 하나를 연다(같은 목록의 예전 견적서) */
    report(id: string, revisionNo: number): Promise<SavedSetup>
    /** 확정한 견적의 조건으로 새 견적서를 시작한다(fromRevisionNo 가 있으면 그 번호의 견적서에서, 없으면 가장 최근 견적서에서). 이후 조건 대화·추천은 같은 id 로 새 견적서에 쓴다 */
    newRevision(id: string, fromRevisionNo?: number): Promise<LoadedConversation>
    /** 같은 id가 있으면 갱신합니다. 저장된 구성을 돌려줍니다. */
    save(setup: SavedSetup): Promise<SavedSetup>
    remove(id: string): Promise<void>
  }
}
