import type { CheckDraft, PlanState } from './types'
import { isCheckDraft, isPlanState, object } from './validators'

export const WORKSPACE_KEY = 'truefit.workspace.v1'

export function readWorkspace(): { state: PlanState; checkDraft: CheckDraft } | null {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(WORKSPACE_KEY) || 'null')
    if (!object(data) || !object(data.state) || !isCheckDraft(data.checkDraft)) return null
    if (!isPlanState(data.state)) return null
    return { state: data.state.stage === 3 ? { ...data.state, stage: 2, currentPlan: null } : data.state, checkDraft: data.checkDraft }
  } catch { return null }
}
