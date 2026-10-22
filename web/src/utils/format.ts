export function wonFmt(n: number): string {
  return Math.round(n).toLocaleString('ko-KR') + '원'
}

export function parseWon(price: string): number {
  return Number(String(price).replace(/[^0-9]/g, ''))
}

/** ISO(yyyy-mm-dd) → 한국식 짧은 날짜 yy/mm/dd. 형식이 아니면 빈 문자열 */
export function isoToKo(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return match ? `${match[1].slice(2)}/${match[2]}/${match[3]}` : ''
}

/** yy/mm/dd(숫자만 쳐도 됨) → ISO(yyyy-mm-dd). 없는 날짜(2월 30일 등)면 null. 연도는 2000년대로 본다 */
export function koToIso(text: string): string | null {
  const digits = text.replace(/\D/g, '')
  if (digits.length !== 6) return null
  const year = 2000 + Number(digits.slice(0, 2)), month = Number(digits.slice(2, 4)), day = Number(digits.slice(4, 6))
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// ── 날짜 표기(한국식) ──
const clock = (date: Date) => `${date.getHours() < 12 ? '오전' : '오후'} ${date.getHours() % 12 || 12}:${String(date.getMinutes()).padStart(2, '0')}`
/** 대화 줄: 마지막 수정 날짜와 시각 — 9월 30일 오후 4:25 */
export function fullDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return `${date.getMonth() + 1}월 ${date.getDate()}일 ${clock(date)}`
}
/** 견적서 줄: 짧게 — 9/30 오후 4:25 */
export function shortDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return `${date.getMonth() + 1}/${date.getDate()} ${clock(date)}`
}
/** 견적서 오른쪽 금액: 162만 (1만 원 미만이면 원 단위) */
export const compactWon = (won: number) => (won >= 10000 ? `${Math.round(won / 10000).toLocaleString('ko-KR')}만` : wonFmt(won))

// 대화 내역을 마지막 활동 시점으로 묶는 제목. 자정 기준 날짜 차이로 나누고, 30일이 지나면 월별(예: 2026년 8월)로 나눈다.
export function dateGroup(iso: string | null): string {
  if (!iso) return '날짜 없음'
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86400000)
  if (days <= 0) return '오늘'
  if (days === 1) return '어제'
  if (days <= 7) return '지난 7일'
  if (days <= 30) return '지난 30일'
  const date = new Date(iso)
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월`
}

/** 리포트 화면의 확정 시각 — 2026. 10. 1. 오전 9:50 */
export function confirmedAtText(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}
