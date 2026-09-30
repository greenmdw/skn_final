import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

// "저장한 견적" 슬라이드 패널을 어느 화면에서든 열고 닫기 위한 작은 상태.
interface DrawerValue { savedOpen: boolean; openSaved: () => void; closeSaved: () => void }
const DrawerContext = createContext<DrawerValue | null>(null)

export function DrawerProvider({ children }: { children: ReactNode }) {
  const [savedOpen, setSavedOpen] = useState(false)
  const value = useMemo<DrawerValue>(() => ({
    savedOpen, openSaved: () => setSavedOpen(true), closeSaved: () => setSavedOpen(false),
  }), [savedOpen])
  return <DrawerContext.Provider value={value}>{children}</DrawerContext.Provider>
}

export function useDrawer() {
  const ctx = useContext(DrawerContext)
  if (!ctx) throw new Error('useDrawer must be used within DrawerProvider')
  return ctx
}
