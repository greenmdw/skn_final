import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import { setAuthUser } from '../../state/authStore'
import AuthLayout from './AuthLayout'
import { authErrorMessage, validEmail } from './messages'

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next')
  const target = next && next.startsWith('/') && !next.startsWith('//') ? next : '/'   // 로그인 뒤 돌아갈 곳(같은 사이트 안만)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [forgot, setForgot] = useState(false)
  const [error, setError] = useState('')
  const [invalid, setInvalid] = useState({ email: false, password: false })
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const emailValue = email.trim()
    if (!validEmail(emailValue)) { setInvalid({ email: true, password: false }); setError('올바른 이메일 주소를 입력해 주세요.'); return }
    if (!password) { setInvalid({ email: false, password: true }); setError('비밀번호를 입력해 주세요.'); return }
    setInvalid({ email: false, password: false })
    setError('')
    setBusy(true)
    try {
      setAuthUser(await api.auth.login({ email: emailValue, password, remember }))
      navigate(target)
    } catch (err) {
      setBusy(false)
      if ((err as { code?: string }).code === 'invalid_credentials') setInvalid({ email: true, password: true })
      setError(authErrorMessage(err))
    }
  }

  const clear = (key: 'email' | 'password') => { setError(''); setInvalid(prev => ({ ...prev, [key]: false })) }

  return (
    <AuthLayout switcher={<>아직 계정이 없으신가요? <Link to="/signup">회원가입</Link></>}>
      <section className="auth-card">
        <span className="auth-eyebrow">WELCOME BACK</span>
        <h1>다시 만나 반가워요</h1>
        <p className="auth-sub">이메일과 비밀번호로 로그인하고, 저장해 둔 장바구니와 리포트를 이어가세요.</p>
        <form noValidate onSubmit={submit}>
          <div className="auth-field">
            <label htmlFor="tf-login-email">이메일 *</label>
            <input type="email" id="tf-login-email" autoComplete="email" placeholder="you@example.com" required
              className={invalid.email ? 'auth-invalid' : ''} value={email}
              onChange={e => { setEmail(e.target.value); clear('email') }} />
          </div>
          <div className="auth-field">
            <label htmlFor="tf-login-password">비밀번호 *</label>
            <input type="password" id="tf-login-password" autoComplete="current-password" placeholder="비밀번호를 입력해 주세요" required
              className={invalid.password ? 'auth-invalid' : ''} value={password}
              onChange={e => { setPassword(e.target.value); clear('password') }} />
          </div>
          <div className="auth-row-between">
            <label className="auth-check-inline">
              <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
              <span>로그인 상태 유지</span>
            </label>
            <button type="button" className="auth-link-button" onClick={() => setForgot(true)}>비밀번호를 잊으셨나요?</button>
          </div>
          {forgot && <p className="auth-forgot">비밀번호 재설정은 아직 준비 중이에요.</p>}
          <p className="auth-error" role="alert">{error}</p>
          <button type="submit" className="auth-btn" disabled={busy}>{busy ? '로그인 중…' : '로그인'}</button>
          <p className="auth-switch">아직 계정이 없으신가요? <Link to="/signup">이메일로 회원가입 →</Link></p>
        </form>
      </section>
    </AuthLayout>
  )
}
