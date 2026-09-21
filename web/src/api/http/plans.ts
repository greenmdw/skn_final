import type { Api } from '../types'
import { ApiError } from '../types'
import { request, sleep } from './client'
import {
  currentSpecsFromRows, planFromResult, priorityFromText, purposeFromText, resolutionFromText, upgradePartsFromText,
} from './mapping'
import type { WireResult, WireSessionState } from './wire'

const POLL_MS = 700
const RESULT_TIMEOUT_MS = 60_000
// 부품·가격이 먼저 확정되고 설명 문장(LLM)은 뒤따라 채워진다. 문장이 늦어도 이만큼만 기다리고 보여준다.
const EXPLANATION_GRACE_MS = 20_000

async function waitForResult(listId: string): Promise<WireResult> {
  const startedAt = Date.now()
  let graceUntil = 0
  for (;;) {
    let result: WireResult | null = null
    try {
      result = await request<WireResult>('GET', `/session/${listId}/result`)
    } catch (error) {
      // 실행을 접수한 직후에는 결과 행이 아직 없을 수 있다 — 그 경우만 다시 시도한다.
      if (!(error instanceof ApiError && error.code === 'not_found')) throw error
    }
    if (result?.status === 'failed') {
      throw new ApiError(result.error?.message || '추천을 만들지 못했습니다.', result.error?.code ?? 'RECOMMEND_FAILED')
    }
    if (result?.status === 'done') {
      if (result.explanation.status !== 'pending') return result
      if (!graceUntil) graceUntil = Date.now() + EXPLANATION_GRACE_MS
      if (Date.now() > graceUntil) return result
    }
    if (Date.now() - startedAt > RESULT_TIMEOUT_MS) {
      throw new ApiError('추천이 오래 걸리고 있습니다. 잠시 후 다시 시도해주세요.', 'TIMEOUT')
    }
    await sleep(POLL_MS)
  }
}

// 업그레이드에서 유지하는 부품의 플랫폼·RAM 종류·파워 용량은 조건부 칩 질문으로 묻는다. 이 화면에는 그 질문을 받을 자리가 없어
// "모르겠어요"(unknown)로 답한다 — 추천은 진행되고, 결과에 "확인 못 함"으로 안내된다(실패로 단정하지 않는다).
async function answerRemainingQuestions(session: string): Promise<void> {
  for (let turn = 0; turn < 6; turn++) {
    const state = await request<WireSessionState>('GET', session)
    const question = state.next_question
    if (state.can_recommend || !question) return
    if (!question.options.some(option => option.value === 'unknown')) return
    await request('POST', session + '/answer', { question_id: question.id, selected: ['unknown'] })
  }
}

// 추천을 요청할 때마다 새 목록(세션)을 만든다. 그 list_id 가 화면의 plan.id 가 되고, 확정도 같은 id 로 한다.
export const plans: Api['plans'] = {
  async recommend({ mode, budget, conditions, checkSnapshot }) {
    if (budget === null) throw new ApiError('예산을 입력해주세요. 예산 안에서 구성을 추천합니다.', 'BUDGET_REQUIRED')
    const { list_id: listId } = await request<{ list_id: string }>('POST', '/session')
    const session = '/session/' + listId
    await request('POST', session + '/category', { category: 'computer', mode: mode === 'upgrade' ? 'upgrade' : 'build' })

    const intent = conditions.intent
    const slots: Record<string, unknown> = {
      purpose: purposeFromText(intent),
      budget_max: budget,
      priority: priorityFromText(mode === 'upgrade' ? intent : conditions.quiet),
    }
    const resolution = resolutionFromText(conditions.performance)
    if (resolution) slots.resolution = resolution
    if (mode === 'upgrade') {
      slots.upgrade_parts = upgradePartsFromText(intent)
      const specs = checkSnapshot ? currentSpecsFromRows(checkSnapshot.rows) : {}
      if (Object.keys(specs).length) slots.current_specs = specs
    }
    for (const [field, value] of Object.entries(slots)) await request('PATCH', session + '/slot', { field, value })
    await answerRemainingQuestions(session)

    await request('POST', session + '/recommend', {})
    const plan = planFromResult(await waitForResult(listId), { mode, budget, conditions, checkSnapshot })
    if (!plan.items.length) throw new ApiError('추천 결과에 부품이 없습니다. 조건을 바꿔 다시 시도해주세요.', 'EMPTY_RESULT')
    return plan
  },
}
