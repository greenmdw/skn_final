import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useToast } from '../state/ToastContext'
import { setAuthUser } from '../state/authStore'
import { api, errorMessage, isMockApi } from '../api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { safeNext } from '../utils/redirect'

export function LoginPage() {
  useDocumentTitle('로그인')
  const navigate = useNavigate()
  const { search } = useLocation()
  const { showToast } = useToast()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const cleanEmail = email.trim()
    if (!cleanEmail) { setError('이메일을 입력해 주세요.'); return }
    if (!password) { setError('비밀번호를 입력해 주세요.'); return }
    setError('')
    setSubmitting(true)
    try {
      setAuthUser(await api.auth.login({ email: cleanEmail, password }))
    } catch (err) {
      setError(errorMessage(err, '로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.'))
      setSubmitting(false)
      return
    }
    showToast(isMockApi ? '로그인되었습니다. (목업)' : '로그인되었습니다.')
    navigate(safeNext(search) ?? '/')
  }

  return (
    <section className="landing" aria-labelledby="loginTitle">
      <div className="landing-inner login-card">
        <button type="button" className="back-link" onClick={() => navigate('/')}>← 처음으로</button>
        <p className="eyebrow">WELCOME BACK</p>
        <h1 className="landing-title" id="loginTitle">로그인하고<br />계획을 이어가세요.</h1>
        <p className="landing-desc">저장한 구성과 리스트를 이 계정에서 계속 관리할 수 있어요.</p>
        <div className="check-card">
          <form onSubmit={handleSubmit}>
            <label className="check-label" htmlFor="loginEmail">이메일</label>
            <input id="loginEmail" type="email" className="check-input" placeholder="you@example.com" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} />
            <label className="check-label" htmlFor="loginPassword">비밀번호</label>
            <input id="loginPassword" type="password" className="check-input" placeholder="비밀번호를 입력하세요" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
            <p className="confirm-error" role="alert">{error}</p>
            <button type="submit" className="analyze-btn" style={{ marginTop: 4 }} disabled={submitting}>로그인 →</button>
          </form>
          <p className="setup-hint login-foot">
            계정이 없으신가요?{' '}
            <button type="button" className="inline-link" onClick={() => navigate('/signup' + search)}>회원가입</button>
          </p>
        </div>
        <p className="setup-hint" style={{ marginTop: 16 }}>{isMockApi ? '이 목업에서는 실제 인증이 이뤄지지 않으며, 입력하신 정보는 서버로 전송되지 않습니다.' : '로그인하면 지금까지 만든 추천 목록이 계정으로 합쳐집니다.'}</p>
      </div>
    </section>
  )
}
