import { createContext, useContext } from 'react'
import type { ChatChoice, ChatMessage, CheckDraft, PartKey, PlanState, SavedSetup } from './types'

export interface PlanContextValue {
  state: PlanState
  checkDraft: CheckDraft
  updateCheckDraft: (patch: Partial<CheckDraft>) => void
  messages: ChatMessage[]
  /** 서버가 조건 대화 한 턴을 처리하는 중 */
  busy: boolean
  starterHidden: boolean
  analyzingIndex: number
  customHeading: { title: string; desc: string } | null
  handleInput: (text: string) => void
  handleChoice: (choice: ChatChoice) => void
  startAnalysis: () => void
  /** 남은 예산으로 성능을 올리려고 우선순위를 '성능 우선'으로 바꿔 다시 추천받는다(서버 인터뷰 세션이 있는 새 구성 전용). */
  retryWithPerformance: () => void
  /** 브라우저에 남은 옛 구성을 서버의 최신 결과로 조용히 다시 읽는다(실패하면 그대로 둔다) */
  refreshPlan: () => void
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
