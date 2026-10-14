import type { Api } from '../types'
import { request } from './client'
import type { WireReviewSummary } from './wire'

export const reviews: Api['reviews'] = {
  async summary(productKey) {
    const wire = await request<WireReviewSummary>('GET', `/reviews/summary/${encodeURIComponent(productKey)}`)
    return {
      productKey: wire.product_key,
      productName: wire.product_name ?? null,
      totalCount: wire.total_count ?? 0,
      ratingRaw: wire.rating_raw ?? null,
      ratingRefined: wire.rating_refined ?? null,
      excludedCount: wire.excluded_count ?? null,
      excludedRatio: wire.excluded_ratio ?? null,
      riskEvidence: wire.product_manipulation_risk?.evidence ?? [],
      status: wire.status === 'ready' ? 'ready' : 'unavailable',
      dataNotice: wire.data_notice,
    }
  },
}
