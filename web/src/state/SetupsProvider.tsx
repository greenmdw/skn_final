import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { SavedSetup } from './types'
import { ApiError, api, errorMessage } from '../api'
import { SetupsContext, type SetupsContextValue } from './SetupsContext'
import { useAuthUser } from './authStore'

export function SetupsProvider({ children }: { children: ReactNode }) {
  const [savedSetups, setSavedSetups] = useState<SavedSetup[]>([])
  const [loading, setLoading] = useState(true)
  const [storageError, setStorageError] = useState('')
  const [authRequired, setAuthRequired] = useState(false)
  const user = useAuthUser()

  // 로그인·로그아웃으로 사용자가 바뀌면 그 사용자의 확정 목록을 다시 불러온다. 확정 뒤에도 다시 읽는다(reload) —
  // 같은 목록에 견적서가 늘면 번호·개수는 서버만 안다.
  const [reloadKey, setReloadKey] = useState(0)
  const reload = useCallback(() => setReloadKey(n => n + 1), [])
  const loadedFor = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    let active = true
    setLoading(true)
    const who = user?.email ?? null
    if (loadedFor.current !== who) setSavedSetups([])   // 다른 사용자의 목록을 잠깐이라도 보이지 않는다
    loadedFor.current = who
    api.setups.list()
      .then(result => { if (active) { setSavedSetups(result.data); setStorageError(result.warning) } })
      .catch(error => { if (active) setStorageError(errorMessage(error, '저장 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.email, reloadKey])

  const addSetup = useCallback(async (setup: SavedSetup) => {
    try {
      const saved = await api.setups.save(setup)
      setSavedSetups(prev => [saved, ...prev.filter(s => s.id !== saved.id)])
      setStorageError('')
      setAuthRequired(false)
      reload()
      return true
    } catch (error) {
      setStorageError(errorMessage(error, '저장하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      setAuthRequired(error instanceof ApiError && error.code === 'AUTH_REQUIRED')
      return false
    }
  }, [reload])
  const removeSetup = useCallback(async (id: string) => {
    try {
      await api.setups.remove(id)
      setSavedSetups(prev => prev.filter(s => s.id !== id))
      setStorageError('')
      return true
    } catch (error) {
      setStorageError(errorMessage(error, '삭제하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
  }, [])

  const value = useMemo<SetupsContextValue>(() => ({ savedSetups, loading, storageError, authRequired, addSetup, removeSetup, reload }), [savedSetups, loading, storageError, authRequired, addSetup, removeSetup, reload])
  return <SetupsContext.Provider value={value}>{children}</SetupsContext.Provider>
}
