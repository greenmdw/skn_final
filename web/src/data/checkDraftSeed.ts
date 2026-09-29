import type { CheckDraft } from '../state/types'

// 견적 점검 초안. 견적 점검 화면은 아직 개발 전이라 비어 있는 상태로 시작한다(가짜 예시 부품을 넣지 않는다).
export function createCheckDraft(): CheckDraft {
  return { question: '', budget: '', rows: [] }
}
