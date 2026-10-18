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
export interface AuthUser { name: string; email: string; /** 마케팅 수신 동의 */ marketingConsent?: boolean; /** 가입 시각(ISO) */ createdAt?: string }

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

/** 반복 행동에서 추론한 선호 신호(GET /session/previous). 사용자가 응답해야 이번 견적에 반영된다. */
export interface PreferenceHint {
  id: string
  dimension: string
  slot: string
  value: string
  direction: string
  /** true 면 "예"가 이번 견적 조건에 실제로 담긴다. false 면 묻지 않고 알려 주기만 한다 */
  actionable: boolean
  summary: string
}

export interface PreviousLookup {
  previous: PreviousConditions | null
  preferenceHint: PreferenceHint | null
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
  /** 어느 화면의 대화인가 — 주변기기 대화는 주변기기 화면으로 연다 */
  chat: 'computer' | 'peripheral'
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

// ---- 받은 견적 점검 ----
export interface QuoteConditions {
  purpose?: 'game' | 'creation' | 'office' | 'study' | 'other'
  resolution?: 'FHD_144' | 'QHD_165' | '4K'
  priority?: 'performance' | 'value' | 'quiet'
  games?: string[]
  budgetMax?: number
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

/** DB 미보유 부품 실시간 검색 결과(docs/미보유부품_실시간스펙검색_설계.md). relevant가 false거나
 * supportedFields가 전부 비어 있으면 "찾지 못했다"로 보여준다. */
export interface LiveSpecLookupResult {
  slot: string
  query: string
  relevant: boolean
  supportedFields: Record<string, unknown>
  sourceUrl: string | null
  /** 이 값을 확인(검색)한 시각 — ISO. 저장소에서 가져온 값이면 그때의 시각이다 */
  fetchedAt: string | null
  /** unreviewed 미검토 · confirmed 사람이 확인함 · rejected 틀린 값(서버가 못 찾음으로 돌려준다) */
  reviewStatus: 'unreviewed' | 'confirmed' | 'rejected'
  /** 참고가(원). 서버가 켜져 있고 만료 전일 때만 있다 — 합계·가격 비교와 무관한 참고 표시용 */
  referencePrice: number | null
  referencePriceAt: string | null
}

export interface QuoteApplyResult { listId: string; slots: string[]; missing: string[]; runId: string | null }

// ---- 받은 견적 점검: 여러 장 업로드 초안(백엔드 /pc/review-drafts) ----
export interface QuoteCapabilities {
  imageExtraction: boolean
  supportedTypes: string[]
  maxFiles: number
  maxFileBytes: number
  maxTotalBytes: number
  textMaxChars: number
}

export interface QuoteDraftSource {
  id: string
  type: 'image' | 'text' | 'replacement' | 'manual'
  fileName: string | null
  sortOrder: number
  status: 'completed' | 'failed'
  errorCode: string | null
  qualityWarning: string | null     // 사진이 작거나 흐릴 때의 안내
  ignoredLines: string[]            // 튜닝·액세서리라 분석에서 뺀 줄
}

export type QuoteMatchStatus = 'confirmed' | 'ambiguous' | 'candidate' | 'inferred' | 'unmatched'

export interface QuoteDraftItem {
  id: string
  category: string
  rawText: string
  /** 상품코드·가격이 빠진 제품명 */
  name: string
  productCode: string | null
  quantity: number
  unitPrice: number | null
  /** 수량이 반영된 품목 합계. 견적에 금액이 없으면 null */
  lineTotal: number | null
  priceType: 'unit' | 'line_total' | 'unknown'
  matchedProductId: string | null
  matchedProductKey: string | null
  matchedName: string | null
  imageUrl: string | null
  matchStatus: QuoteMatchStatus
  candidateCount: number | null
  sourceIds: string[]
  selectedForAnalysis: boolean
  userEdited: boolean
  /** 'model' = 제조사·시리즈를 줄여 쓴 글을 모델 번호로 찾아 확정했다(제조사 확인을 권한다) */
  matchVia?: 'model' | null
  /** 실시간 검색 값이 저장소에 있어 점검에 쓰인다. 제품 확정이 아니다 */
  liveValue?: boolean
}

export interface QuoteDraft {
  draftId: string
  version: number
  sources: QuoteDraftSource[]
  items: QuoteDraftItem[]
  selectedItemByCategory: Record<string, string>
  conditions: Record<string, unknown>
  question: string | null
  partialSuccess: boolean
  groups: { id: string; name: string; sourceIds: string[]; itemIds: string[] }[]
  /** 올린 사진이 서로 다른 견적처럼 보이면 'separate' — 화면의 기본 선택일 뿐이다 */
  sourceModeHint: 'single' | 'separate'
  createdAt: string
}

export interface QuoteDraftCreateRequest {
  images: File[]
  text?: string
  question?: string
  conditions?: QuoteConditions
}

export interface QuoteDraftItemEdit {
  id: string
  delete?: boolean
  name?: string
  quantity?: number
  /** null 이면 금액을 지운다 */
  lineTotal?: number | null
}

export interface QuoteDraftPriceRow {
  category: string
  itemId: string
  quantity: number
  quoteUnitPrice: number | null
  quoteLineTotal: number | null
  quotePriceType: 'unit' | 'line_total' | 'unknown'
  catalogUnitPrice: number | null
  catalogLineTotal: number | null
  catalogCheckedAt: string | null
  catalogStatus: 'available' | 'out_of_stock' | 'no_price' | 'unmatched'
  diffLineTotal: number | null
}

export interface QuoteBalanceRequirement {
  label: string
  purpose: string | null
  resolution: string | null
}

export interface QuoteDraftAnalysis extends QuoteReviewResult {
  usedItems: QuoteDraftItem[]
  question: string | null
  draftVersion: number
  priceExcluded: { category: string; itemId: string; reason: string }[]
  priceRows: QuoteDraftPriceRow[]
  /** 용도 대비 균형 기준 라벨(예: "게임 · QHD 165Hz"). 용도를 입력하지 않았으면 null */
  requirementLabel: string | null
}

export interface QuoteRecognizedOption {
  itemId: string
  productId: string | null
  name: string
  imageUrl: string | null
  quantity: number
  quoteLineTotal: number | null
  matchStatus: QuoteMatchStatus
  specs: { key: string; label: string; unit: string; candidate: unknown }[]
}

export interface QuoteRecommendedOption {
  productId: string
  name: string
  imageUrl: string | null
  price: number | null
  priceDelta: number | null
  specs: { key: string; label: string; unit: string; baseline: unknown; candidate: unknown; diff: number | null }[]
  compatChanges: { axis: string; label: string; from: string; to: string; detail: string }[]
  incompatible: string[]
  additionalReplacements: { category: string; axis: string; reason: string }[]
  reason: string
}

export interface QuoteDraftComparison {
  category: string
  baselineItemId: string
  recognized: QuoteRecognizedOption[]
  recommended: QuoteRecommendedOption[]
  notes: string[]
}

export interface QuoteReplacementPreview {
  beforeTotal: number
  afterTotal: number
  totalDiff: number
  newIssues: { axis: string; label: string; detail: string }[]
  resolvedIssues: { axis: string; label: string; detail: string }[]
  additionalReplacements: { category: string; axis: string; reason: string }[]
  priceExcluded: { category: string; itemId: string; reason: string }[]
}

export interface QuoteComparisonProduct {
  productId: string | null
  productKey: string | null
  name: string | null
  imageUrl: string | null
  quantity: number
  lineTotal: number | null
}

export interface QuoteSavedComparison {
  comparisonId: string
  receivedTotal: number
  savedTotal: number
  totalDiff: number
  comparableCategories: string[]
  excludedReceivedCategories: string[]
  rows: { category: string; sameProduct: boolean; received: QuoteComparisonProduct | null; saved: QuoteComparisonProduct | null; priceDiff: number | null }[]
  briefSummary: { changedCount: number; largestPriceDifferenceCategory: string | null; text: string }
  savedName: string
  /** 'draft_quotes' = 올린 두 견적끼리 비교(저장 견적 비교가 아님) */
  kind: string | null
  labels: { received: string; saved: string }
  /** 서로 다른 두 견적의 기준별 값. 기준마다 따로 보여 주고 종합 우열은 없다 */
  criteria: QuoteCriterion[]
  computedAt: string
}

export interface QuoteCriterion {
  key: string
  label: string
  aText: string
  bText: string
  /** 어느 쪽 값이 더 좋은가('a'·'b'·같음 'tie'·확인 못 해 비교 안 함 null) — 기준마다 따로다 */
  better: 'a' | 'b' | 'tie' | null
  higherIsBetter: boolean
  /** true 면 우열이 없는 참고 줄(예: 카탈로그로 확정된 부품 수) */
  info: boolean
}

/** 서버가 조립한 질문 답변 자료. 알 수 없는 형식은 화면에서 버린다(서버 값만 그대로 그린다). */
export type QuoteVisual =
  | { type: 'product_comparison'; category: string | null; title: string; items: { side: string; productId: string | null; name: string; imageUrl: string | null; price: number | null }[] }
  | { type: 'table'; category: string | null; title: string; columns: string[]; rows: unknown[][] }
  | { type: 'compatibility_check'; title: string; items: { side: string; axis: string; label: string; state: string; detail: string }[] }

export interface QuoteGuideRef { id: string; slot: string; kind: 'care' | 'install'; text: string; score: number | null }

export interface QuoteDraftChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
  createdAt: string
  comparisonId: string | null
  answerId: string | null
  guideRefs: QuoteGuideRef[]
  visuals: QuoteVisual[]
  displayTarget: 'saved_comparison_explanation' | 'chat' | null
  duplicateOf: string | null
  via: 'agent' | 'rules' | null
}

export interface QuoteDraftChatReply {
  messageId: string | null
  answerId: string | null
  reply: string
  guideRefs: QuoteGuideRef[]
  visuals: QuoteVisual[]
  displayTarget: 'saved_comparison_explanation' | 'chat'
  duplicateOf: string | null
  via: 'agent' | 'rules'
  createdAt: string | null
}

// ---- 주변기기 추천(백엔드 POST /session/{id}/peripherals/recommend) ----
export type PeripheralKind = 'monitor' | 'keyboard' | 'mouse' | 'speaker'

/** 서버(POST /peripherals/interpret)가 한 문장을 정해진 목록의 값으로 읽은 결과. 이어서 말하면 이 값에 더해진다. */
export interface PeripheralInterpretation {
  kinds: PeripheralKind[]
  /** 목적 코드(예: 게임용). 이름은 resolved[종류].purposes 의 label 로 보인다 */
  purposes: string[]
  /** 목적 → 그 목적을 말할 때의 종류. 없는 목적은 모든 종류에 적용된다(서버가 정하고 화면은 그대로 돌려보낸다) */
  purposeKinds: Partial<Record<string, PeripheralKind[]>>
  /** 상황 코드(예: trending) */
  situations: string[]
  /** 직접 말해서 거르는 스펙 조건(종류 → 조건 이름) */
  stated: Partial<Record<PeripheralKind, string[]>>
  handSize: 'small' | 'medium' | 'large' | null
  /** 종류별 예산 상한(원) */
  budget: Partial<Record<PeripheralKind, number>>
  /** 종류별 최소 가격(원) — "6만원 이상"처럼 말했을 때. 서버가 아직 안 주면 비어 있다 */
  budgetMin: Partial<Record<PeripheralKind, number>>
  /** 여러 종류를 합친 예산(원) */
  budgetTotal: number | null
  /** 강조한 축(종류 → 가격·리뷰·무상AS·브랜드·스펙 기준 이름). 선호 브랜드를 말하면 "브랜드"가 저절로 붙는다 */
  emphasis: Partial<Record<PeripheralKind, string[]>>
  /** 선호 브랜드(종류 → 브랜드 이름) */
  brandLike: Partial<Record<PeripheralKind, string[]>>
  /** 빼 달라고 한 브랜드(종류 → 브랜드 이름). 후보에서 빠진다 */
  brandAvoid: Partial<Record<PeripheralKind, string[]>>
  /** 뺄 제품(종류 → 제품 이름). 채팅의 "다른 걸로"가 그때의 1위를 넣는다 */
  exclude: Partial<Record<PeripheralKind, string[]>>
  /** 서버가 목록에서 찾지 못해 반영하지 못한 말 */
  unrecognized: string[]
}

export interface PeripheralResolvedCondition { condition: string; label: string; sources: string[] }

/** 함께 고를 수 없는 두 조건이 둘 다 말해졌을 때 서버가 어떻게 정리했는지. kept 가 null 이면 둘 다 뺐다(다시 물어야 한다) */
export interface PeripheralConflict { conditions: string[]; labels: string[]; kept: string | null }

/** 한 종류에 대한 풀이. preferences 는 순위만 바꾸는 선호, filters 는 직접 말해서 거르는 조건이다 */
export interface PeripheralResolvedKind {
  kind: PeripheralKind
  label: string
  purposes: { code: string; label: string }[]
  preferences: PeripheralResolvedCondition[]
  filters: PeripheralResolvedCondition[]
  conflicts: PeripheralConflict[]
}

export interface PeripheralInterpretRequest {
  text: string
  /** 직전 응답의 interpretation. 주면 이어서 말한 것으로 더해 읽는다 */
  previous?: PeripheralInterpretation | null
  /** 종류 카드로 고른 값. 같은 문장을 이 값과 함께 다시 보낸다 */
  kinds?: PeripheralKind[]
}

export interface PeripheralInterpretResult {
  interpretation: PeripheralInterpretation
  /** 종류 → 풀이 */
  resolved: Partial<Record<PeripheralKind, PeripheralResolvedKind>>
  /** true 면 "어떤 기기를 찾으세요?" 카드를 띄운다 */
  needsKind: boolean
  /** llm | rules — 규칙으로 읽었어도 오류가 아니다 */
  source: 'llm' | 'rules'
  /** 문장이 길어 앞부분만 읽었다 */
  truncated: boolean
}

export interface PeripheralRecommendRequest {
  kinds: PeripheralKind[]
  /** 여러 종류를 합친 예산(interpretation.budgetTotal) */
  budgetMax?: number
  /** 아래 값은 interpretation 의 같은 이름 필드를 그대로 싣는다 */
  purposes?: string[]
  purposeKinds?: Partial<Record<string, PeripheralKind[]>>
  situations?: string[]
  stated?: Partial<Record<PeripheralKind, string[]>>
  kindBudget?: Partial<Record<PeripheralKind, number>>
  /** 종류별 최소 가격(원). interpretation.budgetMin */
  kindBudgetMin?: Partial<Record<PeripheralKind, number>>
  emphasis?: Partial<Record<PeripheralKind, string[]>>
  brandLike?: Partial<Record<PeripheralKind, string[]>>
  brandAvoid?: Partial<Record<PeripheralKind, string[]>>
  exclude?: Partial<Record<PeripheralKind, string[]>>
  handSize?: 'small' | 'medium' | 'large' | null
  /** 주면 그 PC 견적의 해상도로 모니터 교차검사를 켠다(내 것이 아니면 서버가 조용히 무시) */
  pcListId?: string
}

/** 채팅 한 턴(POST /session/{id}/peripherals/chat)의 서버 답. 화면은 reply 를 그대로 보여 준다 */
export interface PeripheralTurn {
  /** 이번 문장에서 새로 반영한 것(앞 턴 것은 없다) */
  newConditions: { kind: string; label: string }[]
  /** 반영하지 못한 말과 이유 */
  notReflected: string[]
  /** 어떻게 읽었는지·함께 고를 수 없어 정리한 조건 */
  notes: string[]
  /** 질문이면 답 */
  answer: { type: string; topic: string | null; text: string; kinds: PeripheralKind[]; chips: string[] } | null
  /** 결과 화면 명령(reset · remove · swap · cheaper · relative_budget). 명령이 아니면 null */
  command: string | null
  /** 이번 문장으로 뺀 것. 있으면 받은 interpretation 으로 추천을 다시 받는다 */
  removedConditions: { kind: string; label: string }[]
  /** true 면 조건을 모두 지웠다 — 결과를 지우고 첫 화면으로 돌아간다 */
  reset: boolean
  /** 위를 순서대로 이은 채팅 답장 */
  reply: string
  /** 이번 답 뒤에 보여 줄 질문 칩 */
  chips: string[]
  /** 추천 결과가 나온 뒤에 보여 줄 질문 칩 */
  resultChips: string[]
}

export interface PeripheralChatRequest extends PeripheralInterpretRequest {
  /** 추천을 받은 세션. 없으면 서버에 빈 세션을 만든다 */
  sessionId?: string | null
  /** 묶은 PC 견적(내 PC와 맞는지 묻는 질문에 쓴다) */
  pcListId?: string
}

export interface PeripheralChatResult extends PeripheralInterpretResult {
  sessionId: string
  turn: PeripheralTurn
}

/** 저장된 주변기기 채팅(GET /session/{id}/peripherals/messages) — 돌아왔을 때 채팅과 마지막 조건을 되살린다 */
export interface PeripheralHistory {
  messages: { role: 'user' | 'assistant'; text: string; at: string }[]
  interpretation: PeripheralInterpretation
  resolved: Partial<Record<PeripheralKind, PeripheralResolvedKind>>
  /** 마지막으로 추천을 받은 상태였다 — 같은 조건으로 추천을 다시 받는다(추천 결과는 저장하지 않는다) */
  showingResults: boolean
  /** 마지막 추천 때 채팅에 말한 유의사항 */
  notices: string[]
}

/** 한 평가 기준(타건감·연결 안정성 등)에 모인 후기 관측 집계 */
export interface PeripheralReviewAspect {
  aspectCode: string
  /** observed 관측 있음 · balanced 긍정·부정 비슷 · no_observations 관측 없음 등 서버 판정 */
  state: string
  positive: number
  negative: number
  mixed: number
  /** 대표 관측 문장(서버가 후기에서 뽑은 것) */
  quote: string | null
  /** 대표 문장의 방향. 서버가 다수 의견 쪽 문장을 고른다. 서버가 안 주면 null */
  quoteDirection?: 'positive' | 'negative' | 'mixed' | null
  /** 적은 쪽 의견도 적지 않다(갈리는 점) */
  dissent?: boolean
}

/** 점수 축 하나(서버가 사용자말 이름 label 을 준다). value 는 0~1, weight 는 비중 */
export interface PeripheralScoreAxis { axis: string; label: string; value: number; weight: number; points: number }
/** 카드에 한 줄로 보이는 필수 스펙 하나 */
export interface PeripheralKeySpec { key: string; label: string; value: string }
/** 사용자가 말한 조건을 스펙 값으로 확인한 결과("무게 76g · 80g 이하") */
export interface PeripheralSpecCheck { key: string; text: string; ok: boolean }
/** 사용자가 말한 항목 하나와 그 근거 연결. feelCodes 는 체감 속성 코드, externalAspects 는 외부 리뷰 항목 코드 */
export interface PeripheralRequested {
  label: string
  /** pc_purpose: 말하지 않았고 묶은 PC 견적의 용도에서만 온 목적 */
  source: 'stated' | 'situation' | 'purpose' | 'pc_purpose'
  /** spec: 스펙 값으로 판정 · evidence: 사용기·외부 리뷰로 판단 */
  type: 'spec' | 'evidence'
  specChecks: PeripheralSpecCheck[]
  feelCodes: string[]
  externalAspects: string[]
}
/** 통과한 후보 안에서 싼 순서(rank 번째, 총 of 개) */
export interface PeripheralPricePosition { rank: number; of: number }

export interface PeripheralAlternative {
  name: string
  price: number
  diff: number
  reviewAspects: PeripheralReviewAspect[]
  reviewNote: string
  /** 아래 네 값은 서버가 대안에도 제품 정보를 줄 때만 있다 */
  variantId?: string | null
  brand?: string | null
  imageUrl?: string | null
  productUrl?: string | null
  /** 이 대안을 큰 카드로 올렸을 때 1위와 같은 정보량을 보이기 위한 값. 서버가 안 주면 비어 있다 */
  keySpecs: PeripheralKeySpec[]
  requested: PeripheralRequested[]
  pricePosition: PeripheralPricePosition | null
  scoreAxes: PeripheralScoreAxis[]
  feel: PeripheralFeel | null
}

export interface PeripheralItem {
  kind: PeripheralKind
  kindLabel: string
  name: string
  brand: string
  /** 확정할 때 서버에 보내는 제품 식별자 */
  variantId: string | null
  productUrl: string | null
  imageUrl: string | null
  price: number
  /** 가격 출처 문구(예: 판매처·관측일 미확인 참고가) */
  priceNote: string
  requirement: { key: string; label: string; value: string }[]
  checks: { axis: string; label: string; state: 'ok' | 'unknown' | 'fail'; detail: string }[]
  reason: { status: string; text: string | null }
  guide: { status: string; text: string | null }
  reviewAspects: PeripheralReviewAspect[]
  reviewWeight: number
  reviewNote: string
  /** 다른 선택지. 서버가 제품 식별자(variantId)를 주는 경우에만 견적에 담을 수 있다(없으면 선택 버튼은 꺼져 있다) */
  alternatives: PeripheralAlternative[]
  /** 체감 근거(사용기 분석). null 이면 보여 줄 근거가 없고 feelNote 만 보인다 */
  feel: PeripheralFeel | null
  feelNote: string | null
  /** 필수 스펙 한 줄(값이 없는 항목은 서버가 뺀다) */
  keySpecs: PeripheralKeySpec[]
  /** 사용자가 말한 항목별 근거 연결. 말한 것이 없으면 비어 있다 */
  requested: PeripheralRequested[]
  pricePosition: PeripheralPricePosition | null
  /** 점수 축(사용자말 이름 포함) */
  scoreAxes: PeripheralScoreAxis[]
}

/** 체감 근거에 인용한 사용기 문장 하나. postId 로 커뮤니티 글을 연다 */
export interface PeripheralFeelQuote {
  quoteId: string
  postId: string
  sentence: string
  isExample: boolean
  /** 없으면 사진을 보여 주지 않는다 */
  photoUrl: string | null
}

export interface PeripheralFeelAttribute {
  code: string
  label: string
  /** 그대로 보여 줄 문구(예: "손이 큰 사용자 5명 중 4명이 좋게 평가했습니다") */
  text: string
  state: string
  split: boolean
  mismatch: boolean
  quotes: PeripheralFeelQuote[]
  /** 이 항목에 좋게·아쉽게 평가한 사용기 작성자 수(같은 조건 + 그 밖). 서버가 안 주면 없다 */
  good?: number
  bad?: number
}

export interface PeripheralFeel {
  /** 순위에 반영된 체감 적합도(0~1). 숫자로 보여 주지 않고 문구를 쓴다 */
  value: number
  basis: 'community' | 'example' | 'external_only'
  /** "예시 글 기준"·"외부 리뷰 기준" 같은 근거 이름 */
  basisText: string
  /** 최근 3개월 사용기 작성자 수. null 이면 표시하지 않는다 */
  recentAuthors: number | null
  attributes: PeripheralFeelAttribute[]
}

/** "더 맞추기" 칩. 누르면 add 를 추천 입력에 더해 추천만 다시 부른다 */
export interface PeripheralAdjustChip {
  kind: PeripheralKind
  id: string
  label: string
  add: { purposes?: string[]; situations?: string[]; stated?: Partial<Record<PeripheralKind, string[]>> }
  /** 눌렀을 때 순서가 바뀌는 자리 수 */
  moved: number
}

export interface PeripheralsResult {
  sessionId: string
  status: 'ready' | 'empty' | 'skipped'
  items: PeripheralItem[]
  empty: { kind: string; reason: string }[]
  referencePrice: number
  priceNote: string
  /** 목록에 없어 반영하지 않은 이름. 오류가 아니라 안내다 */
  ignoredInputs: string[]
  adjustChips: PeripheralAdjustChip[]
  /** 채팅으로 알릴 유의사항(예: PC 견적 없이 고른 모니터). 추천은 그대로이고 주의할 점만 말한다 */
  notices: { kind: string; code: string; text: string }[]
}

// ---- 제품 리뷰 요약(GET /reviews/summary/{product_key}) ----
/** 실제로 모은 리뷰에서 나온 값만 담는다. 서버의 합성 데모 블록은 실사용자에게 보이면 안 되는 값이라 읽지 않는다. */
export interface ReviewSummary {
  productKey: string
  productName: string | null
  /** 모은 리뷰 수. 서버가 모르면 0 */
  totalCount: number
  ratingRaw: number | null
  /** 검수 승인된 분석이 있을 때만 값이 있다 */
  ratingRefined: number | null
  excludedCount: number | null
  excludedRatio: number | null
  /** 상품 단위로 관측된 사실 문장들(점수가 아니다) */
  riskEvidence: string[]
  /** 항목별로 좋다·아쉽다고 말한 리뷰 수("냉각 성능 — 좋다는 리뷰 7건 · 아쉽다는 리뷰 0건"). 리뷰 본문이 아니다 */
  aspectFacts: string[]
  /** ready 면 분석이 있다, unavailable 이면 서버가 이 제품의 분석을 아직 갖고 있지 않다 */
  status: 'ready' | 'unavailable'
  dataNotice: string
}

// ---- 이전 견적과 비교(GET /session/{id}/previous-comparison) ----
export interface PreviousComparisonChange { key: string; label: string; before: string; after: string }
export interface PreviousComparisonPart {
  slot: string
  label: string
  /** 이전 견적의 제품 이름. 이전에 없던 부품이면 null */
  before: string | null
  /** 이번 견적의 제품 이름. 이번에 없는 부품이면 null */
  after: string | null
  beforePrice: number | null
  afterPrice: number | null
  /** 줄 금액(단가×수량) 차이. 이번 − 이전 */
  priceDiff: number
}
/** 바뀐 부품 하나의 이유. requirement 는 요구 사양이 달라져서, unexplained 는 요구가 그대로라 원인을 짐작하지 않은 것 */
export interface PreviousComparisonReason { slot: string; label: string; kind: 'requirement' | 'unexplained'; claim: string; evidence: string[] }

export type PreviousComparison =
  | { available: false; reason: string }
  | {
    available: true
    /** 비교한 이전 견적을 가리키는 말(예: 10월 6일) */
    previousLabel: string
    previousListId: string | null
    /** 서버가 규칙으로 만든 요약 문장 */
    text: string
    conditionChanges: PreviousComparisonChange[]
    partChanges: PreviousComparisonPart[]
    /** 그대로인 부품 이름 */
    unchanged: string[]
    reasons: PreviousComparisonReason[]
    totals: { before: number; after: number; diff: number }
  }

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
    /** 이름·마케팅 수신 동의를 바꾼다(주면 그 값만). 바뀐 사용자 정보를 돌려준다 */
    updateProfile(request: { name?: string; marketingConsent?: boolean }): Promise<AuthUser>
    /** 비밀번호를 바꾼다. 현재 비밀번호가 틀리면 invalid_password */
    changePassword(request: { currentPassword: string; newPassword: string }): Promise<void>
    /** 회원 탈퇴. 비밀번호가 맞아야 하고, 되돌릴 수 없다 */
    withdraw(password: string): Promise<void>
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
    previous(): Promise<PreviousLookup>
    /** 선호 되묻기에 답한다. 세션이 없으면 새 조건 세션을 만들어 거기에 반영하고 그 id 를 돌려준다. */
    respondPreferenceHint(sessionId: string | null, signalId: string, accepted: boolean): Promise<{ sessionId: string }>
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
    /** 이번 추천을 이전 견적(이어서 하기로 가져온 목록, 없으면 가장 최근 추천)과 견준다. 비교할 수 없으면 available=false 와 이유 */
    previousComparison(listId: string): Promise<PreviousComparison>
  }
  reviews: {
    /** 제품 하나의 리뷰 요약. 서버에 요약이 없는 제품이면 NOT_FOUND */
    summary(productKey: string): Promise<ReviewSummary>
  }
  checks: {
    /** 저장된 받은 견적 점검 결과(분석)를 읽는다. 분석 전이면 오류 */
    getReview(listId: string): Promise<QuoteReviewResult>
    /** 점검한 부품으로 새 추천 세션을 만든다(장바구니로 넘기기 전 단계). */
    apply(listId: string, slots: string[]): Promise<QuoteApplyResult>
  }
  peripherals: {
    /** 주변기기(모니터·키보드·마우스·스피커)를 추천받는다. sessionId 가 없으면 서버에 빈 세션을 만들어 쓴다. */
    recommend(request: PeripheralRecommendRequest, sessionId?: string | null): Promise<PeripheralsResult>
    /** 문장 한 줄을 정해진 목록의 값으로 읽는다(로그인 불필요, 주소별 분당 20회) */
    interpret(request: PeripheralInterpretRequest): Promise<PeripheralInterpretResult>
    /** 채팅 한 턴: 문장 해석 + 질문 답변 + 서버가 만든 답장. sessionId 가 없으면 서버에 빈 세션을 만들어 쓴다 */
    chat(request: PeripheralChatRequest): Promise<PeripheralChatResult>
    /** 이 세션(목록)에 저장된 주변기기 채팅. 내 것이 아니거나 없는 세션이면 NOT_FOUND */
    history(sessionId: string): Promise<PeripheralHistory>
  }
  quoteDrafts: {
    /** 서버가 받을 수 있는 업로드 한도·이미지 인식 가능 여부. 화면 진입 때 확인한다 */
    capabilities(): Promise<QuoteCapabilities>
    /** 이미지(여러 장)·텍스트로 초안을 만든다. 같은 제품만 합쳐지고 서로 다른 제품은 모두 남는다 */
    create(request: QuoteDraftCreateRequest): Promise<QuoteDraft>
    get(draftId: string): Promise<QuoteDraft>
    /** 여러 항목 수정·분석 기준 선택을 한 번에 저장한다. 버전이 다르면 STALE_REVIEW_VERSION */
    patchItems(draftId: string, expectedVersion: number, items: QuoteDraftItemEdit[], selectedItemByCategory?: Record<string, string>): Promise<QuoteDraft>
    /** 분석 기준으로 고른 항목만 분석한다(저장된 점검 결과가 만들어진다) */
    analyze(draftId: string, sourceIds?: string[]): Promise<QuoteDraftAnalysis>
    /** 올린 서로 다른 두 견적을 비교한다(저장 견적 비교와 같은 모양) */
    compareQuotes(draftId: string, aSourceIds: string[], bSourceIds: string[]): Promise<QuoteSavedComparison>
    compareCategory(draftId: string, category: string, baselineItemId?: string): Promise<QuoteDraftComparison>
    previewReplacements(draftId: string, replacements: { category: string; candidateProductId: string }[]): Promise<QuoteReplacementPreview>
    applyReplacements(draftId: string, expectedVersion: number, replacements: { category: string; candidateProductId: string }[]): Promise<QuoteDraft>
    /** 카탈로그에 없는 항목을 실시간 검색한다(사용자가 눌렀을 때만) */
    liveLookupItem(draftId: string, itemId: string): Promise<LiveSpecLookupResult>
    /** 분석 결과와 저장 견적을 비교한다(로그인 필요) */
    compareSaved(listId: string, savedListId: string, savedRevisionNo?: number): Promise<QuoteSavedComparison>
    getSavedComparison(listId: string, comparisonId: string): Promise<QuoteSavedComparison>
    sendChat(listId: string, text: string, options?: { clientMessageId?: string; comparisonId?: string }): Promise<QuoteDraftChatReply>
    chatHistory(listId: string): Promise<QuoteDraftChatMessage[]>
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
