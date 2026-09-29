import { useSyncExternalStore } from 'react'
import { api, type AuthUser } from '../api'

// 로그인한 사용자를 화면 어디서나 읽기 위한 작은 저장소. 서버가 쿠키로 세션을 들고 있어서 화면은 "지금 누구인지"만 기억한다.
// 시작할 때 /auth/me 로 확인한다.
let current: AuthUser | null = null
const listeners = new Set<() => void>()
const logoutListeners = new Set<() => void>()

/** 사용자가 로그아웃했을 때(버튼) 불리는 콜백을 등록한다. 작업 중이던 구성처럼 계정에 묶인 상태를 비우는 데 쓴다. */
export function onLogout(callback: () => void): () => void {
  logoutListeners.add(callback)
  return () => { logoutListeners.delete(callback) }
}

function publish(user: AuthUser | null) {
  current = user
  listeners.forEach(listener => listener())
}

export const setAuthUser = (user: AuthUser | null) => publish(user)

export async function refreshAuthUser(): Promise<void> {
  try { publish(await api.auth.me()) } catch { publish(null) }
}

export async function logout(): Promise<void> {
  try { await api.auth.logout() } finally {
    publish(null)
    logoutListeners.forEach(callback => callback())
  }
}

export function useAuthUser(): AuthUser | null {
  return useSyncExternalStore(
    listener => { listeners.add(listener); return () => { listeners.delete(listener) } },
    () => current,
  )
}
