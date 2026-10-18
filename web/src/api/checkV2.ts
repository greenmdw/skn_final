// 받은 견적 점검 새 화면(/check/…)이 쓰는 API. 서버 응답을 거의 그대로(snake_case) 쓰고, 새 화면이 아는 필드만 타입으로 적는다.
// 기존 `api` 객체(types.ts)와 분리한 이유: 새 화면이 안정되어 기존 CheckPage 를 걷어낼 때 이 파일만 남기고 합치기 위해서다(재기획 8단계).
import { request, requestForm } from './http/client'

export interface MatchReason {
  code: 'not_in_catalog' | 'variant_mismatch' | 'ambiguous' | 'insufficient_info' | 'uncertain_reading' | 'low_quality_photo'
  message: string
  nearest?: { name?: string; why_not?: string; key_specs?: string[] } | null
  candidates: { name: string; product_key?: string; key_specs?: string[] }[]
}

export interface DraftItem {
  id: string; category: string; raw_text: string; normalized_name: string; quantity: number
  quote_unit_price: number | null; quote_line_total: number | null
  matched_product_id: string | null; matched_name: string | null; image_url: string | null
  match_status: 'confirmed' | 'ambiguous' | 'candidate' | 'inferred' | 'unmatched'
  match_reason: MatchReason | null; source_ids: string[]; selected_for_analysis: boolean; live_value: boolean
}

export interface SourceRelation {
  applies: boolean; mode: 'single' | 'separate'; confidence: 'high' | 'low'; confirmed: boolean; reasons: string[]; doubts: string[]
}

export interface Draft {
  draft_id: string; version: number
  sources: { id: string; type: string; file_name: string | null; status: 'completed' | 'failed'; quality_warning?: string | null; ignored_lines?: string[] }[]
  items: DraftItem[]
  selected_item_by_category: Record<string, string>
  conditions: Record<string, unknown>
  question: string | null
  groups: { id: string; name: string; source_ids: string[]; item_ids: string[] }[]
  source_relation: SourceRelation | null
  analysis_stale: boolean
}

export interface PriceView {
  mode: 'line' | 'total_only' | 'none'; quote_total: number | null; line_total: number | null
  priced_count: number; total_count: number; catalog_total: number | null; label: string; note: string | null
}

export interface CompatCheck { axis: string; label: string; state: 'ok' | 'fail' | 'unknown' | 'skipped'; detail: string }
export interface BalanceRow { part: string; aspect: string; state: 'short' | 'excess' | 'ok' | 'unknown'; detail: string }

export interface Analysis {
  list_id: string; draft_version: number
  compat: { checks: CompatCheck[]; summary: Record<string, number>; incompatible: string[] }
  balance: { available: boolean; reason: string | null; rows: BalanceRow[]; summary: Record<string, number>; notes: string[] } | null
  input: { current_specs: Record<string, string>; conditions: Record<string, unknown> }
  /** 분석 직후 응답에만 있다 — 저장된 결과를 다시 읽으면(getReview) 없다 */
  price_view?: PriceView
  parts: unknown[]
}

export interface TargetReason { code: string; text: string }
export interface Candidate {
  product_id: string | null; name: string; price: number | null; price_delta: number | null; grade_label: string | null
  grade_change: number | null; resolves: string[]; resolves_all: boolean
  /** 후보 카드에 붙일 주의("성능이 낮아요" 등) */
  cautions: string[]
  recommend_score: number | null
}
export interface Target {
  slot: string; current_name: string | null; current_confirmed: boolean; kind: 'replace' | 'verify' | 'keep'
  rank: number | null; reasons: TargetReason[]; candidates: Candidate[]; note: string | null
  /** 과한 부품의 절감 후보(가성비 우선일 때만, 선택 사항) */
  savings: Candidate[]; savings_note: string | null
}
export interface Targets { replace_budget: number | null; counts: Record<string, number>; targets: Target[]; draft_version: number; analysis_stale: boolean }

export interface ReplacementState {
  replacements: { slot: string; candidate: { product_id: string | null; name: string; price: number | null }; from: { name: string | null; price: number | null }; price_delta: number | null; warnings: string[] }[]
  compat: { before: Record<string, number>; after: Record<string, number>; new_issues: string[]; resolved_issues: string[] }
  games: { game: string; before: unknown; after: unknown }[]
  price: { delta_total: number; unpriced_slots: string[]; replace_budget: number | null; over_budget: boolean }
  draft_version: number; analysis_stale: boolean
}

export interface Report { list_id: string; revision_no: number; name: string; total: number; source: string }

const base = (id: string) => `/pc/review-drafts/${encodeURIComponent(id)}`

export const checkV2 = {
  getDraft: (id: string) => request<Draft>('GET', base(id)),
  createDraft: (form: FormData) => requestForm<Draft>('/pc/review-drafts', form),
  patchConditions: (id: string, version: number, conditions: Record<string, unknown>) =>
    request<Draft>('PATCH', `${base(id)}/conditions`, { expected_version: version, conditions }),
  setSourceRelation: (id: string, version: number, mode: 'single' | 'separate') =>
    request<Draft>('PATCH', `${base(id)}/source-relation`, { expected_version: version, mode }),
  patchItems: (id: string, version: number, items: { id: string; delete?: boolean; normalized_name?: string; quantity?: number }[], selected?: Record<string, string>) =>
    request<Draft>('PATCH', `${base(id)}/items`, { expected_version: version, items, ...(selected ? { selected_item_by_category: selected } : {}) }),
  analyze: (id: string) => request<Analysis>('POST', `${base(id)}/analysis`, {}),
  getReview: (id: string) => request<Analysis>('GET', `/pc/reviews/${encodeURIComponent(id)}`),
  liveLookup: (id: string, itemId: string) => request<{ relevant: boolean; supported_fields: Record<string, unknown>; source_url: string | null; reference_price: number | null }>(
    'POST', `${base(id)}/items/${encodeURIComponent(itemId)}/live-lookup`),
  targets: (id: string) => request<Targets>('GET', `${base(id)}/replacement-targets`),
  replacements: (id: string) => request<ReplacementState>('GET', `${base(id)}/replacements`),
  putReplacement: (id: string, version: number, slot: string, productId: string) =>
    request<ReplacementState>('PUT', `${base(id)}/replacements/${encodeURIComponent(slot)}`, { expected_version: version, candidate_product_id: productId }),
  removeReplacement: (id: string, version: number, slot: string) =>
    request<ReplacementState>('DELETE', `${base(id)}/replacements/${encodeURIComponent(slot)}`, { expected_version: version }),
  confirm: (id: string, body: { expected_version: number; name: string; planned_purchase_at?: string | null; target_amount?: number | null; memo?: string; over_budget_ack?: boolean }) =>
    request<Report>('POST', `${base(id)}/confirm`, body),
  /** 확정한 받은 견적 리포트의 구성으로 새 점검을 시작한다 — 새 draft_id 를 돌려준다 */
  restart: (id: string) => request<Draft>('POST', `${base(id)}/restart`),
}

export interface KeptPart { slot: string; slot_label: string; source_text: string; name: string; match_status: string | null; qty: number; line_amount: number | null }
export interface QuoteReportExtra { total: number; target_amount: number | null; source: 'recommendation' | 'quote_check'; kept_parts: KeptPart[]; quote_check: { total_partial?: boolean; kept_unpriced_slots?: string[] } | null }

/** 리포트에서 받은 견적용 섹션(유지한 부품)만 따로 읽는다. 기존 리포트 매핑(SavedSetup)은 건드리지 않는다. */
export const quoteReportExtra = (listId: string, revisionNo?: number | null) =>
  request<QuoteReportExtra>('GET', `/lists/${encodeURIComponent(listId)}/report${revisionNo ? `?revision=${revisionNo}` : ''}`)

export interface LiveBatchItem {
  item_id: string; state: 'found' | 'not_found' | 'failed' | 'skipped'; message: string | null
}
export interface LiveBatchResult { items: LiveBatchItem[]; found: number; not_found: number; failed: number; skipped: number }
/** 한 번에 찾을 수 있는 개수의 서버 기본값(LIVE_LOOKUP_BATCH_MAX) — 넘으면 서버가 거절하므로 화면이 미리 자른다. */
export const LIVE_BATCH_MAX = 6
export const liveLookupBatch = (draftId: string, itemIds: string[]) =>
  request<LiveBatchResult>('POST', `/pc/review-drafts/${encodeURIComponent(draftId)}/live-lookup-batch`, { item_ids: itemIds })

// ── 채팅 동작(재기획 6단계) ──────────────────────────────────────────────────────
export type ChatUndo =
  | { kind: 'remove_replacement'; slot: string }
  | { kind: 'put_replacement'; slot: string; product_id: string }
  | { kind: 'restore_replacements'; items: { slot: string; product_id: string }[] }
  | { kind: 'set_conditions'; values: Record<string, unknown> }
  | { kind: 'edit_item'; item_id: string; name: string }
export interface ChatAction { kind: string; label: string; undo: ChatUndo | null }
export interface ChatReply { reply: string; action: ChatAction | null }

export const sendChat = (draftId: string, text: string, clientMessageId: string) =>
  request<ChatReply>('POST', `/pc/reviews/${encodeURIComponent(draftId)}/messages`, { text, client_message_id: clientMessageId })

/** 채팅 동작 되돌리기 — 최신 버전을 읽어 와서 같은 REST 함수로 되돌린다(서버 규칙·소유권 검사가 그대로 적용된다). */
export async function undoChatAction(draftId: string, undo: ChatUndo): Promise<void> {
  const version = async () => (await checkV2.getDraft(draftId)).version
  if (undo.kind === 'remove_replacement') { await checkV2.removeReplacement(draftId, await version(), undo.slot); return }
  if (undo.kind === 'put_replacement') { await checkV2.putReplacement(draftId, await version(), undo.slot, undo.product_id); return }
  if (undo.kind === 'restore_replacements') {
    for (const row of undo.items) await checkV2.putReplacement(draftId, await version(), row.slot, row.product_id)
    return
  }
  if (undo.kind === 'set_conditions') { await checkV2.patchConditions(draftId, await version(), undo.values); return }
  await checkV2.patchItems(draftId, await version(), [{ id: undo.item_id, normalized_name: undo.name }])
}
