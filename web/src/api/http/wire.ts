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
  image_url?: string | null
  purchase_url?: string | null
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
  explanation: { status: 'pending' | 'ready' | 'failed'; contribution?: Record<string, number> | null }
  budget_notice?: { message: string; budget: number; spent: number; remaining: number; suggest_priority: 'performance' } | null
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

// ── 견적 점검: 사양 텍스트 매칭 미리보기(src.schemas.OwnedPartsPreview*) — 세션 없이 호출 ──
export interface WireOwnedPartsPreviewRow {
  part: string
  original: string
  matched: string
  matched_note: string
  state: 'ok' | 'warn'
  match_status: 'confirmed' | 'ambiguous' | 'candidate' | 'inferred' | 'unmatched'
  candidate_count: number | null
}
export interface WireOwnedPartsPreviewOut { rows: WireOwnedPartsPreviewRow[] }

export interface WireQuoteCompat {
  checks: { axis: string; label: string; state: 'ok' | 'fail' | 'unknown' | 'skipped'; detail: string }[]
  summary: Record<string, number>
  incompatible: string[]
}
export interface WireQuotePriceRow {
  part: string; matched: string | null; quoted: number | null; catalog: number | null; quantity: number
  diff: number | null; diff_pct: number | null
  state: 'cheaper' | 'similar' | 'pricier' | 'no_quote_price' | 'no_catalog'; detail: string
}
export interface WireQuoteReview {
  list_id: string
  version: number
  input: { current_specs: Record<string, string>; conditions: Record<string, unknown>; input_hash: string }
  parts: WireOwnedPartsPreviewRow[]
  compat: WireQuoteCompat
  prices: { available: boolean; reason: string | null; rows: WireQuotePriceRow[]; summary: Record<string, unknown> } | null
  balance: { available: boolean; reason: string | null; rows: { part: string; aspect: string; state: 'short' | 'excess' | 'ok' | 'unknown'; detail: string; measured: number | null; target: number | null }[]; summary: Record<string, number>; notes: string[] } | null
  compare: { available: boolean; reason: string | null; rows: { part: string; quote: Record<string, unknown> | null; ours: Record<string, unknown>; same_product: boolean; price_diff: number | null; price_diff_pct: number | null; price_state: 'cheaper' | 'similar' | 'pricier' | null; tier_diff: number | null; detail: string }[]; summary: Record<string, unknown>; notes: string[] } | null
  computed_at: string
}
export interface WireQuotePartCompare {
  slot: string
  baseline: Record<string, unknown>
  candidates: { name: string; price: number; price_delta: number | null; perf_tier: number | null; specs: { key: string; label: string; unit: string; baseline: unknown; candidate: unknown; diff: number | null }[]; incompatible: string[]; compat_changes: { axis: string; label: string; from: string; to: string; detail: string }[]; review: Record<string, unknown> | null }[]
  unmatched_targets: string[]
  note: string | null
}
export interface WireLiveSpecLookup {
  slot: string
  query: string
  relevant: boolean
  supported_fields: Record<string, unknown>
  source_url: string | null
  fetched_at: string | null
  status: 'unreviewed' | 'confirmed' | 'rejected'
  cached: boolean
  reference_price: number | null
  reference_price_source_url: string | null
  reference_price_at: string | null
}
export interface WireQuoteChatOut { reply: string; evidence: string[]; via: 'agent' | 'rules' }
export interface WireQuoteChatHistory { messages: { id: string; role: 'user' | 'assistant' | 'system'; text: string; created_at: string }[] }
export interface WireQuoteApply { list_id: string; slots: string[]; missing: string[]; run_id: string | null }

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
export interface WirePreviousLookup {
  previous: { list_id: string; name: string; confirmed: boolean; last_active_at: string; summary: string;
    fields: { key: string; label: string | null; display: string }[] } | null
}
export interface WireConditionState {
  list_id: string
  category: string | null
  mode: string | null
  messages: WireMessage[]
  fields: WireField[]
  next_question: WireNextQuestion | null
  can_recommend: boolean
  budget_warning?: { level: 'tight' | 'infeasible' | 'ok'; message: string | null; estimated_min: number; budget: number } | null
}

export interface WireReportItem {
  slot: string
  slot_label: string
  product: { name: string; image_url?: string | null; purchase_url?: string | null }
  price: number
  qty: number
  review: WireReview | null
  evidence_text: string | null
}

export interface WireReport {
  list_id: string
  /** 목록 안의 견적서 번호(1부터) */
  revision_no: number
  name: string
  planned_purchase_at: string | null
  target_amount: number | null
  memo: string
  total: number
  confirmed_at: string
  items: WireReportItem[]
}

export interface WireReportSummary {
  revision_no: number
  name: string
  confirmed_at: string
  total: number
  /** 본체 부품 수만 */
  item_count: number
  /** 확정할 때 같이 저장한 주변기기 수(없으면 0) */
  peripheral_count?: number
  planned_purchase_at: string | null
}

export interface WireListSummary {
  list_id: string
  name: string
  category: string | null
  stage: 'category' | 'conditions' | 'results' | 'report'
  updated_at: string
  last_active_at: string | null
  first_message: string | null
  conditions_summary: string
  total: number | null
  planned_purchase_at: string | null
  item_count: number | null
  reports: WireReportSummary[]
}

export interface WireLists {
  items: WireListSummary[]
}

// ── 견적 리스트 히스토리(src.schemas.ListHistoryOut) ──
export interface WireListHistory {
  summary: WireText
  steps?: { kind: string; text: string; quote: string | null; changes: string[]; notes: string[] }[]
  events: { at: string; kind: string; text: string; quote?: string | null }[]
}

export interface WireUser { user: { email: string; display_name: string } }

// ── 부품 교체(src.schemas.AlternativesOut) ──
export interface WireAlternative {
  candidate_id: string
  label: string
  current: boolean
  product: WireProduct
  price: number
  price_delta: number
  review: WireReview | null
}

// ---- 주변기기 추천 (POST /session/{id}/peripherals/recommend) ----
export interface WirePeripheralText { status: string; text: string | null }
export interface WirePeripheralItem {
  kind: 'monitor' | 'keyboard' | 'mouse' | 'speaker'
  kind_label: string
  product: { name: string; brand: string; variant_id: string | null; product_url: string | null; image_url: string | null }
  price: number
  price_source: string
  price_note: string
  requirement: { key: string; label: string; value: string }[]
  checks: { axis: string; label: string; state: string; detail: string }[]
  reason: WirePeripheralText
  alternatives: { name: string; price: number; diff: number }[]
  guide: WirePeripheralText
}
export interface WirePeripherals {
  status: 'ready' | 'empty' | 'skipped'
  items: WirePeripheralItem[]
  empty: { kind: string; reason: string }[]
  totals: { reference_price: number; note: string }
}
