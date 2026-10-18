import type { PartKey } from '../state/types'

/** 받은 견적 점검의 부품군 이름 → 아이콘 키. 모르는 이름이면 null(범용 아이콘). */
export function partKeyOf(category: string | null | undefined): PartKey | null {
  const text = (category ?? '').toLowerCase()
  if (!text) return null
  if (text.includes('cpu') || text.includes('프로세서')) return 'cpu'
  if (text.includes('gpu') || text.includes('그래픽')) return 'gpu'
  if (text.includes('ram') || text.includes('메모리')) return 'ram'
  if (text.includes('메인보드') || text.includes('보드')) return 'board'
  if (text.includes('저장') || text.includes('ssd') || text.includes('hdd')) return 'ssd'
  if (text.includes('파워') || text.includes('psu')) return 'psu'
  if (text.includes('케이스')) return 'case'
  if (text.includes('쿨러')) return 'cooler'
  if (text.includes('모니터')) return 'monitor'
  return null
}
