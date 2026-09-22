// 백엔드 추천이 내는 8개 슬롯(cpu·gpu·ram·board·ssd·psu·case·cooler)과 목업에만 있던 monitor.
export type PartKey = 'cpu' | 'gpu' | 'ram' | 'ssd' | 'monitor' | 'board' | 'psu' | 'case' | 'cooler'

export interface Part {
  type: string
  name: string
  price: string
  meta: string
  source: string
  action: string
  actionClass: '' | 'track' | 'later'
  score: string
  fit: string
  reasonTitle: string
  tags: string[]
  /** 구매 전 확인 문장들(서버가 준 것). 목업·확정 리포트 항목에는 없다 */
  checks?: string[]
  rating: string
  reviews: string
  label: string
}

export type PlanMode = 'new' | 'upgrade'

/** 조건 세션(백엔드)이 대화 한 턴마다 돌려주는 필드 하나 — 에이전트/규칙이 자유 텍스트에서 뽑은 값. */
export interface ConditionField {
  key: string
  label: string
  value: unknown
  display: string | null
  status: 'confirmed' | 'assumed' | 'missing'
}

export interface PlanState {
  currentPlan: CurrentPlan | null
  budget: number | null
  stage: number
  mode: PlanMode
  intent: string
  performance: string
  quiet: string
  checkSnapshot: CheckDraft | null
  /** 실서버 조건 대화 세션 id(list_id). 인터뷰 중에만 쓰고, 목업 모드에서는 항상 null. */
  sessionId: string | null
  /** 지금까지 세션에 반영된 조건들(백엔드 fields) — 화면(GoalPanel)에 그대로 보여준다. */
  fields: ConditionField[]
  /** 백엔드가 판단한 "지금 추천 가능" 여부. 목업 모드에서는 쓰지 않는다. */
  canRecommend: boolean
  selectedPart: PartKey
  deskUnlocked: boolean
  deskWidth: number
  deskDepth: number
  deskHeight: number
}

export interface ChatMessage {
  id: string
  role: 'bot' | 'user'
  text: string
  choices?: ChatChoice[]
}

export interface SavedSetup {
  id: string
  title: string
  date: string
  target: number
  memo: string
  savedAt: string
  plan: CurrentPlan
  desk: DeskState
  checkDraft: CheckDraft
}

export interface DeskState {
  deskUnlocked: boolean
  deskWidth: number
  deskDepth: number
  deskHeight: number
}

export interface PlanItem extends Omit<Part, 'price'> {
  id: string
  key: PartKey | null
  price: number
}

export interface CompatCheck {
  axis: string
  label: string
  /** ok 통과 · unknown 스펙을 몰라 확인 못 함 · fail 확정된 비호환 · skipped 이번 견적에서 바뀌지 않는 부품이라 보지 않음 */
  state: 'ok' | 'unknown' | 'fail' | 'skipped'
  detail: string
}

export interface CompatNotice {
  /** 확정된 호환 문제(소켓·전력·크기·예산) */
  problems: string[]
  /** 스펙을 몰라 정밀 검사를 못 한 항목 */
  unchecked: string[]
}

export interface CurrentPlan {
  id: string
  mode: PlanMode
  items: PlanItem[]
  /** 세트 전체 호환 점검 결과. 서버 추천에만 있다 */
  compat?: CompatNotice
  /** 호환 검사별 상세. 서버 추천에만 있다 */
  compatChecks?: CompatCheck[]
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  checkSnapshot: CheckDraft | null
}

export interface ChatChoice { label: string; value: string }

export interface ReviewRow {
  part: string
  original: string
  originalNote: string
  matched: string
  matchedNote: string
  state: 'ok' | 'warn'
  stateLabel: string
}

export interface CheckDraft {
  question: string
  budget: string
  rows: ReviewRow[]
}
