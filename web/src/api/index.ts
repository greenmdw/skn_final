import type { Api } from './types'
import { httpApi } from './http'

// 화면과 상태 코드는 이 `api` 객체만 호출합니다. 모든 호출은 백엔드(FastAPI)로 갑니다 — 가짜 데이터 모드는 없습니다.
export const api: Api = httpApi

export { ApiError, SESSION_GONE, errorMessage } from './types'
export type * from './types'
