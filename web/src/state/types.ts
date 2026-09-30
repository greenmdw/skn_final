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
  /** 서버 카탈로그의 제품 이미지 주소. 없으면 화면이 카테고리 아이콘을 보여 준다 */
  imageUrl?: string | null
  /** 판매처 링크(서버가 준 경우만) */
  purchaseUrl?: string | null
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
  /** 추천 전 예산 사전 경고 — 요구 성능의 최저가 합계가 예산에 빠듯하거나 못 미칠 때만 있다. */
  budgetWarning: BudgetWarning | null
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
  /** 이 줄의 합계 금액 = 단가 × 수량 */
  price: number
  /** 수량. 서버가 준 값. 없으면(예전에 저장된 구성 등) 화면에 표시하지 않는다 */
  qty?: number
  /** 개당 가격(서버가 준 단가) */
  unitPrice?: number
  /** 구매 시점(서버 값). 없으면 표시하지 않는다 */
  timing?: 'now' | 'soon' | 'later'
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

export interface BudgetWarning {
  level: 'tight' | 'infeasible' | 'ok'
  message: string
}

/** 예산을 많이 남긴 이유 안내(서버가 문장을 만든다). 성능 우선으로 다시 추천받는 길을 함께 안내한다. */
export interface BudgetNotice { message: string; remaining: number }

/** 추천 구성이 점수를 얻은 축별 비율(%, 합 100). 축 이름(가격·성능·밸런스·리뷰·호환여유)은 서버가 정한다. */
export interface ContributionShare { axis: string; percent: number }

export interface CurrentPlan {
  id: string
  mode: PlanMode
  items: PlanItem[]
  /** 예산이 많이 남은 이유와 성능 우선 재추천 안내. 서버 새 구성 추천에만 있다. */
  budgetNotice?: BudgetNotice
  /** 추천 당시 구성의 축별 기여도. 서버 추천에만 있다(부품을 바꿔도 추천 당시 값 그대로다). */
  contribution?: ContributionShare[]
  /** 세트 전체 호환 점검 결과. 서버 추천에만 있다 */
  compat?: CompatNotice
  /** 호환 검사별 상세. 서버 추천에만 있다 */
  compatChecks?: CompatCheck[]
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  checkSnapshot: CheckDraft | null
}

/** 채팅 선택지. questionId 가 있으면 서버 조건 질문의 선택지 — value 는 서버 내부 값이라 화면에는 label 만 보인다. */
// resumeFrom: 지난 목록 id — 누르면 그 목록의 조건을 이어 쓴다(A1). startFresh: 이어 쓰지 않고 새로 시작.
export interface ChatChoice { label: string; value: string; questionId?: string; resumeFrom?: string; startFresh?: boolean }

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
