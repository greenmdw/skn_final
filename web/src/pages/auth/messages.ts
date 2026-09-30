import { ApiError } from '../../api'

// 옛 frontend/js/api.js 의 tfAuthErrorMessage 와 같은 문구. 서버가 준 오류 코드(error.code)로 고른다.
const MESSAGES: Record<string, string> = {
  invalid_credentials: '이메일 또는 비밀번호가 올바르지 않습니다.',
  account_locked: '로그인 시도가 여러 번 실패해 잠시 잠겼어요. 15분 후 다시 시도해 주세요.',
  email_taken: '이미 가입된 이메일입니다.',
  weak_password: '비밀번호는 영문과 숫자를 포함해 8자 이상이어야 합니다.',
  terms_required: '필수 약관에 동의해 주세요.',
  invalid_password: '현재 비밀번호가 일치하지 않습니다.',
  rate_limited: '요청이 많아요. 잠시 후 다시 시도해 주세요.',
  unauthorized: '로그인이 필요합니다.',
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return MESSAGES[error.code] ?? error.message
  return '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'
}

export const validEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
export const validPassword = (value: string) => value.length >= 8 && /[A-Za-z]/.test(value) && /\d/.test(value)
