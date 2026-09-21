import type { Api } from '../types'
import type { CurrentPlan, Part, PartKey, PlanItem } from '../../state/types'
import { parseWon } from '../../utils/format'
import { newId } from '../../utils/id'
import { delay } from './delay'
import { fakeParts } from './data/fakeParts'
import { upgradePart } from './data/upgradePart'

function item(key: PartKey, part: Part): PlanItem {
  return { ...part, id: key, key, price: parseWon(part.price) }
}

// 목업: 요청 내용과 관계없이 고정된 샘플 구성을 돌려줍니다. 실제 서비스에서는 추천 API로 교체됩니다.
export const plans: Api['plans'] = {
  async recommend({ mode, budget, conditions, checkSnapshot }) {
    await delay(mode === 'new' ? 2600 : 0)
    const items = mode === 'upgrade'
      ? [item('gpu', { ...upgradePart, fit: '샘플 업그레이드 후보입니다. 실제 성능과 호환성은 아직 분석되지 않았습니다.', reasonTitle: 'GPU 업그레이드 예시', tags: ['샘플', '호환성 확인 필요'] })]
      : (Object.entries(fakeParts) as [PartKey, Part][]).map(([key, part]) => item(key, part))
    if (mode === 'new') items.push({
      id: 'other', key: null, type: '기타 부품', name: '기타 부품 예산 (미선정)', price: 250000,
      meta: '메인보드·케이스·파워 등 별도 선정 필요', source: '샘플 예산', action: '별도 선정', actionClass: '',
      score: '', fit: '구체적인 제품이 선정되지 않은 예산 항목입니다. 실구매 전 제품과 가격 확인이 필요합니다.',
      reasonTitle: '추가 부품 예산', tags: ['미선정'], rating: '-', reviews: '없음', label: '기타',
    })
    return {
      id: newId(), mode, items, budget, conditions: { ...conditions },
      checkSnapshot: checkSnapshot ? structuredClone(checkSnapshot) : null,
    } satisfies CurrentPlan
  },
}
