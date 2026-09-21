import { createContext, useContext } from 'react'
import type { SavedSetup } from './types'

export interface SetupsContextValue {
  savedSetups: SavedSetup[]
  /** 저장 목록을 처음 불러오는 중이면 true */
  loading: boolean
  storageError: string
  /** 마지막 저장이 로그인 부재로 거절됐으면 true — 확정 화면이 로그인 버튼을 보인다 */
  authRequired: boolean
  addSetup: (setup: SavedSetup) => Promise<boolean>
  removeSetup: (id: string) => Promise<boolean>
}
export const SetupsContext = createContext<SetupsContextValue | null>(null)

export function useSetups() {
  const ctx = useContext(SetupsContext)
  if (!ctx) throw new Error('useSetups must be used within SetupsProvider')
  return ctx
}
