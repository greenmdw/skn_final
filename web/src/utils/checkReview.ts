import type { QuoteDraft, QuoteDraftItem, QuoteDraftItemEdit, QuoteMatchStatus } from '../api'
import type { PartKey, SavedSetup } from '../state/types'

/** 백엔드가 받는 부품군 이름(한글 슬롯) 순서 */
export const CATEGORY_ORDER = ['CPU', 'GPU', 'RAM', '메인보드', '저장장치', '파워', '케이스', '쿨러']

export const REVIEW_PART_KEYS: Record<string, PartKey> = {
  CPU: 'cpu', GPU: 'gpu', RAM: 'ram', 메인보드: 'board', SSD: 'ssd', 저장장치: 'ssd', 파워: 'psu', 케이스: 'case', 쿨러: 'cooler',
}

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

export function normalizedProductName(name: string): string {
  return name.toLocaleLowerCase().replace(/[^a-z0-9가-힣]/g, '')
}

// ── 인식 항목 ──────────────────────────────────────────────────────────────
export interface PendingEdit { name?: string; quantity?: number; lineTotal?: number | null; delete?: boolean }

export interface ItemStatus {
  tone: 'ok' | 'warn' | 'miss'
  label: string
  /** 사용자가 확인했거나 서버가 제품을 확정한 항목 */
  checked: boolean
}

/** 서버의 매칭 판정을 그대로 화면 상태로 옮긴다. 수정 대기 중이면 "수정 대기". */
export function itemStatus(item: QuoteDraftItem, pending?: PendingEdit): ItemStatus {
  if (pending) return { tone: 'warn', label: '수정 대기', checked: true }
  if (item.userEdited) return { tone: 'ok', label: '사용자 확인', checked: true }
  const byStatus: Record<QuoteMatchStatus, ItemStatus> = {
    confirmed: { tone: 'ok', label: '대응됨', checked: true },
    ambiguous: { tone: 'warn', label: '제품 확인 필요', checked: false },
    candidate: { tone: 'warn', label: '제품 확인 필요', checked: false },
    inferred: { tone: 'warn', label: '제품 확인 필요', checked: false },
    unmatched: { tone: 'miss', label: '제품 확인 필요', checked: false },
  }
  return byStatus[item.matchStatus]
}

/** 대응 결과 한 줄: 카탈로그 제품명, 후보가 여럿이면 개수, 없으면 안내 */
export function matchedLine(item: QuoteDraftItem): string {
  if (item.matchedName) return item.matchedName
  if (item.matchStatus === 'ambiguous') return item.candidateCount ? `후보 ${item.candidateCount}개 · 제품을 정확히 정해주세요` : '후보가 여러 개예요'
  if (item.matchStatus === 'unmatched') return '카탈로그에서 찾지 못함'
  return '정확한 제품을 확정하지 못함'
}

export function categoryRank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category)
  return index === -1 ? CATEGORY_ORDER.length : index
}

export interface ItemGroup { category: string; items: QuoteDraftItem[] }

/** 부품군 순서대로 묶는다. 같은 부품군의 서로 다른 제품은 모두 남긴다. */
export function groupItems(items: QuoteDraftItem[]): ItemGroup[] {
  const map = new Map<string, QuoteDraftItem[]>()
  for (const item of items) {
    const list = map.get(item.category) ?? []
    list.push(item)
    map.set(item.category, list)
  }
  return [...map.entries()]
    .sort(([a], [b]) => categoryRank(a) - categoryRank(b))
    .map(([category, list]) => ({ category, items: list }))
}

/** 이미지 번호(견적 이미지 N번). 교체·직접 추가 항목은 그 이름으로 */
export function sourceBadge(item: QuoteDraftItem, draft: QuoteDraft): string {
  const labels = item.sourceIds.map(id => {
    const source = draft.sources.find(entry => entry.id === id)
    if (!source) return null
    if (source.type === 'replacement') return '교체'
    if (source.type === 'manual') return '직접 추가'
    if (source.type === 'text') return '텍스트'
    return `${source.sortOrder}번`
  }).filter((label): label is string => Boolean(label))
  return labels.length ? labels.join('·') : '출처 없음'
}

/** 분석 기준으로 고른 항목(없으면 그 부품군의 첫 항목)의 id */
export function effectiveSelection(draft: QuoteDraft, local: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const group of groupItems(draft.items)) {
    const wanted = local[group.category] ?? draft.selectedItemByCategory[group.category]
    result[group.category] = group.items.some(item => item.id === wanted) ? wanted : group.items[0].id
  }
  return result
}

/** 수정 대기 값을 화면 표시용으로 항목에 덧씌운다 */
export function withPending(item: QuoteDraftItem, pending?: PendingEdit): QuoteDraftItem {
  if (!pending) return item
  return {
    ...item,
    name: pending.name ?? item.name,
    quantity: pending.quantity ?? item.quantity,
    lineTotal: pending.lineTotal === undefined ? item.lineTotal : pending.lineTotal,
  }
}

export const MAX_QUANTITY = 20

/**
 * 수량을 바꾼 수정 대기 값. 품목 금액은 수량이 반영된 값이라, 금액을 읽은 항목은 1개 값은 그대로 두고 비례해서 다시 계산한다.
 * 원래 값으로 돌아오면(이름·수량·금액이 모두 같으면) null — 수정 대기에서 뺀다.
 */
export function withQuantity(item: QuoteDraftItem, pending: PendingEdit | undefined, next: number): PendingEdit | null {
  const shown = withPending(item, pending)
  const lineTotal = shown.lineTotal == null ? undefined : Math.round(shown.lineTotal / Math.max(shown.quantity, 1) * next)
  const merged: PendingEdit = { ...pending, quantity: next, ...(lineTotal === undefined ? {} : { lineTotal }) }
  const same = (merged.name === undefined || merged.name === item.name) && merged.quantity === item.quantity
    && (merged.lineTotal === undefined || merged.lineTotal === item.lineTotal)
  return same ? null : merged
}

export function pendingToEdits(pending: Record<string, PendingEdit>): QuoteDraftItemEdit[] {
  return Object.entries(pending).map(([id, edit]) => (edit.delete ? { id, delete: true } : { id, name: edit.name, quantity: edit.quantity, lineTotal: edit.lineTotal }))
}

/** 선택 항목의 품목 합계(금액을 읽은 항목만) */
export function selectedTotal(draft: QuoteDraft, selection: Record<string, string>, pending: Record<string, PendingEdit>): number {
  return Object.values(selection).reduce((sum, itemId) => {
    const item = draft.items.find(entry => entry.id === itemId)
    if (!item) return sum
    return sum + (withPending(item, pending[itemId]).lineTotal ?? 0)
  }, 0)
}

/** 입력한 조건을 화면 태그로 */
export function conditionTags(conditions: Record<string, unknown>, requirementLabel?: string | null): string[] {
  const tags: string[] = []
  const purpose = typeof conditions.purpose === 'string' ? PURPOSE_LABEL[conditions.purpose] : undefined
  const resolution = typeof conditions.resolution === 'string' ? RESOLUTION_LABEL[conditions.resolution] : undefined
  const priority = typeof conditions.priority === 'string' ? PRIORITY_LABEL[conditions.priority] : undefined
  if (purpose) tags.push(`용도 · ${purpose}`)
  if (resolution) tags.push(`해상도 · ${resolution}`)
  if (typeof conditions.budget_max === 'number' && conditions.budget_max > 0) tags.push(`예산 · ${conditions.budget_max.toLocaleString('ko-KR')}원`)
  if (priority) tags.push(`우선순위 · ${priority}`)
  if (Array.isArray(conditions.games) && conditions.games.length) tags.push(`게임 · ${conditions.games.join(', ')}`)
  if (!tags.length && requirementLabel) tags.push(requirementLabel)
  return tags
}

/** 질문 문장에서 평가 관점 태그를 뽑는다(화면 표시용 — 서버 판정이 아니다) */
export function questionTags(question: string, chips: string[]): string[] {
  const tags: string[] = []
  if (/호환|소켓|장착/.test(question)) tags.push('호환성')
  if (/가격|예산|비싸|가성비/.test(question)) tags.push('가격 적정성')
  if (/성능|게임|병목|QHD|FHD|4K/i.test(question)) tags.push('성능 밸런스')
  if (/업그레이드|교체|바꿀/.test(question)) tags.push('업그레이드')
  for (const chip of chips) tags.push(chip)
  const unique = [...new Set(tags)]
  return unique.length ? unique : ['전체 점검']
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

/** 확인한 시각을 "오늘 확인"·"N일 전 확인"으로. 시각을 알 수 없으면 그렇게 말한다. */
export function checkedAgo(iso: string | null | undefined): string {
  const time = iso ? Date.parse(iso) : NaN
  if (Number.isNaN(time)) return '확인 시각 알 수 없음'
  const days = Math.floor((Date.now() - time) / 86_400_000)
  return days <= 0 ? '오늘 확인' : `${days}일 전 확인`
}

/** 제품명 입력에 "238,000원" 같은 금액이 섞여 있으면 떼어 낸다 */
export function splitNameAndPrice(value: string): { name: string; price: number | null } {
  let price: number | null = null
  const name = value
    .replace(/(?:₩\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원/g, (_, amount: string) => {
      price = Number(amount.replaceAll(',', ''))
      return ' '
    })
    .replace(/\s{2,}/g, ' ')
    .replace(/[·,\-\s]+$/, '')
    .trim()
  return { name, price }
}

export function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    reader.readAsText(file, 'utf-8')
  })
}

/** 본문(.pl-main)만 스크롤한다. scrollIntoView 는 overflow:hidden 인 바깥 문서까지 밀어 올려 상단바가 잘린다. */
export function scrollMainTo(id: string, block: 'start' | 'center' = 'start') {
  const element = document.getElementById(id)
  const main = element?.closest<HTMLElement>('.pl-main')
  if (!element || !main) return
  const offset = element.getBoundingClientRect().top - main.getBoundingClientRect().top
  const top = main.scrollTop + offset - (block === 'center' ? Math.max(0, (main.clientHeight - element.offsetHeight) / 2) : 16)
  main.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  const root = document.scrollingElement
  if (root && root.scrollTop !== 0) root.scrollTop = 0
}

export function newClientId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
