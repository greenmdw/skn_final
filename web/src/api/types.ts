import type { ChatChoice, CheckDraft, CurrentPlan, PartKey, PlanMode, SavedSetup } from '../state/types'

// 화면이 백엔드에 기대하는 계약입니다. 실제 서버를 붙일 때는 이 인터페이스(Api)를 그대로 구현하면 됩니다.

export class ApiError extends Error {
  readonly code: string
  constructor(message: string, code = 'UNKNOWN') {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback
}

// ---- 인증 ----
export interface LoginRequest { email: string; password: string }
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

export interface ReviewChatRequest {
  /** config: 확인된 PC 구성 수정 채팅, answer: 업그레이드 답변에 대한 추가 질문 */
  topic: 'config' | 'answer'
  text: string
}
export interface ReviewChatReply { text: string }

// ---- 추천 구성 ----
export interface RecommendRequest {
  mode: PlanMode
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  checkSnapshot: CheckDraft | null
}

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
  }
  chat: {
    reply(request: ChatReplyRequest): Promise<ChatReply>
    reviewReply(request: ReviewChatRequest): Promise<ReviewChatReply>
  }
  plans: {
    recommend(request: RecommendRequest): Promise<CurrentPlan>
  }
  checks: {
    suggestUpgrade(draft: CheckDraft): Promise<UpgradeSuggestion>
  }
  setups: {
    list(): Promise<SetupsListResult>
    /** 같은 id가 있으면 갱신합니다. 저장된 구성을 돌려줍니다. */
    save(setup: SavedSetup): Promise<SavedSetup>
    remove(id: string): Promise<void>
  }
}
