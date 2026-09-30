import { ApiError, SESSION_GONE } from '../types'

// 서버는 "없는 목록"과 "내 것이 아닌 목록"(로그아웃했거나 다른 계정)을 똑같이 404 not_found 로 답한다.
// 브라우저에 남아 있던 작업이 그런 목록을 가리키면 SESSION_GONE 으로 바꿔서, 화면이 작업을 비우고 새로 시작하게 한다.

const GONE_MESSAGE = '이전에 하던 작업을 서버에서 찾을 수 없어요. 로그아웃했거나 다른 계정일 수 있어요. 조건을 다시 말씀해 주세요.'

export const isNotFound = (error: unknown) => error instanceof ApiError && error.code === 'not_found'

/** not_found 만 SESSION_GONE 으로 바꾸고, 나머지 오류는 그대로 던진다. */
export function asSessionGone(error: unknown): unknown {
  return isNotFound(error) ? new ApiError(GONE_MESSAGE, SESSION_GONE) : error
}
