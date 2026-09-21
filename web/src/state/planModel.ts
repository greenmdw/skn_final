import { wonFmt } from '../utils/format'
import type { CurrentPlan, SavedSetup } from './types'
import { isMockApi } from '../api'

export function planTotal(plan: CurrentPlan): number {
  return plan.items.reduce((sum, part) => sum + part.price, 0)
}

// Explicit budget field accepts won amounts only, with optional separators/unit.
export function parseBudget(value: string): number | null | undefined {
  const text = value.trim()
  if (!text) return null
  if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)\s*원?$/.test(text)) return undefined
  const amount = Number(text.replace(/[,\s원]/g, ''))
  return Number.isSafeInteger(amount) && amount > 0 && amount <= 100000000 ? amount : undefined
}

export function localDate(): string {
  const now = new Date()
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-')
}

export function reportText(setup: SavedSetup): string {
  const plan = setup.plan
  return [setup.title, (isMockApi ? '이 브라우저에 임시 저장 · 구매 예정: ' : '구매 예정: ') + setup.date,
    '유형: ' + (plan.mode === 'upgrade' ? '업그레이드' : '신규 구성'),
    '질문: ' + plan.conditions.intent, '성능: ' + plan.conditions.performance, '소음: ' + plan.conditions.quiet,
    '예산: ' + (plan.budget === null ? '미입력' : wonFmt(plan.budget)),
    ...(plan.checkSnapshot?.rows.map(row => '기존 ' + row.part + ': ' + row.matched) ?? []), '',
    ...plan.items.map(p => p.type + ': ' + p.name + ' - ' + wonFmt(p.price) + '\n추천 근거: ' + p.fit), '',
    '전체 가격: ' + wonFmt(planTotal(plan)), '목표 가격: ' + wonFmt(setup.target), '메모: ' + setup.memo,
    '책상: ' + [setup.desk.deskWidth, setup.desk.deskDepth, setup.desk.deskHeight].join(' × ') + 'mm',
    '저장 시점: ' + setup.savedAt,
  ].join('\n')
}
