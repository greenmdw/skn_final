import type { Api } from './types'
import { mockApi } from './mock'
import { httpApi } from './http'

// 화면과 상태 코드는 이 `api` 객체만 호출합니다.
// 기본은 백엔드 연결(httpApi). 백엔드 없이 화면만 볼 때는 `VITE_API_MODE=mock npm run dev`.
export const isMockApi = import.meta.env.VITE_API_MODE === 'mock'
export const api: Api = isMockApi ? mockApi : httpApi

export { ApiError, errorMessage } from './types'
export type * from './types'
