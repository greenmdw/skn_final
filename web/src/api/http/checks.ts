import type { Api, QuoteReviewRequest, QuoteReviewResult } from '../types'
import { ApiError } from '../types'
import { request } from './client'
import { plans } from './plans'
import { backendSlotFromRowPart, reviewRowsFromWire, suggestionFromPlan } from './mapping'
import type { WireLiveSpecLookup, WireOwnedPartsPreviewOut, WireQuoteApply, WireQuoteChatHistory, WireQuoteChatOut, WireQuotePartCompare, WireQuoteReview } from './wire'

function translatedSpecs(currentSpecs?: Record<string, string>): Record<string, string> {
  const translated: Record<string, string> = {}
  for (const [part, value] of Object.entries(currentSpecs ?? {})) {
    const slot = backendSlotFromRowPart(part)
    if (slot && value.trim()) translated[slot] = value.trim()
  }
  return translated
}

function reviewBody(input: QuoteReviewRequest) {
  const conditions = input.conditions ? {
    purpose: input.conditions.purpose,
    resolution: input.conditions.resolution,
    priority: input.conditions.priority,
    games: input.conditions.games ?? [],
    budget_max: input.conditions.budgetMax,
  } : undefined
  return {
    current_specs: translatedSpecs(input.currentSpecs),
    text: input.text?.trim() || undefined,
    image_data_url: input.imageDataUrl || undefined,
    conditions,
  }
}

function quoteReviewFromWire(result: WireQuoteReview): QuoteReviewResult {
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

// 견적 점검의 업그레이드 제안 = 서버의 업그레이드 추천(mode=upgrade)을 그대로 돌려 그 결과를 제안 카드로 바꾼 것이다.
// 입력한 질문에서 바꿀 부품을, 점검 화면의 부품 표에서 현재 사양(current_specs)을 뽑아 보낸다(plans.recommend 와 같은 변환).
export const checks: Api['checks'] = {
  async suggestUpgrade(draft) {
    const budget = Number(String(draft.budget).replace(/[^0-9]/g, ''))
    const plan = await plans.recommend({
      mode: 'upgrade', budget: budget > 0 ? budget : null, checkSnapshot: draft,
      conditions: { intent: draft.question, performance: '', quiet: '' },
    })
    const suggestion = suggestionFromPlan(plan, draft)
    if (!suggestion) throw new ApiError('추천할 업그레이드 부품을 찾지 못했습니다. 질문에 바꾸고 싶은 부품을 적어주세요.', 'EMPTY_RESULT')
    return suggestion
  },
  async previewOwnedParts({ currentSpecs, text, imageDataUrl }) {
    // 점검 표의 부품 행 라벨(BOARD·SSD 등 화면 전용 이름 포함)을 백엔드 슬롯 이름으로 바꾼다.
    // 대응이 없으면(모니터 등) 빼고 보낸다 — 백엔드가 판정할 수 없는 걸 물어보지 않는다.
    // text·imageDataUrl(원문)은 그대로 보낸다 — 슬롯별로 나누는 건 서버(LLM 추출·규칙 파서)의 일이다.
    const translated = translatedSpecs(currentSpecs)
    if (Object.keys(translated).length === 0 && !text?.trim() && !imageDataUrl) return []
    const result = await request<WireOwnedPartsPreviewOut>('POST', '/pc/owned-parts/preview', {
      current_specs: translated, text: text?.trim() || undefined, image_data_url: imageDataUrl || undefined,
    })
    return reviewRowsFromWire(result.rows)
  },
  async createReview(input) {
    const result = await request<WireQuoteReview>('POST', '/pc/reviews', reviewBody(input))
    return quoteReviewFromWire(result)
  },
  async updateReview(listId, input) {
    const result = await request<WireQuoteReview>('PUT', `/pc/reviews/${encodeURIComponent(listId)}`, reviewBody(input))
    return quoteReviewFromWire(result)
  },
  async getReview(listId) {
    const result = await request<WireQuoteReview>('GET', `/pc/reviews/${encodeURIComponent(listId)}`)
    return quoteReviewFromWire(result)
  },
  async comparePart(listId, slot, direction) {
    const query = direction ? `?direction=${direction}` : ''
    const result = await request<WireQuotePartCompare>('GET', `/pc/reviews/${encodeURIComponent(listId)}/parts/${encodeURIComponent(slot)}/compare${query}`)
    return {
      slot: result.slot, baseline: result.baseline, unmatchedTargets: result.unmatched_targets, note: result.note,
      candidates: result.candidates.map(candidate => ({
        name: candidate.name, price: candidate.price, priceDelta: candidate.price_delta,
        perfTier: candidate.perf_tier, specs: candidate.specs, incompatible: candidate.incompatible,
        compatChanges: candidate.compat_changes, review: candidate.review,
      })),
    }
  },
  async liveLookupPart(listId, slot) {
    const result = await request<WireLiveSpecLookup>('POST', `/pc/reviews/${encodeURIComponent(listId)}/parts/${encodeURIComponent(slot)}/live-lookup`)
    return {
      slot: result.slot, query: result.query, relevant: result.relevant, supportedFields: result.supported_fields,
      sourceUrl: result.source_url, fetchedAt: result.fetched_at, reviewStatus: result.status,
      referencePrice: result.reference_price, referencePriceAt: result.reference_price_at,
    }
  },
  async sendMessage(listId, text) {
    return request<WireQuoteChatOut>('POST', `/pc/reviews/${encodeURIComponent(listId)}/messages`, { text })
  },
  async getMessages(listId) {
    const result = await request<WireQuoteChatHistory>('GET', `/pc/reviews/${encodeURIComponent(listId)}/messages`)
    return result.messages.map(message => ({ ...message, createdAt: message.created_at }))
  },
  async apply(listId, slots) {
    const result = await request<WireQuoteApply>('POST', `/pc/reviews/${encodeURIComponent(listId)}/apply`, { slots })
    return { listId: result.list_id, slots: result.slots, missing: result.missing, runId: result.run_id }
  },
}
