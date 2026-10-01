import { isoToKo, wonFmt } from '../utils/format'
import type { CurrentPlan, PartKey, PlanItem, SavedSetup } from './types'
import { QUIET_LABEL } from './conditionLabels'
export { parseBudget } from './budget'

export function planTotal(plan: CurrentPlan): number {
  return plan.items.reduce((sum, part) => sum + part.price, 0)
}

/** 한 대에 하나만 쓰는 부품 — 수량을 2개 이상으로 올리면 "여러 대를 구매하시나요?" 안내를 보인다 */
const SINGLE_PER_PC: PartKey[] = ['cpu', 'board', 'psu', 'case']
export function multiQtyItems(plan: CurrentPlan): PlanItem[] {
  return plan.items.filter(item => item.key !== null && SINGLE_PER_PC.includes(item.key) && (item.qty ?? 1) > 1)
}

export function localDate(): string {
  const now = new Date()
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-')
}

export function reportText(setup: SavedSetup): string {
  const plan = setup.plan
  return [setup.title, '구매 예정: ' + isoToKo(setup.date),
    '유형: ' + (plan.mode === 'upgrade' ? '업그레이드' : '신규 구성'),
    '질문: ' + plan.conditions.intent, '성능: ' + plan.conditions.performance, QUIET_LABEL + ': ' + plan.conditions.quiet,
    '예산: ' + (plan.budget === null ? '미입력' : wonFmt(plan.budget)),
    ...(plan.checkSnapshot?.rows.map(row => '기존 ' + row.part + ': ' + row.matched) ?? []), '',
    ...plan.items.map(p => p.type + ': ' + p.name + ' - ' + wonFmt(p.price) + '\n추천 근거: ' + p.fit), '',
    '전체 가격: ' + wonFmt(planTotal(plan)), '목표 가격: ' + wonFmt(setup.target), '메모: ' + setup.memo,
    '책상: ' + [setup.desk.deskWidth, setup.desk.deskDepth, setup.desk.deskHeight].join(' × ') + 'mm',
    '저장 시점: ' + setup.savedAt,
  ].join('\n')
}
