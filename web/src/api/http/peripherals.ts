import type {
  Api, PeripheralFeel, PeripheralInterpretation, PeripheralItem, PeripheralKind, PeripheralResolvedKind, PeripheralReviewAspect,
} from '../types'
import { request } from './client'
import type {
  WirePeripheralFeel, WirePeripheralInterpret, WirePeripheralInterpretation, WirePeripheralItem, WirePeripheralReviewContribution, WirePeripherals,
} from './wire'

function aspectsFromWire(review: { contributions: WirePeripheralReviewContribution[] } | null | undefined): PeripheralReviewAspect[] {
  return (review?.contributions ?? []).map(entry => ({
    aspectCode: entry.aspect_code,
    state: entry.evidence_state,
    positive: entry.p,
    negative: entry.n,
    mixed: entry.mixed,
    quote: entry.members[0]?.observation_text ?? null,
  }))
}

function feelFromWire(feel: WirePeripheralFeel | null | undefined): PeripheralFeel | null {
  if (!feel) return null
  return {
    value: feel.value, basis: feel.basis, basisText: feel.basis_text, recentAuthors: feel.recent_authors ?? null,
    attributes: feel.attributes.map(attribute => ({
      code: attribute.code, label: attribute.label, text: attribute.text, state: attribute.state,
      split: attribute.split, mismatch: attribute.mismatch,
      quotes: attribute.quotes.map(quote => ({
        quoteId: quote.quote_id, postId: quote.post_id, sentence: quote.sentence, isExample: Boolean(quote.is_example), photoUrl: quote.photo_url ?? null,
      })),
    })),
  }
}

function itemFromWire(item: WirePeripheralItem): PeripheralItem {
  const aspects = aspectsFromWire(item.review)
  return {
    kind: item.kind, kindLabel: item.kind_label, name: item.product.name, brand: item.product.brand,
    variantId: item.product.variant_id, productUrl: item.product.product_url, imageUrl: item.product.image_url,
    price: item.price, priceNote: item.price_note,
    requirement: item.requirement,
    checks: item.checks.map(check => ({ axis: check.axis, label: check.label, state: check.state === 'ok' || check.state === 'fail' ? check.state : 'unknown', detail: check.detail })),
    reason: item.reason, guide: item.guide,
    reviewAspects: aspects, reviewWeight: item.review_weight, reviewNote: item.review_note,
    alternatives: item.alternatives.map(alternative => ({
      name: alternative.name, price: alternative.price, diff: alternative.diff,
      reviewAspects: aspectsFromWire(alternative.review), reviewNote: alternative.review_note ?? '',
    })),
    feel: feelFromWire(item.feel), feelNote: item.feel_note ?? null,
  }
}

const interpretationFromWire = (wire: WirePeripheralInterpretation): PeripheralInterpretation => ({
  kinds: wire.kinds ?? [], purposes: wire.purposes ?? [], situations: wire.situations ?? [], stated: wire.stated ?? {},
  handSize: wire.hand_size ?? null, budget: wire.budget ?? {}, budgetTotal: wire.budget_total ?? null, unrecognized: wire.unrecognized ?? [],
})

// previous 로 돌려보낼 때는 서버가 준 모양(snake_case) 그대로여야 한다.
const interpretationToWire = (value: PeripheralInterpretation): WirePeripheralInterpretation => ({
  kinds: value.kinds, purposes: value.purposes, situations: value.situations, stated: value.stated as Record<string, string[]>,
  hand_size: value.handSize, budget: value.budget as Record<string, number>, budget_total: value.budgetTotal, unrecognized: value.unrecognized,
})

// 서버는 추천을 "목록(세션)"에 묶어 호출한다. PC 견적 대화 없이도 쓸 수 있어, 처음이면 빈 세션을 하나 만든다.
export const peripherals: Api['peripherals'] = {
  async recommend(input, sessionId) {
    const id = sessionId ?? (await request<{ list_id: string }>('POST', '/session')).list_id
    // 예전 입력(purpose·priority·noise_sensitive·resolution)은 새 화면에서 보내지 않는다 — 문장 해석 결과를 그대로 싣는다.
    const body = {
      kinds: input.kinds,
      budget_max: input.budgetMax,
      purposes: input.purposes ?? [],
      situations: input.situations ?? [],
      stated: input.stated ?? {},
      kind_budget: input.kindBudget ?? {},
      pc_list_id: input.pcListId,
    }
    const result = await request<WirePeripherals>('POST', `/session/${encodeURIComponent(id)}/peripherals/recommend`, body)
    return {
      sessionId: id, status: result.status, items: result.items.map(itemFromWire), empty: result.empty,
      referencePrice: result.totals.reference_price, priceNote: result.totals.note,
      ignoredInputs: result.ignored_inputs ?? [],
      adjustChips: (result.adjust_chips ?? []).map(chip => ({ kind: chip.kind, id: chip.id, label: chip.label, add: chip.add, moved: chip.moved })),
    }
  },

  async interpret({ text, previous, kinds }) {
    const result = await request<WirePeripheralInterpret>('POST', '/peripherals/interpret', {
      text, previous: previous ? interpretationToWire(previous) : null, kinds: kinds && kinds.length ? kinds : null,
    })
    const resolved: Partial<Record<PeripheralKind, PeripheralResolvedKind>> = {}
    for (const [kind, entry] of Object.entries(result.resolved ?? {})) {
      resolved[kind as PeripheralKind] = {
        kind: entry.kind, label: entry.label, purposes: entry.purposes ?? [],
        preferences: (entry.preferences ?? []).map(item => ({ condition: item.condition, label: item.label, sources: item.sources ?? [] })),
        filters: (entry.filters ?? []).map(item => ({ condition: item.condition, label: item.label, sources: item.sources ?? [] })),
      }
    }
    return {
      interpretation: interpretationFromWire(result.interpretation), resolved,
      needsKind: result.needs_kind, source: result.source, truncated: Boolean(result.truncated),
    }
  },
}
