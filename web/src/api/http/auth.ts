import type { Api, AuthUser } from '../types'
import { request } from './client'
import type { WireUser } from './wire'

function toUser(wire: WireUser): AuthUser {
  return { name: wire.user.display_name, email: wire.user.email }
}

// 서버가 httpOnly 쿠키(truefit_session)로 세션을 만든다. 로그인·가입 때 게스트로 만든 추천 목록이 계정으로 합쳐진다.
export const auth: Api['auth'] = {
  async login({ email, password }) {
    return toUser(await request<WireUser>('POST', '/auth/login', { email, password, remember: true }))
  },
  // 가입 화면이 이용약관·개인정보 처리방침 동의를 확인한 뒤에만 이 함수를 부르므로 두 동의를 true 로 보낸다.
  async signup({ name, email, password, marketingConsent }) {
    return toUser(await request<WireUser>('POST', '/auth/signup', {
      email, password, display_name: name, terms_agreed: true, privacy_agreed: true, marketing_agreed: marketingConsent,
    }))
  },
}
