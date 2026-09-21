import type { Api } from '../types'
import { mockApi } from '../mock'
import { request } from './client'
import { partExplanation, planFromResult, wantsPartExplanation } from './mapping'
import type { WireResult } from './wire'

const MAX_LENGTH = 300   // 서버(ResultMessageIn)가 받는 최대 글자 수

// 인터뷰 단계(목적·성능 질문)는 화면 안의 정해진 문답이다 — 서버는 조건을 추천 요청 때 한 번에 받는다.
// 구성이 나온 뒤의 후속 질문만 서버(POST /session/{id}/result-message)가 답하고, 부품을 바꾸면 바뀐 구성을 함께 돌려준다.
export const chat: Api['chat'] = {
  async reply(request_) {
    const { topic, text, plan, selectedPart } = request_
    if (topic !== 'followup' || !plan) return mockApi.chat.reply(request_)
    const part = plan.items.find(item => item.key === selectedPart)
    if (part && wantsPartExplanation(text)) return { text: partExplanation(part) }
    if (text.length > MAX_LENGTH) return { text: `메시지는 ${MAX_LENGTH}자 이내로 입력해주세요.` }
    const { reply, result } = await request<{ reply: string; result: WireResult }>('POST', '/session/' + plan.id + '/result-message', { text })
    const next = planFromResult(result, { mode: plan.mode, budget: plan.budget, conditions: plan.conditions, checkSnapshot: plan.checkSnapshot })
    return { text: reply, plan: next }
  },
  reviewReply: mockApi.chat.reviewReply,
}
