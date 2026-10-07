import type { PeripheralKind, ReportSummary } from '../api/types'
// 백엔드 추천이 내는 8개 슬롯(cpu·gpu·ram·board·ssd·psu·case·cooler)과 목업에만 있던 monitor.
export type PartKey = 'cpu' | 'gpu' | 'ram' | 'ssd' | 'monitor' | 'board' | 'psu' | 'case' | 'cooler'

export interface Part {
  type: string
  name: string
  price: string
  meta: string
  source: string
  score: string
  fit: string
  /** true면 fit이 아직 LLM 생성 중이라 보여 주는 안내 문구다 — 화면이 이 값을 보고 다시 물어볼지 정한다 */
  fitPending?: boolean
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

/** "견적 수정하기"로 들어온 원본 견적서 — 장바구니에서 덮어쓸지 새로 저장할지 물을 때 쓴다 */
export interface EditingSheet {
  listId: string
  revisionNo: number
  name: string
  /** ISO yyyy-mm-dd */
  date: string
  target: number
  memo: string
}

/** 장바구니·확정 리포트에 함께 담는 주변기기 한 줄. variantId 가 있어야 확정에 보낼 수 있다(리포트에서 읽은 값에는 없다) */
export interface SetupPeripheral {
  kind: PeripheralKind
  name: string
  brand?: string
  /** 단가(참고가). 줄 금액은 price × qty */
  price: number
  qty: number
  variantId?: string | null
  imageUrl?: string | null
  productUrl?: string | null
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
  /** 견적 수정하기로 연 원본 견적서. 없으면 새 견적이다 */
  editingSheet: EditingSheet | null
  /** 확정한 견적서의 구성을 보기만 한다(대화 내역에서 확정된 대화를 열었을 때) — 부품·수량·대화를 바꿀 수 없다 */
  viewOnly: boolean
  /** 주변기기 추천에서 통합 장바구니로 보낸 품목. 본체 견적을 확정할 때 함께 저장된다 */
  peripherals: SetupPeripheral[]
  /** 본체 견적 없이 주변기기만 담았을 때, 그 추천을 받은 목록(세션) id. 확정은 이 목록으로 한다 */
  peripheralSessionId?: string | null
}

export interface ChatMessage {
  id: string
  role: 'bot' | 'user'
  text: string
  choices?: ChatChoice[]
  /** 'offer' 는 처음 화면에 띄우는 제안(지난 조건·선호 되묻기). 다시 제안할 때 앞서 붙인 것을 지우는 데 쓴다 */
  tag?: 'offer'
}

export interface SavedSetup {
  /** 서버 목록(list) id. 목록 하나에 확정 견적서가 여러 개일 수 있다 — 이 값은 그중 revisionNo 번 견적서다 */
  id: string
  /** 목록 안의 견적서 번호(1부터). 예전에 저장된 값에는 없다 */
  revisionNo?: number
  /** 같은 목록의 확정 견적서 전체(오래된 것부터). 목록 조회로 받은 최신 견적서에만 있다 */
  reports?: ReportSummary[]
  title: string
  date: string
  target: number
  memo: string
  savedAt: string
  plan: CurrentPlan
  desk: DeskState
  checkDraft: CheckDraft
  /** 확정할 때 같이 저장한 주변기기. 없으면 본체만 확정한 견적서다 */
  peripherals?: SetupPeripheral[]
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
  /** 서버 결과에서의 순서. 뺀 부품을 제자리에 흐리게 보여 줄 때 쓴다 */
  order?: number
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
  /** 합계·확정에 들어가는 부품(서버에서 선택된 것) */
  items: PlanItem[]
  /** 사용자가 뺀 부품. 합계·확정에서는 빠지고, 화면에서 "제외됨"으로 보이며 다시 넣을 수 있다 */
  excluded?: PlanItem[]
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
export interface ChatChoice { label: string; value: string; questionId?: string; resumeFrom?: string; startFresh?: boolean; preferenceHint?: { signalId: string; accepted: boolean } }

export interface ReviewRow {
  part: string
  original: string
  originalNote: string
  matched: string
  matchedNote: string
  state: 'ok' | 'warn'
  stateLabel: string
  /** state(ok/warn)보다 세분화된 값 — unmatched일 때만 실시간 검색 버튼을 보여준다. */
  matchStatus: 'confirmed' | 'ambiguous' | 'candidate' | 'inferred' | 'unmatched'
  /** 'live' 면 값 일부 또는 전부가 실시간 검색 결과다(상태는 그대로 확인 필요) */
  valueSource?: 'live' | null
}

export interface CheckDraft {
  question: string
  budget: string
  rows: ReviewRow[]
}
