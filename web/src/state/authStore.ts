import { useSyncExternalStore } from 'react'
import { api, isMockApi, type AuthUser } from '../api'

// 로그인한 사용자를 화면 어디서나 읽기 위한 작은 저장소. 서버가 쿠키로 세션을 들고 있어서 화면은 "지금 누구인지"만 기억한다.
// 목업은 로그인 화면이 입력값으로 사용자를 만들어 넣고(새로고침하면 사라진다), 서버 연결 모드는 시작할 때 /auth/me 로 확인한다.
let current: AuthUser | null = null
const listeners = new Set<() => void>()

function publish(user: AuthUser | null) {
  current = user
  listeners.forEach(listener => listener())
}

export const setAuthUser = (user: AuthUser | null) => publish(user)

export async function refreshAuthUser(): Promise<void> {
  if (isMockApi) return
  try { publish(await api.auth.me()) } catch { publish(null) }
}

export async function logout(): Promise<void> {
  try { await api.auth.logout() } finally { publish(null) }
}

export function useAuthUser(): AuthUser | null {
  return useSyncExternalStore(
    listener => { listeners.add(listener); return () => { listeners.delete(listener) } },
    () => current,
  )
}
