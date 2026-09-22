import type { Api, ConditionTurnResult } from '../types'
import { request } from './client'
import { choicesFromWire, fieldsFromWire, replyTextFromWire } from './mapping'
import type { WireConditionState } from './wire'

// 인터뷰(용도·예산·우선순위 등)를 서버의 조건 세션에 연결한다. 서버는 조건 추출 에이전트(LLM, CONDITIONS_AGENT=1일 때)가
// 있으면 그걸로, 없으면 규칙 추출(slot_rules)로 자유 문장에서 값을 뽑는다 — 화면은 결과만 반영한다(§D-3 "판정은 코드, LLM은 서술").
// 새 PC 인터뷰만 여기로 온다. 업그레이드 점검(견적 점검 화면)은 별도 화면·계약이라 이 세션을 쓰지 않는다.

async function createSession(): Promise<string> {
  const { list_id: listId } = await request<{ list_id: string }>('POST', '/session')
  await request('POST', '/session/' + listId + '/category', { category: 'computer', mode: 'build' })
  return listId
}

function toResult(sessionId: string, state: WireConditionState): ConditionTurnResult {
  return {
    sessionId,
    reply: replyTextFromWire(state),
    fields: fieldsFromWire(state.fields),
    choices: choicesFromWire(state.next_question),
    canRecommend: state.can_recommend,
  }
}

export const conditions: Api['conditions'] = {
  async send(sessionId, text) {
    const id = sessionId ?? await createSession()
    const state = await request<WireConditionState>('POST', '/session/' + id + '/message', { text })
    return toResult(id, state)
  },
  async patch(sessionId, field, value) {
    const state = await request<WireConditionState>('PATCH', '/session/' + sessionId + '/slot', { field, value })
    return toResult(sessionId, state)
  },
}
