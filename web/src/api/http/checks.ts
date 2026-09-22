import type { Api } from '../types'
import { ApiError } from '../types'
import { request } from './client'
import { plans } from './plans'
import { backendSlotFromRowPart, reviewRowsFromWire, suggestionFromPlan } from './mapping'
import type { WireOwnedPartsPreviewOut } from './wire'

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
    const translated: Record<string, string> = {}
    for (const [part, value] of Object.entries(currentSpecs ?? {})) {
      const slot = backendSlotFromRowPart(part)
      if (slot && value.trim()) translated[slot] = value
    }
    if (Object.keys(translated).length === 0 && !text?.trim() && !imageDataUrl) return []
    const result = await request<WireOwnedPartsPreviewOut>('POST', '/pc/owned-parts/preview', {
      current_specs: translated, text: text?.trim() || undefined, image_data_url: imageDataUrl || undefined,
    })
    return reviewRowsFromWire(result.rows)
  },
}
