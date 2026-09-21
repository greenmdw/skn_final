import { ApiError } from '../types'

// 백엔드(FastAPI)와 같은 오리진에서 서빙되므로 상대 경로를 쓴다. 개발 서버(vite)는 vite.config.ts 의 프록시가 같은 경로를 백엔드로 넘긴다.
// 인증은 httpOnly 쿠키라 credentials: 'include' 가 필요하다.

interface ErrorEnvelope { error?: { code?: string; message?: string } }

const NETWORK_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.'

/** 서버가 준 오류 봉투({"error":{"code","message"}})를 ApiError 로 바꾼다. 그 외 형식은 상태 코드로 짐작한다. */
function toApiError(status: number, body: unknown): ApiError {
  const envelope = (body ?? {}) as ErrorEnvelope & { detail?: unknown }
  const error = envelope.error
  if (error?.message) return new ApiError(error.message, error.code ?? 'HTTP_' + status)
  if (Array.isArray(envelope.detail)) return new ApiError('입력한 값의 형식이 올바르지 않습니다.', 'VALIDATION')
  if (status === 401) return new ApiError('로그인이 필요합니다.', 'AUTH_REQUIRED')
  if (status === 404) return new ApiError('요청한 항목을 찾을 수 없습니다.', 'NOT_FOUND')
  return new ApiError('요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.', 'HTTP_' + status)
}

export async function request<T>(method: 'GET' | 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'include',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(NETWORK_MESSAGE, 'NETWORK')
  }
  const text = response.status === 204 ? '' : await response.text()
  let parsed: unknown = null
  if (text) {
    try { parsed = JSON.parse(text) } catch { parsed = null }
  }
  if (!response.ok) throw toApiError(response.status, parsed)
  return parsed as T
}

export const sleep = (ms: number) => new Promise<void>(resolve => window.setTimeout(resolve, ms))
