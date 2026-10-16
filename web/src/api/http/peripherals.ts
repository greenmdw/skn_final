import type {
  Api, PeripheralFeel, PeripheralInterpretation, PeripheralInterpretResult, PeripheralItem, PeripheralKind, PeripheralResolvedKind,
  PeripheralRequested, PeripheralReviewAspect, PeripheralScoreAxis,
} from '../types'
import { request } from './client'
import type {
  WirePeripheralChat, WirePeripheralFeel, WirePeripheralInterpret, WirePeripheralInterpretation, WirePeripheralItem,
  WirePeripheralRequested, WirePeripheralReviewContribution, WirePeripheralScoreDetail, WirePeripherals,
} from './wire'

const HANGUL = /[가-힣]/

/**
 * 후기 한 줄. 리뷰 원문 문장(evidence_sentences, 한글)을 먼저 쓴다. observation_text 는 분석 요약이라 대부분 영어여서,
 * 한글이 들어 있을 때만 대신 쓰고 아니면 보이지 않게 한다(영어 문장을 한국어 화면에 그대로 내지 않는다).
 */
function quoteFromMembers(members: WirePeripheralReviewContribution['members']): string | null {
  for (const member of members) {
    const sentence = member.evidence_sentences?.find(text => text.trim())
    if (sentence) return sentence.trim()
  }
  const summary = members.find(member => HANGUL.test(member.observation_text))
  return summary ? summary.observation_text : null
}

function aspectsFromWire(review: { contributions: WirePeripheralReviewContribution[] } | null | undefined): PeripheralReviewAspect[] {
  return (review?.contributions ?? []).map(entry => ({
    aspectCode: entry.aspect_code,
    state: entry.evidence_state,
    positive: entry.p,
    negative: entry.n,
    mixed: entry.mixed,
    // 서버가 다수 의견 쪽에서 고른 대표 문장을 먼저 쓰고, 없으면(예전 서버) 멤버에서 찾는다.
    quote: entry.quote?.text ?? quoteFromMembers(entry.members ?? []),
    quoteDirection: entry.quote?.direction ?? null,
    dissent: Boolean(entry.dissent),
  }))
}

const scoreAxesFromWire = (detail: WirePeripheralScoreDetail | null | undefined): PeripheralScoreAxis[] =>
  (detail?.axes ?? []).map(axis => ({ axis: axis.axis, label: axis.label ?? axis.axis, value: axis.value, weight: axis.weight, points: axis.points }))

const requestedFromWire = (requested: WirePeripheralRequested[] | undefined): PeripheralRequested[] =>
  (requested ?? []).map(entry => ({
    label: entry.label, source: entry.source, type: entry.type, specChecks: entry.spec_checks ?? [],
    feelCodes: entry.feel_codes ?? [], externalAspects: entry.external_aspects ?? [],
  }))

function feelFromWire(feel: WirePeripheralFeel | null | undefined): PeripheralFeel | null {
  if (!feel) return null
  return {
    value: feel.value, basis: feel.basis, basisText: feel.basis_text, recentAuthors: feel.recent_authors ?? null,
    attributes: feel.attributes.map(attribute => ({
      code: attribute.code, label: attribute.label, text: attribute.text, state: attribute.state,
      split: attribute.split, mismatch: attribute.mismatch, good: attribute.good, bad: attribute.bad,
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
      variantId: alternative.variant_id ?? null, brand: alternative.brand ?? null, imageUrl: alternative.image_url ?? null, productUrl: alternative.product_url ?? null,
      keySpecs: alternative.key_specs ?? [], requested: requestedFromWire(alternative.requested),
      pricePosition: alternative.price_position ?? null, scoreAxes: scoreAxesFromWire(alternative.score_detail),
      feel: feelFromWire(alternative.feel),
    })),
    feel: feelFromWire(item.feel), feelNote: item.feel_note ?? null,
    keySpecs: item.key_specs ?? [], requested: requestedFromWire(item.requested),
    pricePosition: item.price_position ?? null, scoreAxes: scoreAxesFromWire(item.score_detail),
  }
}

const interpretationFromWire = (wire: WirePeripheralInterpretation): PeripheralInterpretation => ({
  kinds: wire.kinds ?? [], purposes: wire.purposes ?? [], situations: wire.situations ?? [], stated: wire.stated ?? {},
  handSize: wire.hand_size ?? null, budget: wire.budget ?? {}, budgetMin: wire.budget_min ?? {}, budgetTotal: wire.budget_total ?? null,
  emphasis: wire.emphasis ?? {}, brandLike: wire.brand_like ?? {}, brandAvoid: wire.brand_avoid ?? {}, exclude: wire.exclude ?? {},
  unrecognized: wire.unrecognized ?? [],
})

// previous 로 돌려보낼 때는 서버가 준 모양(snake_case) 그대로여야 한다. 질문(question)은 이번 턴 것이라 돌려보내지 않는다.
const interpretationToWire = (value: PeripheralInterpretation): WirePeripheralInterpretation => ({
  kinds: value.kinds, purposes: value.purposes, situations: value.situations, stated: value.stated as Record<string, string[]>,
  hand_size: value.handSize, budget: value.budget as Record<string, number>, budget_min: value.budgetMin as Record<string, number>,
  budget_total: value.budgetTotal,
  emphasis: value.emphasis as Record<string, string[]>, brand_like: value.brandLike as Record<string, string[]>,
  brand_avoid: value.brandAvoid as Record<string, string[]>, exclude: value.exclude as Record<string, string[]>,
  unrecognized: value.unrecognized,
})

/** 해석 응답(interpret 과 chat 이 같다)을 화면 모양으로 */
function interpretResultFromWire(result: WirePeripheralInterpret): PeripheralInterpretResult {
  const resolved: Partial<Record<PeripheralKind, PeripheralResolvedKind>> = {}
  for (const [kind, entry] of Object.entries(result.resolved ?? {})) {
    resolved[kind as PeripheralKind] = {
      kind: entry.kind, label: entry.label, purposes: entry.purposes ?? [],
      preferences: (entry.preferences ?? []).map(item => ({ condition: item.condition, label: item.label, sources: item.sources ?? [] })),
      filters: (entry.filters ?? []).map(item => ({ condition: item.condition, label: item.label, sources: item.sources ?? [] })),
      conflicts: entry.conflicts ?? [],
    }
  }
  return {
    interpretation: interpretationFromWire(result.interpretation), resolved,
    needsKind: result.needs_kind, source: result.source, truncated: Boolean(result.truncated),
  }
}

// 추천·채팅은 "목록(세션)"에 묶어 호출한다. PC 견적 대화 없이도 쓸 수 있어, 처음이면 빈 세션을 하나 만든다.
const ensureSession = async (sessionId?: string | null) => sessionId ?? (await request<{ list_id: string }>('POST', '/session')).list_id

export const peripherals: Api['peripherals'] = {
  async recommend(input, sessionId) {
    const id = await ensureSession(sessionId)
    // 예전 입력(purpose·priority·noise_sensitive·resolution)은 새 화면에서 보내지 않는다 — 문장 해석 결과를 그대로 싣는다.
    const body = {
      kinds: input.kinds,
      budget_max: input.budgetMax,
      purposes: input.purposes ?? [],
      situations: input.situations ?? [],
      stated: input.stated ?? {},
      kind_budget: input.kindBudget ?? {},
      kind_budget_min: input.kindBudgetMin ?? {},
      emphasis: input.emphasis ?? {},
      brand_like: input.brandLike ?? {},
      brand_avoid: input.brandAvoid ?? {},
      exclude: input.exclude ?? {},
      hand_size: input.handSize ?? null,
      pc_list_id: input.pcListId,
    }
    const result = await request<WirePeripherals>('POST', `/session/${encodeURIComponent(id)}/peripherals/recommend`, body)
    return {
      sessionId: id, status: result.status, items: result.items.map(itemFromWire), empty: result.empty,
      referencePrice: result.totals.reference_price, priceNote: result.totals.note,
      ignoredInputs: result.ignored_inputs ?? [],
      adjustChips: (result.adjust_chips ?? []).map(chip => ({ kind: chip.kind, id: chip.id, label: chip.label, add: chip.add, moved: chip.moved })),
      notices: result.notices ?? [],
    }
  },

  async interpret({ text, previous, kinds }) {
    const result = await request<WirePeripheralInterpret>('POST', '/peripherals/interpret', {
      text, previous: previous ? interpretationToWire(previous) : null, kinds: kinds && kinds.length ? kinds : null,
    })
    return interpretResultFromWire(result)
  },

  async chat({ text, previous, kinds, sessionId, pcListId }) {
    const id = await ensureSession(sessionId)
    const result = await request<WirePeripheralChat>('POST', `/session/${encodeURIComponent(id)}/peripherals/chat`, {
      text, previous: previous ? interpretationToWire(previous) : null, kinds: kinds && kinds.length ? kinds : null,
      pc_list_id: pcListId ?? null,
    })
    const { turn } = result
    return {
      ...interpretResultFromWire(result),
      sessionId: id,
      turn: {
        newConditions: turn.new_conditions ?? [], notReflected: turn.not_reflected ?? [], notes: turn.notes ?? [],
        answer: turn.answer, command: turn.command ?? null, removedConditions: turn.removed_conditions ?? [], reset: Boolean(turn.reset),
        reply: turn.reply, chips: turn.chips ?? [], resultChips: turn.result_chips ?? [],
      },
    }
  },
}
