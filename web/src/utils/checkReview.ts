import type { SavedSetup } from '../state/types'

/** 백엔드가 받는 부품군 이름(한글 슬롯) 순서 */
export const CATEGORY_ORDER = ['CPU', 'GPU', 'RAM', '메인보드', '저장장치', '파워', '케이스', '쿨러']

export const PURPOSE_LABEL: Record<string, string> = { game: '게임', creation: '창작', office: '사무', study: '학습', other: '기타' }
export const RESOLUTION_LABEL: Record<string, string> = { FHD_144: 'FHD 144Hz', QHD_165: 'QHD 165Hz', '4K': '4K' }
export const PRIORITY_LABEL: Record<string, string> = { performance: '성능 우선', value: '가성비', quiet: '저소음' }

export function fileSize(size: number): string {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

export function wonText(value: number | null | undefined): string {
  return value == null ? '금액 미인식' : `${value.toLocaleString('ko-KR')}원`
}

export function signedWon(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toLocaleString('ko-KR')}원`
}

// ── 저장 견적 ──────────────────────────────────────────────────────────────
const PRIORITY_WORDS = ['성능 우선', '가성비 우선', '가성비', '저소음']

export function setupPurpose(setup: SavedSetup): string {
  const purpose = setup.plan.conditions.intent.trim()
  if (purpose) return purpose
  const firstTitlePart = setup.title.split('·')[0]?.trim()
  return firstTitlePart && firstTitlePart !== setup.title ? firstTitlePart : '용도 미기록'
}

export function setupPriority(setup: SavedSetup): string {
  const priority = setup.plan.conditions.quiet.trim()
  if (priority) return priority
  return PRIORITY_WORDS.find(word => setup.title.includes(word)) ?? '우선순위 미기록'
}

export function setupDate(setup: SavedSetup): string {
  const date = new Date(setup.savedAt)
  if (Number.isNaN(date.getTime())) return setup.date || '날짜 정보 없음'
  return date.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    reader.readAsText(file, 'utf-8')
  })
}

export function newClientId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
