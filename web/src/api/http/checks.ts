import type { Api } from '../types'
import { ApiError } from '../types'
import { plans } from './plans'
import { suggestionFromPlan } from './mapping'

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
}
