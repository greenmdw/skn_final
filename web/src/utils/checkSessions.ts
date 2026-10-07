// 서버 대화 목록에는 "받은 견적 점검" 표시가 없어서(목록 항목만으로는 일반 추천과 구분되지 않는다),
// 이 브라우저에서 만든 점검 초안 id 를 기억해 둔다. 왼쪽 패널에서 그 대화를 누르면 점검 화면으로 연다.
// 다른 기기·브라우저에서는 알 수 없다 — 서버가 점검 종류를 알려 주면 이 보관은 필요 없다.
const KEY = 'truefit.check-sessions.v1'
const MAX = 60

export interface CheckSessionInfo {
  createdAt: string
  /** 마지막으로 비교한 저장 견적 비교 id — 다시 열 때 비교표를 되살린다 */
  comparisonId?: string
}

function read(): Record<string, CheckSessionInfo> {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(KEY) || '{}')
    if (typeof data !== 'object' || data === null || Array.isArray(data)) return {}
    return Object.fromEntries(Object.entries(data as Record<string, unknown>).filter(([, value]) =>
      typeof value === 'object' && value !== null && typeof (value as CheckSessionInfo).createdAt === 'string')) as Record<string, CheckSessionInfo>
  } catch { return {} }
}

function write(next: Record<string, CheckSessionInfo>) {
  const entries = Object.entries(next).sort(([, a], [, b]) => b.createdAt.localeCompare(a.createdAt)).slice(0, MAX)
  try { localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(entries))) } catch { /* 보관 실패는 무시 */ }
}

export function registerCheckSession(draftId: string) {
  const all = read()
  all[draftId] = { ...all[draftId], createdAt: all[draftId]?.createdAt ?? new Date().toISOString() }
  write(all)
}

export function checkSessionInfo(draftId: string): CheckSessionInfo | null {
  return read()[draftId] ?? null
}

export const isCheckSession = (draftId: string) => checkSessionInfo(draftId) !== null

export function rememberCheckComparison(draftId: string, comparisonId: string) {
  const all = read()
  if (!all[draftId]) return
  all[draftId] = { ...all[draftId], comparisonId }
  write(all)
}
