import { peripheralsTotal, planTotal } from '../../state/planModel'
import type { SavedSetup } from '../../state/types'
import { PERIPHERAL_KINDS } from '../../utils/peripherals'

// "내 현재 PC"의 부품 칸. 서버에는 저장하지 않고 이 브라우저(계정별)에만 남긴다.
export const PC_FIELDS = [
  ['cpu', 'CPU'], ['gpu', '그래픽카드'], ['ram', '메모리'], ['storage', '저장장치'],
  ['board', '메인보드'], ['psu', '파워'], ['cooler', '쿨러'], ['case', '케이스'],
] as const
export type PcKey = typeof PC_FIELDS[number][0]
export type PcParts = Partial<Record<PcKey, string>>

export const PC_PLACEHOLDERS: Record<PcKey, string> = {
  cpu: 'Ryzen 5 5600', gpu: 'RTX 3060 12GB', ram: 'DDR4 16GB', storage: 'NVMe SSD 500GB',
  board: 'B550M', psu: '650W 80PLUS Bronze', cooler: '기본 쿨러', case: '미들타워',
}

export interface MyPc { parts: PcParts; source: string; title: string; savedAt: string }

/** 부품 이름표("CPU 쿨러", "그래픽카드"…)를 칸으로 옮긴다. "CPU 쿨러"는 CPU 보다 먼저 본다. */
export function pcKey(label: string): PcKey | null {
  if (/쿨러/.test(label)) return 'cooler'
  if (/CPU/i.test(label)) return 'cpu'
  if (/그래픽|GPU/i.test(label)) return 'gpu'
  if (/메모리|RAM/i.test(label)) return 'ram'
  if (/저장|SSD|HDD/i.test(label)) return 'storage'
  if (/메인보드|보드/.test(label)) return 'board'
  if (/파워|PSU/i.test(label)) return 'psu'
  if (/케이스/.test(label)) return 'case'
  return null
}

const storageKey = (email: string) => `truefit.mypc.v1:${email}`

export function readMyPc(email: string): MyPc | null {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(storageKey(email)) || 'null')
    if (typeof raw !== 'object' || raw === null) return null
    const value = raw as Partial<MyPc>
    if (typeof value.parts !== 'object' || value.parts === null) return null
    const parts: PcParts = {}
    for (const [key] of PC_FIELDS) {
      const text = (value.parts as Record<string, unknown>)[key]
      if (typeof text === 'string' && text.trim()) parts[key] = text.trim()
    }
    if (!Object.keys(parts).length) return null
    return { parts, source: String(value.source ?? ''), title: String(value.title ?? ''), savedAt: String(value.savedAt ?? '') }
  } catch { return null }
}

export function writeMyPc(email: string, pc: MyPc | null) {
  try {
    if (pc) localStorage.setItem(storageKey(email), JSON.stringify(pc))
    else localStorage.removeItem(storageKey(email))
  } catch { /* 저장소를 못 써도 화면은 그대로 쓴다 */ }
}

/** 내 PC 를 받은 견적 점검 질문 문장으로 만든다 */
export function pcQuestion(pc: MyPc): string {
  const names = PC_FIELDS.filter(([key]) => pc.parts[key]).map(([key, label]) => `${label} ${pc.parts[key]}`)
  return `내 현재 PC(${names.join(', ')})를 기준으로 이 견적의 호환성과 업그레이드 여부를 점검해줘.`
}

export const dateText = (iso: string | null | undefined): string => {
  const time = iso ? Date.parse(iso) : NaN
  if (Number.isNaN(time)) return ''
  const date = new Date(time)
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
}

export const reportPath = (setup: Pick<SavedSetup, 'id' | 'revisionNo'>) =>
  `/report/${setup.id}${setup.revisionNo ? `?v=${setup.revisionNo}` : ''}`

/** 견적서의 부품(본체 + 주변기기)을 [이름표, 제품명] 줄로 */
export function setupSpecs(setup: SavedSetup): [string, string][] {
  const body = setup.plan.items.map((item): [string, string] => [item.type || item.label, item.name])
  const periph = (setup.peripherals ?? []).map((item): [string, string] => [
    PERIPHERAL_KINDS.find(kind => kind.id === item.kind)?.label ?? item.kind, item.name,
  ])
  return [...body, ...periph]
}

export const setupTotal = (setup: SavedSetup) => planTotal(setup.plan) + peripheralsTotal(setup.peripherals)

/** 목록 줄에 보일 요약: 제품명 앞 몇 개 */
export function setupSummary(setup: SavedSetup, count = 4): string {
  const names = setupSpecs(setup).map(([, name]) => name)
  return names.slice(0, count).join(' | ') + (names.length > count ? ` 외 ${names.length - count}개` : '')
}

/** 견적서의 본체 부품을 내 PC 칸으로 */
export function setupToPcParts(setup: SavedSetup): PcParts {
  const parts: PcParts = {}
  for (const item of setup.plan.items) {
    const key = pcKey(item.type) ?? pcKey(item.label)
    if (key && !parts[key]) parts[key] = item.name
  }
  return parts
}

export const newestFirst = (a: SavedSetup, b: SavedSetup) => b.savedAt.localeCompare(a.savedAt)

/** 견적서 하나를 가리키는 키(목록 id + 견적서 번호) */
export const configKey = (setup: { id: string; revisionNo?: number }) => `${setup.id}:${setup.revisionNo ?? 0}`
