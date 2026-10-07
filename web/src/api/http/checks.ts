import type { Api, QuoteReviewResult } from '../types'
import { request } from './client'
import { reviewRowsFromWire } from './mapping'
import type { WireQuoteApply, WireQuoteReview } from './wire'

export function quoteReviewFromWire(result: WireQuoteReview): QuoteReviewResult {
  return {
    listId: result.list_id,
    version: result.version,
    input: { currentSpecs: result.input.current_specs, conditions: result.input.conditions, inputHash: result.input.input_hash },
    parts: reviewRowsFromWire(result.parts),
    compat: result.compat,
    prices: result.prices ? {
      available: result.prices.available, reason: result.prices.reason, summary: result.prices.summary,
      rows: result.prices.rows.map(row => ({
        part: row.part, matched: row.matched, quoted: row.quoted, catalog: row.catalog,
        quantity: row.quantity, diff: row.diff, diffPercent: row.diff_pct, state: row.state, detail: row.detail,
      })),
    } : null,
    balance: result.balance,
    compare: result.compare ? {
      available: result.compare.available, reason: result.compare.reason, summary: result.compare.summary, notes: result.compare.notes,
      rows: result.compare.rows.map(row => ({
        part: row.part, quote: row.quote, ours: row.ours, sameProduct: row.same_product,
        priceDiff: row.price_diff, priceDiffPercent: row.price_diff_pct, priceState: row.price_state,
        tierDiff: row.tier_diff, detail: row.detail,
      })),
    } : null,
    computedAt: result.computed_at,
  }
}

// 받은 견적 점검은 여러 장 업로드 초안(quoteDrafts)이 맡는다. 여기에는 저장된 점검 결과를 읽는 것과 장바구니(새 추천 세션)로
// 넘기는 것만 남아 있다 — 분석 결과는 초안의 list_id 와 같은 id 로 읽는다.
export const checks: Api['checks'] = {
  async getReview(listId) {
    const result = await request<WireQuoteReview>('GET', `/pc/reviews/${encodeURIComponent(listId)}`)
    return quoteReviewFromWire(result)
  },
  async apply(listId, slots) {
    const result = await request<WireQuoteApply>('POST', `/pc/reviews/${encodeURIComponent(listId)}/apply`, { slots })
    return { listId: result.list_id, slots: result.slots, missing: result.missing, runId: result.run_id }
  },
}
