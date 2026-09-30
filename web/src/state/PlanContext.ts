import { createContext, useContext } from 'react'
import type { AlternativeOption, ItemPatch } from '../api/types'
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
  /** 저장돼 있던 작업의 서버 세션이 아직 유효한지 확인하고, 없으면(로그아웃·다른 계정) 작업을 비우고 새로 시작한다 */
  checkSession: () => void
  /** 이 부품 자리의 대안 목록을 서버에서 가져온다 */
  loadAlternatives: (itemId: string) => Promise<AlternativeOption[]>
  /** 대안으로 교체한다. 성공하면 true (실패하면 안내 메시지를 띄운다) */
  swapItem: (itemId: string, candidateId: string) => Promise<boolean>
  /** 수량·구매 시점을 바꾼다. 성공하면 true */
  updateItem: (itemId: string, patch: ItemPatch) => Promise<boolean>
  selectPart: (key: PartKey) => void
  setBudget: (budget: number | null) => void
  setDesk: (width: number, depth: number, height: number) => boolean
  resetPlan: () => void
  loadFromSavedSetup: (setup: SavedSetup) => void
  startUpgradeMode: () => Promise<boolean>
  /** 지난 대화를 서버에서 읽어 연다. hasResult 면 추천 결과까지. 열린 화면('plan'|'conditions'), 실패하면 null */
  openConversation: (listId: string, hasResult: boolean) => Promise<'plan' | 'conditions' | null>
  /** 확정한 견적의 조건으로 새 견적서를 시작한다(조건 대화로). 성공하면 true */
  startNewRevision: (listId: string) => Promise<boolean>
  reviseSetup: (listId: string) => Promise<'plan' | 'conditions' | null>
}
export const PlanContext = createContext<PlanContextValue | null>(null)

export function usePlan() {
  const ctx = useContext(PlanContext)
  if (!ctx) throw new Error('usePlan must be used within PlanProvider')
  return ctx
}
