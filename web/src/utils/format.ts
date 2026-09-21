export function wonFmt(n: number): string {
  return Math.round(n).toLocaleString('ko-KR') + '원'
}

export function parseWon(price: string): number {
  return Number(String(price).replace(/[^0-9]/g, ''))
}
