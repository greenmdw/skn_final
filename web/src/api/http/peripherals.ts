import type { Api, PeripheralItem } from '../types'
import { request } from './client'
import type { WirePeripheralItem, WirePeripherals } from './wire'

function itemFromWire(item: WirePeripheralItem): PeripheralItem {
  const aspects = (item.review?.contributions ?? []).map(entry => ({
    aspectCode: entry.aspect_code,
    state: entry.evidence_state,
    positive: entry.p,
    negative: entry.n,
    mixed: entry.mixed,
    quote: entry.members[0]?.observation_text ?? null,
  }))
  return {
    kind: item.kind, kindLabel: item.kind_label, name: item.product.name, brand: item.product.brand,
    variantId: item.product.variant_id, productUrl: item.product.product_url, imageUrl: item.product.image_url,
    price: item.price, priceNote: item.price_note,
    requirement: item.requirement,
    checks: item.checks.map(check => ({ axis: check.axis, label: check.label, state: check.state === 'ok' || check.state === 'fail' ? check.state : 'unknown', detail: check.detail })),
    reason: item.reason, guide: item.guide,
    reviewAspects: aspects, reviewWeight: item.review_weight, reviewNote: item.review_note,
    alternatives: item.alternatives,
  }
}

// 서버는 추천을 "목록(세션)"에 묶어 호출한다. PC 견적 대화 없이도 쓸 수 있어, 처음이면 빈 세션을 하나 만든다.
export const peripherals: Api['peripherals'] = {
  async recommend(input, sessionId) {
    const id = sessionId ?? (await request<{ list_id: string }>('POST', '/session')).list_id
    const body = {
      kinds: input.kinds,
      budget_max: input.budgetMax,
      resolution: input.resolution,
      priority: input.priority,
      noise_sensitive: input.noiseSensitive,
      pc_list_id: input.pcListId,
    }
    const result = await request<WirePeripherals>('POST', `/session/${encodeURIComponent(id)}/peripherals/recommend`, body)
    return {
      sessionId: id, status: result.status, items: result.items.map(itemFromWire), empty: result.empty,
      referencePrice: result.totals.reference_price, priceNote: result.totals.note,
    }
  },
}
