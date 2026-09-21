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

export interface CurrentPlan {
  id: string
  mode: PlanMode
  items: PlanItem[]
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
