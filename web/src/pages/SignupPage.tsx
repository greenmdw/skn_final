import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useToast } from '../state/ToastContext'
import { setAuthUser } from '../state/authStore'
import { api, errorMessage, isMockApi } from '../api'
import { TermsModal } from '../components/layout/TermsModal'
import { termsOfService, privacyPolicy } from '../data/termsContent'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { safeNext } from '../utils/redirect'

export function SignupPage() {
  useDocumentTitle('회원가입')
  const navigate = useNavigate()
  const { search } = useLocation()
  const { showToast } = useToast()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [agreeTerms, setAgreeTerms] = useState(false)
  const [agreePrivacy, setAgreePrivacy] = useState(false)
  const [agreeMarketing, setAgreeMarketing] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [openModal, setOpenModal] = useState<'terms' | 'privacy' | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) { setError('이름을 입력해 주세요.'); return }
    if (!email.trim()) { setError('이메일을 입력해 주세요.'); return }
    if (!password) { setError('비밀번호를 입력해 주세요.'); return }
    if (password.length < 8) { setError('비밀번호는 8자 이상으로 입력해 주세요.'); return }
    if (password !== passwordConfirm) { setError('비밀번호가 일치하지 않습니다.'); return }
    if (!agreeTerms) { setError('이용약관에 동의해 주세요.'); return }
    if (!agreePrivacy) { setError('개인정보 처리방침에 동의해 주세요.'); return }
    setError('')
    setSubmitting(true)
    try {
      setAuthUser(await api.auth.signup({ name: name.trim(), email: email.trim(), password, marketingConsent: agreeMarketing }))
    } catch (err) {
      setError(errorMessage(err, '회원가입하지 못했습니다. 잠시 후 다시 시도해 주세요.'))
      setSubmitting(false)
      return
    }
    if (isMockApi) {
      showToast('회원가입이 완료되었습니다. (목업)')
      navigate('/login')
    } else {
      // 서버가 가입과 동시에 로그인 상태로 만든다.
      showToast('회원가입이 완료되었습니다.')
      navigate(safeNext(search) ?? '/')
    }
  }

  return (
    <section className="landing" aria-labelledby="signupTitle">
      <div className="landing-inner login-card">
        <button type="button" className="back-link" onClick={() => navigate('/')}>← 처음으로</button>
        <p className="eyebrow">JOIN TrueFit</p>
        <h1 className="landing-title" id="signupTitle">계정을 만들고<br />내 계획을 저장하세요.</h1>
        <p className="landing-desc">구성과 리스트, 책상 정보를 계정에 안전하게 보관해요.</p>
        <div className="check-card">
          <form onSubmit={handleSubmit}>
            <label className="check-label" htmlFor="signupName">이름</label>
            <input id="signupName" type="text" className="check-input" placeholder="홍길동" autoComplete="name" value={name} onChange={e => setName(e.target.value)} />
            <label className="check-label" htmlFor="signupEmail">이메일</label>
            <input id="signupEmail" type="email" className="check-input" placeholder="you@example.com" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} />
            <label className="check-label" htmlFor="signupPassword">비밀번호</label>
            <input id="signupPassword" type="password" className="check-input" placeholder="8자 이상 입력하세요" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} />
            <label className="check-label" htmlFor="signupPasswordConfirm">비밀번호 확인</label>
            <input id="signupPasswordConfirm" type="password" className="check-input" placeholder="비밀번호를 다시 입력하세요" autoComplete="new-password" value={passwordConfirm} onChange={e => setPasswordConfirm(e.target.value)} />
            <div className="terms-group">
              <div className="terms-row">
                <input id="agreeTerms" type="checkbox" checked={agreeTerms} onChange={e => setAgreeTerms(e.target.checked)} />
                <label className="terms-label" htmlFor="agreeTerms"><span className="terms-tag">[필수]</span>이용약관 동의</label>
                <button type="button" className="terms-view-btn" onClick={() => setOpenModal('terms')}>약관 전문 보기</button>
              </div>
              <div className="terms-row">
                <input id="agreePrivacy" type="checkbox" checked={agreePrivacy} onChange={e => setAgreePrivacy(e.target.checked)} />
                <label className="terms-label" htmlFor="agreePrivacy"><span className="terms-tag">[필수]</span>개인정보 처리방침 동의</label>
                <button type="button" className="terms-view-btn" onClick={() => setOpenModal('privacy')}>전문 보기</button>
              </div>
              <div className="terms-row">
                <input id="agreeMarketing" type="checkbox" checked={agreeMarketing} onChange={e => setAgreeMarketing(e.target.checked)} />
                <label className="terms-label" htmlFor="agreeMarketing"><span className="terms-tag optional">[선택]</span>마케팅 정보 및 이벤트 수신 동의</label>
              </div>
            </div>
            <p className="confirm-error" role="alert">{error}</p>
            <button type="submit" className="analyze-btn" style={{ marginTop: 4 }} disabled={submitting}>회원가입 →</button>
          </form>
          <p className="setup-hint login-foot">
            이미 계정이 있으신가요?{' '}
            <button type="button" className="inline-link" onClick={() => navigate('/login' + search)}>로그인</button>
          </p>
        </div>
        <p className="setup-hint" style={{ marginTop: 16 }}>{isMockApi ? '이 목업에서는 실제 계정이 생성되지 않으며, 입력하신 정보는 서버로 전송되지 않습니다.' : '가입하면 지금까지 만든 추천 목록이 계정으로 합쳐집니다.'}</p>
      </div>
      <TermsModal open={openModal === 'terms'} title="이용약관 동의" articles={termsOfService} onClose={() => setOpenModal(null)} />
      <TermsModal open={openModal === 'privacy'} title="개인정보 처리방침 동의" articles={privacyPolicy} onClose={() => setOpenModal(null)} />
    </section>
  )
}
