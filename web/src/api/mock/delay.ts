// 서버 응답 시간을 흉내 냅니다. 0이면 기다리지 않습니다.
export function delay(ms: number): Promise<void> {
  return ms > 0 ? new Promise(resolve => setTimeout(resolve, ms)) : Promise.resolve()
}
