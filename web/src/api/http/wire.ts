// 백엔드 응답 중 화면이 읽는 필드만 옮긴 타입이다(src/schemas.py 의 RecommendResultOut · ReportOut · ListsOut · UserEnvelopeOut).

export interface WireText { status: 'pending' | 'ready' | 'failed'; text: string | null }

export interface WireReview {
  total_count: number | null
  rating_refined: number | null
}

export interface WireProduct {
  name: string
  brand: string
  spec_summary: string | null
}

export interface WireItem {
  item_id: string
  slot: string
  slot_label: string
  product: WireProduct
  price: number
  price_source: string
  price_observed_at: string | null
  qty: number
  selected: boolean
  timing: 'now' | 'soon' | 'later' | string
  budget_share: number | null
  review: WireReview | null
  reason: WireText
  /** 구매 전 확인: 부품 사용 가이드 + 이 부품에 걸린 세트 검증 쟁점(" · " 로 이어 붙인 한 문장) */
  checks?: WireText | null
  alternatives_count: number
}

export interface WireCompatCheck { axis: string; label: string; state: 'ok' | 'unknown' | 'fail' | 'skipped' | string; detail: string }

export interface WireIssue { axis: string; severity: 'major' | 'minor' | string; text: string }

export interface WireResult {
  list_id: string
  status: 'running' | 'done' | 'failed'
  items: WireItem[]
  explanation: { status: 'pending' | 'ready' | 'failed' }
  /** 세트 전체 호환 점검. major = 확정된 문제(소켓·전력·크기·예산), minor = 스펙을 몰라 정밀 검사를 못 한 항목 */
  verification?: { status: 'pending' | 'ready' | 'failed'; issues: WireIssue[] } | null
  /** 호환 검사별 상세(무엇을 비교했고 결과가 어땠는지). 서버가 지금 선택된 부품으로 매번 계산한다 */
  compat_checks?: WireCompatCheck[] | null
  error: { code: string; message: string } | null
}

export interface WireSessionState {
  can_recommend: boolean
  next_question: { id: string; select: string; options: { value: unknown }[] } | null
}

// ── 조건 대화 세션(src.schemas.ConditionState) ──────────────────────────────
export interface WireMessage { id: string; role: string; text: string; created_at: string }
export interface WireField {
  key: string
  label: string
  value: unknown
  display: string | null
  status: string
  editable: boolean
}
export interface WireNextQuestion {
  id: string
  field: string
  text: string
  select: 'single' | 'multi' | 'free' | string
  options: { value: unknown; label?: string }[]
}
export interface WireConditionState {
  list_id: string
  category: string | null
  mode: string | null
  messages: WireMessage[]
  fields: WireField[]
  next_question: WireNextQuestion | null
  can_recommend: boolean
}

export interface WireReportItem {
  slot: string
  slot_label: string
  product: { name: string }
  price: number
  qty: number
  timing: string
  review: WireReview | null
  evidence_text: string | null
}

export interface WireReport {
  list_id: string
  name: string
  planned_purchase_at: string | null
  target_amount: number | null
  memo: string
  total: number
  confirmed_at: string
  items: WireReportItem[]
}

export interface WireLists {
  items: { list_id: string; category: string | null; stage: 'category' | 'conditions' | 'results' | 'report' }[]
}

export interface WireUser { user: { email: string; display_name: string } }
