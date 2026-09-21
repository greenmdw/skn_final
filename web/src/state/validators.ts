import type { CheckDraft, CurrentPlan, DeskState, PlanState, SavedSetup } from './types'

// 브라우저 저장소(localStorage)에서 읽은 값이 기대한 모양인지 검사하는 타입 가드입니다.
export const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string'
const amount = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 100000000
export const budget = (value: unknown) => value === null || amount(value)
const keys = ['cpu', 'gpu', 'ram', 'ssd', 'monitor', 'board', 'psu', 'case', 'cooler']

export function isCheckDraft(value: unknown): value is CheckDraft {
  return object(value) && text(value.question) && text(value.budget) && Array.isArray(value.rows) && value.rows.every(row =>
    object(row) && ['part', 'original', 'originalNote', 'matched', 'matchedNote', 'stateLabel'].every(key => text(row[key])) && (row.state === 'ok' || row.state === 'warn'))
}
export function isDesk(value: unknown): value is DeskState {
  return object(value) && typeof value.deskUnlocked === 'boolean' &&
    typeof value.deskWidth === 'number' && value.deskWidth >= 800 && value.deskWidth <= 3000 &&
    typeof value.deskDepth === 'number' && value.deskDepth >= 400 && value.deskDepth <= 1500 &&
    typeof value.deskHeight === 'number' && value.deskHeight >= 500 && value.deskHeight <= 1300
}
export function isPlan(value: unknown): value is CurrentPlan {
  return object(value) && text(value.id) && value.id.length > 0 && ['new', 'upgrade'].includes(String(value.mode)) && budget(value.budget) &&
    object(value.conditions) && ['intent', 'performance', 'quiet'].every(key => text((value.conditions as Record<string, unknown>)[key])) &&
    (value.checkSnapshot === null || isCheckDraft(value.checkSnapshot)) && Array.isArray(value.items) && value.items.length > 0 &&
    value.items.every(p => object(p) && text(p.id) && (p.key === null || keys.includes(String(p.key))) && amount(p.price) &&
      ['type', 'name', 'meta', 'source', 'action', 'score', 'fit', 'reasonTitle', 'rating', 'reviews', 'label'].every(key => text(p[key])) &&
      ['', 'track', 'later'].includes(String(p.actionClass)) && Array.isArray(p.tags) && p.tags.every(text))
}
export function isSetup(value: unknown): value is SavedSetup {
  return object(value) && text(value.id) && text(value.title) && text(value.date) && /^\d{4}-\d{2}-\d{2}$/.test(value.date) &&
    text(value.memo) && text(value.savedAt) && Number.isFinite(Date.parse(value.savedAt)) && amount(value.target) &&
    isPlan(value.plan) && value.id === value.plan.id && isDesk(value.desk) && isCheckDraft(value.checkDraft)
}
export function isPlanState(value: unknown): value is PlanState {
  return object(value) && isDesk(value) && ['new', 'upgrade'].includes(String(value.mode)) && keys.includes(String(value.selectedPart)) &&
    typeof value.stage === 'number' && [0, 1, 2, 3, 4].includes(value.stage) && budget(value.budget) &&
    ['intent', 'performance', 'quiet'].every(key => text(value[key])) && (value.checkSnapshot === null || isCheckDraft(value.checkSnapshot)) &&
    (value.currentPlan === null || isPlan(value.currentPlan)) && (value.stage !== 4 || value.currentPlan !== null)
}

