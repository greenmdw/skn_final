import { createContext, useContext } from 'react'
import type { ChatMessage, CheckDraft, PartKey, PlanState, SavedSetup } from './types'

export interface PlanContextValue {
  state: PlanState
  checkDraft: CheckDraft
  updateCheckDraft: (patch: Partial<CheckDraft>) => void
  messages: ChatMessage[]
  starterHidden: boolean
  analyzingIndex: number
  customHeading: { title: string; desc: string } | null
  handleInput: (text: string) => void
  handleChoice: (value: string) => void
  startAnalysis: () => void
  selectPart: (key: PartKey) => void
  setBudget: (budget: number | null) => void
  setDesk: (width: number, depth: number, height: number) => boolean
  resetPlan: () => void
  loadFromSavedSetup: (setup: SavedSetup) => void
  startUpgradeMode: () => Promise<boolean>
}
export const PlanContext = createContext<PlanContextValue | null>(null)

export function usePlan() {
  const ctx = useContext(PlanContext)
  if (!ctx) throw new Error('usePlan must be used within PlanProvider')
  return ctx
}
