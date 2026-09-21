import type { Api } from '../types'
import { auth } from './auth'
import { chat } from './chat'
import { checks } from './checks'
import { plans } from './plans'
import { setups } from './setups'

// 백엔드에 연결한 것: 로그인·가입, 추천 구성, 구성 뒤의 후속 질문(부품 교체 포함), 확정·리포트·삭제.
// 견적 점검의 업그레이드 제안은 서버의 업그레이드 추천을 그대로 돌린 것이다(성능 변화 폭·소비전력은 서버가 계산하지 않는다).
// 아직 목업인 것: 인터뷰 문답(chat 의 intent·performance)과 점검 화면의 대화(reviewReply) — 백엔드에 해당 API 가 없다.
export const httpApi: Api = { auth, plans, setups, chat, checks }
