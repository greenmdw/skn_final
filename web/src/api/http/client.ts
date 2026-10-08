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

const BUSY_CODE = 'llm_busy'
const BUSY_RETRIES = 2
const BUSY_DEFAULT_WAIT_SECONDS = 3

/** fetch 한 번. 서버가 "AI 응답을 기다리는 요청이 많다"(503 llm_busy)고 하면 Retry-After 만큼 기다렸다 최대 2번 다시 보낸다.
 *  오류가 나면 서버가 DB 변경을 되돌리므로 다시 보내도 중복되지 않는다. 그래도 안 되면 서버의 안내 문장이 그대로 사용자에게 간다. */
async function send(path: string, init: RequestInit): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    let response: Response
    try {
      response = await fetch(path, init)
    } catch {
      throw new ApiError(NETWORK_MESSAGE, 'NETWORK')
    }
    if (response.status !== 503 || attempt >= BUSY_RETRIES) return response
    const body = await response.clone().json().catch(() => null) as ErrorEnvelope | null
    if (body?.error?.code !== BUSY_CODE) return response
    const seconds = Number(response.headers.get('Retry-After'))
    await sleep((seconds > 0 ? seconds : BUSY_DEFAULT_WAIT_SECONDS) * 1000)
  }
}

export async function request<T>(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const response = await send(path, {
    method,
    credentials: 'include',
    headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = response.status === 204 ? '' : await response.text()
  let parsed: unknown = null
  if (text) {
    try { parsed = JSON.parse(text) } catch { parsed = null }
  }
  if (!response.ok) throw toApiError(response.status, parsed)
  return parsed as T
}

/** 파일을 함께 보내는 multipart 요청. Content-Type 은 브라우저가 경계값과 함께 정한다. */
export async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const response = await send(path, { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' }, body: form })
  const text = await response.text()
  let parsed: unknown = null
  if (text) {
    try { parsed = JSON.parse(text) } catch { parsed = null }
  }
  if (!response.ok) throw toApiError(response.status, parsed)
  return parsed as T
}

export const sleep =(ms: number) => new Promise<void>(resolve => window.setTimeout(resolve, ms))
