import type { Api } from '../types'
import { delay } from './delay'

// 목업: 인터뷰는 화면(PlanProvider)이 정해진 문답으로 직접 진행하고 이 모듈은 부르지 않는다 — 여기 있는 건 Api
// 타입을 맞추기 위한 자리표시자다. 실제로 호출되면(테스트 등) 아무 조건도 채우지 않은 응답을 돌려준다.
export const conditions: Api['conditions'] = {
  async send(sessionId) {
    await delay(200)
    return { sessionId: sessionId ?? 'mock-session', reply: '', fields: [], canRecommend: false }
  },
  async patch(sessionId) {
    await delay(100)
    return { sessionId, reply: '', fields: [], canRecommend: false }
  },
}
