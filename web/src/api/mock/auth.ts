import type { Api, AuthUser } from '../types'

// 목업: 실제 인증은 하지 않고 입력한 값으로 사용자 정보를 만들어 돌려줍니다.
export const auth: Api['auth'] = {
  async login({ email }) {
    return { name: email.split('@')[0] || email, email } satisfies AuthUser
  },
  async signup({ name, email }) {
    return { name, email } satisfies AuthUser
  },
}
