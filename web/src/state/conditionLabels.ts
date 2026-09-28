import { isMockApi } from '../api'

// plan.conditions.quiet / state.quiet 는 목업에서는 세 번째 질문(소음 선호)의 답이고, 실서버에서는 서버가 정한
// 우선순위(성능 우선 · 가성비 · 저소음)다. 같은 값을 "소음"이라고 부르면 "소음: 가성비"처럼 읽혀서 화면마다 이 이름을 쓴다.
export const QUIET_LABEL = isMockApi ? '소음' : '우선순위'
export const QUIET_CARD_LABEL = isMockApi ? '소음 선호' : '우선순위'
export const QUIET_CARD_NOTE = isMockApi ? '작업 환경' : '추천 기준'
