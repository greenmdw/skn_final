// 주변기기 채팅의 세션(목록) — 다른 화면에 갔다 와도 같은 대화를 이어 가도록 브라우저에 마지막 세션 id 를 둔다(QA 10/15 #19·#30).
// 대화 자체는 서버에 저장된다(GET /session/{id}/peripherals/messages). 이 값이 없거나 읽지 못해도 새 대화로 시작할 뿐이다.
const KEY = 'truefit.peripherals.session'

export function rememberedPeripheralSession(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function rememberPeripheralSession(sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(KEY, sessionId)
    else localStorage.removeItem(KEY)
  } catch { /* 보관 실패는 무시 — 돌아왔을 때 새 대화로 시작한다 */ }
}

/** 대화 내역에서 주변기기 대화를 열 때의 주소와 상태(같은 화면에서 다른 대화를 열어도 화면을 새로 그리게 key 를 준다) */
export const peripheralConversationPath = (sessionId: string) => `/peripherals?session=${encodeURIComponent(sessionId)}`
export const peripheralConversationState = (sessionId: string) => ({ state: { plannerMode: 'peripherals', newConversationKey: `session:${sessionId}` } })
