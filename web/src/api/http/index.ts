import type { Api } from '../types'
import { mockApi } from '../mock'
import { auth } from './auth'
import { plans } from './plans'
import { setups } from './setups'

// 백엔드에 연결한 것: 로그인·가입, 추천 구성, 확정·리포트·삭제.
// 아직 목업인 것: 채팅 답변(chat)과 견적 점검 제안(checks) — 백엔드에 해당 API 가 없다.
export const httpApi: Api = { auth, plans, setups, chat: mockApi.chat, checks: mockApi.checks }
