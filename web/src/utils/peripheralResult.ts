import type {
  PeripheralFeel, PeripheralFeelQuote, PeripheralItem, PeripheralKeySpec, PeripheralPricePosition, PeripheralRequested,
  PeripheralReviewAspect, PeripheralScoreAxis,
} from '../api'
import type { PeripheralSnapshot } from '../state/types'
import { aspectLabel } from './peripherals'

/**
 * 추천 결과 화면(큰 카드·다른 선택지)이 한 제품을 같은 모양으로 다루기 위한 값.
 * 1위와 대안은 서버가 같은 정보(스펙 한 줄·요청 항목·점수 축·체감 근거)를 주므로 어느 쪽이든 큰 카드로 올릴 수 있다.
 * 서버에 없는 값은 비어 있고, 화면은 그 부분을 그리지 않는다.
 */
export interface CandidateView {
  /** 서버 순위(1위 = 1) */
  rank: number
  name: string
  brand: string
  price: number
  imageUrl: string | null
  productUrl: string | null
  variantId: string | null
  keySpecs: PeripheralKeySpec[]
  requested: PeripheralRequested[]
  pricePosition: PeripheralPricePosition | null
  scoreAxes: PeripheralScoreAxis[]
  reviewAspects: PeripheralReviewAspect[]
  feel: PeripheralFeel | null
}

/** 순위 순서의 후보 목록: 1위, 그다음 서버가 준 다른 선택지 */
export function candidateViews(item: PeripheralItem): CandidateView[] {
  const first: CandidateView = {
    rank: 1, name: item.name, brand: item.brand, price: item.price, imageUrl: item.imageUrl, productUrl: item.productUrl,
    variantId: item.variantId, keySpecs: item.keySpecs, requested: item.requested, pricePosition: item.pricePosition,
    scoreAxes: item.scoreAxes, reviewAspects: item.reviewAspects, feel: item.feel,
  }
  const others = item.alternatives.map((alternative, index): CandidateView => ({
    rank: index + 2, name: alternative.name, brand: alternative.brand ?? item.brand, price: alternative.price,
    imageUrl: alternative.imageUrl ?? null, productUrl: alternative.productUrl ?? null, variantId: alternative.variantId ?? null,
    keySpecs: alternative.keySpecs, requested: alternative.requested, pricePosition: alternative.pricePosition,
    scoreAxes: alternative.scoreAxes, reviewAspects: alternative.reviewAspects, feel: alternative.feel,
  }))
  return [first, ...others]
}

/** `base` 와 값이 다른 스펙만: "주사율 75Hz (지금 165Hz)". 값이 없는 쪽이 있으면 비교하지 않는다. */
export function specDifferences(view: CandidateView, base: CandidateView): { key: string; label: string; value: string; baseValue: string }[] {
  const baseValues = new Map(base.keySpecs.map(spec => [spec.key, spec.value]))
  return view.keySpecs
    .filter(spec => baseValues.has(spec.key) && baseValues.get(spec.key) !== spec.value)
    .map(spec => ({ key: spec.key, label: spec.label, value: spec.value, baseValue: baseValues.get(spec.key) as string }))
}

/** 점수 기여가 큰 축 위쪽 `limit` 개(막대와 "N점 · 비중 N%"로 보인다) */
export const topAxes = (axes: PeripheralScoreAxis[], limit = 3) => [...axes].sort((a, b) => b.points - a.points).slice(0, limit)

export interface RequestedEvidence {
  label: string
  /** 사용자가 말하지 않고 PC 견적 용도에서 온 항목 — "요청하신"이라고 하지 않는다 */
  fromPc: boolean
  specChecks: PeripheralRequested['specChecks']
  quotes: PeripheralFeelQuote[]
  /** 사용기 집계 문구(서버 문구 그대로). few 는 같은 조건의 글이 적어 참고용일 때 */
  note: { text: string; few: boolean } | null
  /** 사용기가 없을 때 외부 리뷰 근거 */
  external: { label: string; positive: number; total: number; quote: string | null; dissent: boolean } | null
}

/**
 * 사용자가 말한 항목 하나의 근거. 사용기 → 외부 리뷰 순으로 있는 것만 채우고, 보일 근거가 하나도 없으면 null
 * (빈 박스나 "근거 없음" 문구를 그리지 않는다).
 */
export function requestedEvidence(view: CandidateView, requested: PeripheralRequested, maxQuotes: number): RequestedEvidence | null {
  const attributes = requested.feelCodes
    .map(code => view.feel?.attributes.find(attribute => attribute.code === code))
    .filter((attribute): attribute is NonNullable<typeof attribute> => Boolean(attribute))
  const quotes = attributes.flatMap(attribute => attribute.quotes).slice(0, maxQuotes)
  const community = attributes.find(attribute => attribute.state !== 'external_only' && attribute.text)
  const note = community ? { text: community.text, few: community.state === 'few_same_condition' } : null

  let external: RequestedEvidence['external'] = null
  if (!quotes.length && !note) {
    const aspects = requested.externalAspects
      .map(code => view.reviewAspects.find(aspect => aspect.aspectCode === code))
      .filter((aspect): aspect is PeripheralReviewAspect => Boolean(aspect))
      .map(aspect => ({ aspect, total: aspect.positive + aspect.negative + aspect.mixed }))
      .filter(entry => entry.total > 0)
      .sort((a, b) => b.total - a.total)
    const best = aspects[0]
    if (best) {
      external = {
        label: aspectLabel(best.aspect.aspectCode), positive: best.aspect.positive, total: best.total,
        quote: best.aspect.quote, dissent: Boolean(best.aspect.dissent),
      }
    }
  }
  if (!requested.specChecks.length && !quotes.length && !note && !external) return null
  return { label: requested.label, fromPc: requested.source === 'pc_purpose', specChecks: requested.specChecks, quotes, note, external }
}

/** 확정할 때 저장할 설명: 지금 큰 카드에 올린 제품(`chosenName`, null 이면 1위)이 화면에 보이던 그대로. */
export function snapshotOf(item: PeripheralItem, chosenName: string | null, sessionId?: string | null): PeripheralSnapshot {
  const views = candidateViews(item)
  const hero = views.find(view => view.name === chosenName) ?? views[0]
  return {
    // 확정한 견적에서 불러온 카드를 다시 확정해도 처음 순위를 잃지 않는다(불러온 카드엔 다른 선택지가 없어 hero.rank 가 1이다)
    v: 1, rank: hero.rank === 1 && item.savedRank ? item.savedRank : hero.rank, keySpecs: hero.keySpecs, requested: hero.requested, pricePosition: hero.pricePosition,
    scoreAxes: hero.scoreAxes, feel: hero.feel, reviewAspects: hero.reviewAspects,
    // 조건 충족 태그는 1위 카드에만 있다
    requirement: hero.rank === 1 ? item.requirement : [],
    ...(sessionId ? { sessionId } : {}),
  }
}

/** 저장해 둔 설명으로 불러온 카드를 채운다. 설명이 없으면(예전 견적서) 이름·가격만 있는 카드 그대로다. */
export function withSnapshot<T extends Pick<PeripheralItem, 'keySpecs' | 'requested' | 'pricePosition' | 'scoreAxes' | 'feel' | 'reviewAspects' | 'requirement'>>(
  item: T, view: PeripheralSnapshot | null | undefined,
): T {
  if (!view) return item
  return {
    ...item, keySpecs: view.keySpecs, requested: view.requested, pricePosition: view.pricePosition, scoreAxes: view.scoreAxes,
    feel: view.feel, reviewAspects: view.reviewAspects, requirement: view.requirement,
    ...(view.rank > 1 ? { savedRank: view.rank } : {}),
  }
}
