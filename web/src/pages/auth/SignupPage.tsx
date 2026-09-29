import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { setAuthUser } from '../../state/authStore'
import AuthLayout from './AuthLayout'
import { authErrorMessage, validEmail, validPassword } from './messages'
import { TERMS } from './terms'

type Note = { text: string; tone: '' | 'ok' | 'bad'; loginLink?: boolean }

export default function SignupPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [name, setName] = useState('')
  const [agreed, setAgreed] = useState([false, false])   // 필수 약관 2개(이용약관, 개인정보 처리방침)
  const [marketing, setMarketing] = useState(false)
  const [emailNote, setEmailNote] = useState<Note>({ text: '', tone: '' })
  const [emailAvailable, setEmailAvailable] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const seq = useRef(0)

  // 이메일 입력을 멈추고 400ms 뒤에 중복 확인 (옛 화면과 같다). 늦게 온 응답은 버린다.
  useEffect(() => {
    const value = email.trim()
    const mine = ++seq.current
    setEmailAvailable(null)
    if (!value) { setEmailNote({ text: '', tone: '' }); return }
    if (!validEmail(value)) { setEmailAvailable(false); setEmailNote({ text: '올바른 이메일 형식으로 입력해 주세요.', tone: 'bad' }); return }
    setEmailNote({ text: '이메일 확인 중…', tone: '' })
    const timer = window.setTimeout(async () => {
      try {
        const available = await api.auth.checkEmail(value)
        if (mine !== seq.current) return
        setEmailAvailable(available)
        setEmailNote(available
          ? { text: '사용할 수 있는 이메일입니다. ✓', tone: 'ok' }
          : { text: '이미 가입된 이메일입니다. ', tone: 'bad', loginLink: true })
      } catch {
        if (mine !== seq.current) return
        setEmailNote({ text: '지금은 중복 확인을 할 수 없어요. 가입할 때 다시 확인합니다.', tone: '' })
      }
    }, 400)
    return () => window.clearTimeout(timer)
  }, [email])

  const pwNote: Note = !password && !password2 ? { text: '', tone: '' }
    : !validPassword(password) ? { text: '영문과 숫자를 포함해 8자 이상으로 입력해 주세요.', tone: 'bad' }
    : password2 && password !== password2 ? { text: '비밀번호가 일치하지 않습니다.', tone: 'bad' }
    : password2 ? { text: '사용할 수 있는 비밀번호입니다.', tone: 'ok' }
    : { text: '', tone: '' }
  const pwClass = (which: 1 | 2) => {
    if (!password && !password2) return ''
    if (which === 1) return validPassword(password) ? 'auth-ok' : 'auth-invalid'
    if (!password2 || !validPassword(password)) return ''
    return password === password2 ? 'auth-ok' : 'auth-invalid'
  }
  const noteClass = (tone: Note['tone']) => 'auth-field-note' + (tone === 'ok' ? ' auth-ok-text' : tone === 'bad' ? ' auth-bad-text' : '')
  const allAgreed = agreed.every(Boolean)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const emailValue = email.trim()
    const nameValue = name.trim()
    const problems: string[] = []
    if (!validEmail(emailValue)) problems.push('이메일을 확인해 주세요.')
    else if (emailAvailable === false) problems.push('이미 가입된 이메일입니다.')
    if (!validPassword(password)) problems.push('비밀번호 조건을 확인해 주세요.')
    else if (password !== password2) problems.push('비밀번호가 일치하지 않습니다.')
    if (!nameValue) problems.push('표시 이름을 입력해 주세요.')
    if (!allAgreed) problems.push('필수 약관에 동의해 주세요.')
    if (problems.length) { setError(problems[0]); return }
    setError('')
    setBusy(true)
    try {
      setAuthUser(await api.auth.signup({ name: nameValue, email: emailValue, password, marketingConsent: marketing }))
      setDone(nameValue)
    } catch (err) {
      setBusy(false)
      if ((err as { code?: string }).code === 'email_taken') setEmailAvailable(false)
      setError(authErrorMessage(err))
    }
  }

  if (done !== null) {
    return (
      <AuthLayout switcher={null}>
        <section className="auth-card">
          <span className="auth-success-badge">✓</span>
          <h1>회원가입이 완료되었습니다</h1>
          <p className="auth-sub"><strong>{done}</strong>님, TrueFit에 오신 걸 환영해요.</p>
          <button type="button" className="auth-btn" onClick={() => navigate('/')}>TrueFit 시작하기 →</button>
        </section>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout switcher={<>이미 계정이 있으신가요? <Link to="/login">로그인</Link></>}>
      <section className="auth-card">
        <span className="auth-eyebrow">GET STARTED · EMAIL</span>
        <h1>이메일로 시작하기</h1>
        <p className="auth-sub">나에게 맞는 컴퓨터 구성을, 계정에 저장하고 이어가세요.</p>
        <form noValidate onSubmit={submit}>
          <div className="auth-field">
            <label htmlFor="tf-signup-email">이메일 *</label>
            <input type="email" id="tf-signup-email" autoComplete="email" placeholder="you@example.com" required
              className={emailNote.tone === 'ok' ? 'auth-ok' : emailNote.tone === 'bad' ? 'auth-invalid' : ''}
              value={email} onChange={e => setEmail(e.target.value)} />
            <p className={noteClass(emailNote.tone)}>
              {emailNote.text}{emailNote.loginLink && <Link to="/login">로그인하기 →</Link>}
            </p>
          </div>
          <div className="auth-two-col">
            <div className="auth-field">
              <label htmlFor="tf-signup-password">비밀번호 *</label>
              <input type="password" id="tf-signup-password" autoComplete="new-password" placeholder="영문·숫자 포함 8자 이상" required
                className={pwClass(1)} value={password} onChange={e => setPassword(e.target.value)} />
            </div>
            <div className="auth-field">
              <label htmlFor="tf-signup-password2">비밀번호 확인 *</label>
              <input type="password" id="tf-signup-password2" autoComplete="new-password" placeholder="비밀번호 재입력" required
                className={pwClass(2)} value={password2} onChange={e => setPassword2(e.target.value)} />
            </div>
          </div>
          <p className={noteClass(pwNote.tone)}>{pwNote.text}</p>
          <div className="auth-field">
            <label htmlFor="tf-signup-name">표시 이름 *</label>
            <input type="text" id="tf-signup-name" placeholder="서비스에서 사용할 이름" maxLength={20} required
              value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div className="auth-terms">
            <label className="auth-term-all">
              <input type="checkbox" checked={allAgreed} onChange={e => setAgreed([e.target.checked, e.target.checked])} />
              <span>전체 동의합니다</span>
            </label>
            {(['이용약관 동의', '개인정보 처리방침 동의'] as const).map((label, i) => (
              <div className="auth-term-item" key={label}>
                <div className="auth-term-row">
                  <label>
                    <input type="checkbox" checked={agreed[i]}
                      onChange={e => setAgreed(prev => prev.map((v, j) => (j === i ? e.target.checked : v)))} />
                    <span><b>[필수]</b> {label}</span>
                  </label>
                  <details>
                    <summary>{TERMS[i].summary}</summary>
                    <div className="auth-term-detail" dangerouslySetInnerHTML={{ __html: TERMS[i].html }} />
                  </details>
                </div>
              </div>
            ))}
            <div className="auth-term-item">
              <div className="auth-term-row">
                <label>
                  <input type="checkbox" checked={marketing} onChange={e => setMarketing(e.target.checked)} />
                  <span>[선택] 마케팅 정보 및 이벤트 수신 동의</span>
                </label>
              </div>
            </div>
          </div>
          <p className="auth-error" role="alert">{error}</p>
          <button type="submit" className="auth-btn" disabled={busy}>{busy ? '가입 중…' : '이메일로 회원가입'}</button>
          <p className="auth-switch">이미 계정이 있으신가요? <Link to="/login">로그인</Link></p>
        </form>
      </section>
    </AuthLayout>
  )
}
