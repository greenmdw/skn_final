import type { Api, ConditionTurnResult } from '../types'
import { request } from './client'
import { budgetWarningFromWire, choicesFromWire, fieldsFromWire, replyTextFromWire } from './mapping'
import { asSessionGone, isNotFound } from './session'
import type { WireConditionState, WirePreviousLookup } from './wire'

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
    budgetWarning: budgetWarningFromWire(state.budget_warning),
  }
}

async function sendTo(id: string, text: string): Promise<ConditionTurnResult> {
  const state = await request<WireConditionState>('POST', '/session/' + id + '/message', { text })
  return toResult(id, state)
}

export const conditions: Api['conditions'] = {
  async send(sessionId, text) {
    if (!sessionId) return sendTo(await createSession(), text)
    try {
      return await sendTo(sessionId, text)
    } catch (error) {
      // 저장돼 있던 세션이 없어졌거나 내 것이 아니면, 새 세션을 만들어 이 말부터 다시 시작한다.
      if (!isNotFound(error)) throw error
      return sendTo(await createSession(), text)
    }
  },
  async answer(sessionId, questionId, selected) {
    try {
      const state = await request<WireConditionState>('POST', '/session/' + sessionId + '/answer', { question_id: questionId, selected })
      return toResult(sessionId, state)
    } catch (error) { throw asSessionGone(error) }
  },
  async patch(sessionId, field, value) {
    try {
      const state = await request<WireConditionState>('PATCH', '/session/' + sessionId + '/slot', { field, value })
      return toResult(sessionId, state)
    } catch (error) { throw asSessionGone(error) }
  },
  async exists(sessionId) {
    try {
      await request('GET', '/session/' + sessionId)
      return true
    } catch (error) {
      return !isNotFound(error)   // 네트워크 오류 등은 "없다"고 단정하지 않는다
    }
  },
  async previous() {
    const { previous } = await request<WirePreviousLookup>('GET', '/session/previous?category=computer&mode=build')
    return previous ? { listId: previous.list_id, summary: previous.summary } : null
  },
  async resume(sessionId, fromListId) {
    const resumeIn = async (id: string) =>
      toResult(id, await request<WireConditionState>('POST', '/session/' + id + '/resume', { from_list_id: fromListId }))
    if (!sessionId) return resumeIn(await createSession())
    try {
      return await resumeIn(sessionId)
    } catch (error) {
      // send 와 같게: 저장돼 있던 세션이 없어졌거나 내 것이 아니면 새 세션에서 이어간다.
      if (!isNotFound(error)) throw error
      return resumeIn(await createSession())
    }
  },
}
