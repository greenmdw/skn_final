// 백엔드 응답 중 화면이 읽는 필드만 옮긴 타입이다(src/schemas.py 의 RecommendResultOut · ReportOut · ListsOut · UserEnvelopeOut).

export interface WireText { status: 'pending' | 'ready' | 'failed'; text: string | null }

export interface WireReview {
  total_count: number | null
  rating_refined: number | null
}

export interface WireProduct {
  /** 엔진 제품 키(예: amd-ryzen-5-5600). 리뷰 요약 조회에 쓴다 */
  product_key?: string
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
  budget_notice?: { message: string; budget: number; spent: number; remaining: number; suggest_priority?: 'performance' | null } | null
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
  /** 'live' 면 이 행의 값(전부 또는 일부)이 실시간 검색 결과다 — 카탈로그 정식 값이 아니다 */
  value_source?: 'live' | null
}

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
export interface WireQuoteApply { list_id: string; slots: string[]; missing: string[]; run_id: string | null }

// ── 받은 견적 점검: 여러 장 업로드 초안(src.schemas.QuoteDraft*) ──
export interface WireQuoteCapabilities {
  image_extraction: boolean; supported_types: string[]; max_files: number
  max_file_bytes: number; max_total_bytes: number; text_max_chars: number
}
export interface WireQuoteDraftItem {
  id: string; category: string; raw_text: string; normalized_name: string; product_code: string | null
  quantity: number; quote_unit_price: number | null; quote_line_total: number | null
  quote_price_type: 'unit' | 'line_total' | 'unknown'
  matched_product_id: string | null; matched_product_key: string | null; matched_name: string | null
  image_url: string | null
  match_status: 'confirmed' | 'ambiguous' | 'candidate' | 'inferred' | 'unmatched'
  candidate_count: number | null; source_ids: string[]; selected_for_analysis: boolean; user_edited: boolean
  /** 실시간 검색 값이 임시 저장소에 있다(저장되지 않는 표시) */
  live_value?: boolean
  /** 'model' = 제조사·시리즈를 줄여 쓴 글을 모델 번호로 찾아 확정했다 */
  match_via?: 'model' | null
}
export interface WireQuoteDraft {
  draft_id: string; version: number
  sources: { id: string; type: 'image' | 'text' | 'replacement' | 'manual'; file_name: string | null; sort_order: number; status: 'completed' | 'failed'; error_code: string | null }[]
  items: WireQuoteDraftItem[]
  selected_item_by_category: Record<string, string>
  conditions: Record<string, unknown>
  question: string | null
  partial_success: boolean
  groups: { id: string; name: string; source_ids: string[]; item_ids: string[] }[]
  created_at: string
}
export interface WireQuoteDraftAnalysis extends WireQuoteReview {
  used_items: WireQuoteDraftItem[]
  question: string | null
  draft_version: number
  price_excluded: { category: string; item_id: string; reason: string }[]
  price_rows: {
    category: string; item_id: string; quantity: number; quote_unit_price: number | null; quote_line_total: number | null
    quote_price_type: 'unit' | 'line_total' | 'unknown'; catalog_unit_price: number | null; catalog_line_total: number | null
    catalog_checked_at: string | null; catalog_status: 'available' | 'out_of_stock' | 'no_price' | 'unmatched'; diff_line_total: number | null
  }[]
}
export interface WireQuoteCompareSpec { key: string; label: string; unit: string; baseline: unknown; candidate: unknown; diff: number | null }
export interface WireQuoteDraftComparison {
  category: string; baseline_item_id: string
  recognized: {
    item_id: string; product_id: string | null; name: string; image_url: string | null; quantity: number
    quote_line_total: number | null; match_status: WireQuoteDraftItem['match_status']; specs: WireQuoteCompareSpec[]
  }[]
  recommended: {
    product_id: string | null; name: string; image_url: string | null; price: number | null; price_delta: number | null
    specs: WireQuoteCompareSpec[]
    compat_changes: { axis: string; label: string; from: string; to: string; detail: string }[]
    incompatible: string[]
    additional_replacements: { category: string; axis: string; reason: string }[]
    reason: string
  }[]
  notes: string[]
}
export interface WireQuoteReplacementPreview {
  before_total: number; after_total: number; total_diff: number
  new_issues: { axis: string; label: string; detail: string }[]
  resolved_issues: { axis: string; label: string; detail: string }[]
  additional_replacements: { category: string; axis: string; reason: string }[]
  price_excluded: { category: string; item_id: string; reason: string }[]
}
export interface WireComparisonProduct {
  product_id: string | null; product_key: string | null; name: string | null; image_url: string | null
  quantity: number; line_total: number | null
}
export interface WireQuoteSavedComparison {
  comparison_id: string; received_total: number; saved_total: number; total_diff: number
  comparable_categories: string[]; excluded_received_categories: string[]
  rows: { category: string; same_product: boolean; received: WireComparisonProduct | null; saved: WireComparisonProduct | null; price_diff: number | null }[]
  brief_summary: { changed_count: number; largest_price_difference_category: string | null; text: string }
  saved: Record<string, unknown>
  labels: Record<string, string>
  computed_at: string
}
export interface WireQuoteGuideRef { id: string; slot: string; kind: 'care' | 'install'; text: string; score: number | null }
export interface WireQuoteChatReply {
  reply: string; evidence: string[]; via: 'agent' | 'rules'
  message_id: string | null; answer_id: string | null
  guide_refs: WireQuoteGuideRef[]; visuals: Record<string, unknown>[]
  display_target: 'saved_comparison_explanation' | 'chat'
  duplicate_of: string | null; created_at: string | null
}
export interface WireQuoteChatHistoryRich {
  messages: {
    id: string; role: 'user' | 'assistant' | 'system'; text: string; created_at: string
    comparison_id: string | null; answer_id: string | null; evidence: string[]
    guide_refs: WireQuoteGuideRef[]; visuals: Record<string, unknown>[]
    via: 'agent' | 'rules' | null; display_target: 'saved_comparison_explanation' | 'chat' | null; duplicate_of: string | null
  }[]
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
export interface WirePreviousLookup {
  preference_hint?: { id: string; dimension: string; slot: string; value: string; direction: string; actionable: boolean; summary: string } | null
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
  /** 확정할 때 같이 얼린 주변기기(없으면 빈 배열) */
  peripherals?: { kind: 'monitor' | 'keyboard' | 'mouse' | 'speaker'; product: { product_key: string; name: string; image_url: string | null; purchase_url: string | null }; price: number; qty: number }[]
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

export interface WireReviewSummary {
  product_key: string
  product_name?: string | null
  total_count: number
  excluded_count?: number | null
  excluded_ratio?: number | null
  rating_raw?: number | null
  rating_refined?: number | null
  distribution_raw?: Record<string, number>
  distribution_refined?: Record<string, number>
  data_notice: string
  status: 'unavailable' | 'ready' | string
  product_manipulation_risk?: { evidence?: string[]; reliable_range?: boolean | null; control_scope?: string | null } | null
  aspect_facts?: string[]
  // synthetic_demo 는 일부러 읽지 않는다 — 서버가 "합성 데모값, 실사용자 노출 금지"로 표시한 값이다.
}

export interface WirePreviousComparison {
  available: boolean
  reason?: string | null
  text: string
  previous_list_id?: string | null
  previous_label?: string | null
  condition_changes?: { key: string; label: string; before: string; after: string }[]
  part_changes?: { slot: string; label: string; before: string | null; after: string | null; before_price: number | null; after_price: number | null; price_diff: number }[]
  unchanged?: string[]
  reasons?: { slot: string; label: string; kind: 'requirement' | 'unexplained'; claim: string; evidence?: string[] }[]
  totals?: { before: number; after: number; diff: number } | null
}

export interface WirePriceWatch {
  enabled: boolean
  target_amount: number | null
  status: 'waiting' | 'tracking' | 'reached'
  latest_total: number | null
  observed_at: string | null
}

export interface WireUser { user: { email: string; display_name: string; marketing_agreed?: boolean; created_at?: string } }

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

// ── 주변기기 추천(src.schemas.PeripheralsOut) ──────────────────────────────
export interface WirePeripheralReviewContribution {
  aspect_code: string
  evidence_state: string
  p: number
  n: number
  mixed: number
  /** observation_text 는 리뷰 분석이 만든 요약(대부분 영어)이고, evidence_sentences 는 리뷰 원문 문장(한글)이다 */
  members: { direction: string; observation_text: string; evidence_sentences?: string[] }[]
  /** 서버가 다수 의견 쪽에서 고른 한글 대표 문장. 없으면 null */
  quote?: { text: string; direction: 'positive' | 'negative' | 'mixed' } | null
  dissent?: boolean
}
export interface WirePeripheralScoreDetail { axes: { axis: string; label?: string; value: number; weight: number; points: number }[] }
export interface WirePeripheralRequested {
  label: string; source: 'stated' | 'situation' | 'purpose'; type: 'spec' | 'evidence'
  spec_checks: { key: string; text: string; ok: boolean }[]; feel_codes: string[]; external_aspects: string[]
}
export interface WirePeripheralItem {
  kind: 'monitor' | 'keyboard' | 'mouse' | 'speaker'
  kind_label: string
  product: { name: string; brand: string; variant_id: string | null; product_url: string | null; image_url: string | null }
  price: number
  price_source: string
  price_note: string
  requirement: { key: string; label: string; value: string }[]
  checks: { axis: string; label: string; state: string; detail: string }[]
  reason: { status: string; text: string | null }
  /** 1위 말고 비교해 볼 만한 제품. 서버는 이름·가격 차이와 리뷰 근거(review)만 준다 — 사양 점검·제품 식별자는 없다 */
  alternatives: {
    name: string; price: number; diff: number; review?: { contributions: WirePeripheralReviewContribution[] } | null; review_note?: string
    variant_id?: string | null; brand?: string | null; image_url?: string | null; product_url?: string | null
    key_specs?: { key: string; label: string; value: string }[]; requested?: WirePeripheralRequested[]
    price_position?: { rank: number; of: number } | null; feel?: WirePeripheralFeel | null; score_detail?: WirePeripheralScoreDetail | null
  }[]
  guide: { status: string; text: string | null }
  review: { contributions: WirePeripheralReviewContribution[] } | null
  review_weight: number
  review_note: string
  /** 체감 근거 블록. null 이면 보여 줄 근거가 없다 */
  feel?: WirePeripheralFeel | null
  feel_note?: string | null
  key_specs?: { key: string; label: string; value: string }[]
  requested?: WirePeripheralRequested[]
  price_position?: { rank: number; of: number } | null
  score_detail?: WirePeripheralScoreDetail | null
}
export interface WirePeripheralFeel {
  value: number
  basis: 'community' | 'example' | 'external_only'
  basis_text: string
  recent_authors: number | null
  attributes: {
    code: string; label: string; type?: string; state: string; text: string; alpha?: number; split: boolean; mismatch: boolean
    good?: number; bad?: number
    quotes: { quote_id: string; post_id: string; sentence: string; is_example?: boolean; photo_url: string | null }[]
  }[]
}
export interface WirePeripheralAdjustChip {
  kind: 'monitor' | 'keyboard' | 'mouse' | 'speaker'
  id: string
  label: string
  add: { purposes?: string[]; situations?: string[]; stated?: Record<string, string[]> }
  moved: number
}
export interface WirePeripherals {
  status: 'ready' | 'empty' | 'skipped'
  items: WirePeripheralItem[]
  empty: { kind: string; reason: string }[]
  totals: { reference_price: number; note: string }
  ignored_inputs?: string[]
  adjust_chips?: WirePeripheralAdjustChip[]
  notices?: { kind: string; code: string; text: string }[]
}

// ── 견적 문장 해석(src.schemas.PeripheralInterpretOut) ──
export interface WirePeripheralInterpretation {
  kinds: ('monitor' | 'keyboard' | 'mouse' | 'speaker')[]
  purposes: string[]
  situations: string[]
  stated: Record<string, string[]>
  hand_size: 'small' | 'medium' | 'large' | null
  budget: Record<string, number>
  budget_min?: Record<string, number>
  budget_total: number | null
  emphasis?: Record<string, string[]>
  brand_like?: Record<string, string[]>
  brand_avoid?: Record<string, string[]>
  unrecognized: string[]
}
export interface WirePeripheralResolvedCondition { condition: string; label: string; sources?: string[] }
export interface WirePeripheralInterpret {
  interpretation: WirePeripheralInterpretation
  resolved: Record<string, {
    kind: 'monitor' | 'keyboard' | 'mouse' | 'speaker'
    label: string
    purposes?: { code: string; label: string }[]
    preferences?: WirePeripheralResolvedCondition[]
    filters?: WirePeripheralResolvedCondition[]
    conflicts?: { conditions: string[]; labels: string[]; kept: string | null }[]
  }>
  needs_kind: boolean
  source: 'llm' | 'rules'
  truncated?: boolean
}
export interface WirePeripheralChat extends WirePeripheralInterpret {
  turn: {
    new_conditions: { kind: string; label: string }[]
    not_reflected: string[]
    notes: string[]
    answer: { type: string; topic: string | null; text: string; kinds: ('monitor' | 'keyboard' | 'mouse' | 'speaker')[]; chips: string[] } | null
    reply: string
    chips: string[]
    result_chips: string[]
  }
}
