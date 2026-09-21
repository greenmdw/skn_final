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

export interface PlanState {
  currentPlan: CurrentPlan | null
  budget: number | null
  stage: number
  mode: PlanMode
  intent: string
  performance: string
  quiet: string
  checkSnapshot: CheckDraft | null
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
