/** 로그인·가입 뒤에 돌아갈 화면(?next=). 같은 사이트의 경로(/ 로 시작, // 나 \ 제외)만 받는다 — 열린 리다이렉트를 막는다. */
export function safeNext(search: string): string | null {
  const value = new URLSearchParams(search).get('next')
  return value && /^\/(?![/\\])/.test(value) ? value : null
}
