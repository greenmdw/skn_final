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
  alternatives_count: number
}

export interface WireResult {
  list_id: string
  status: 'running' | 'done' | 'failed'
  items: WireItem[]
  explanation: { status: 'pending' | 'ready' | 'failed' }
  error: { code: string; message: string } | null
}

export interface WireSessionState {
  can_recommend: boolean
  next_question: { id: string; select: string; options: { value: unknown }[] } | null
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
