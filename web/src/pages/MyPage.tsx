import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import { api } from '../api'
import { logout, setAuthUser, useAuthUser } from '../state/authStore'
import { useToast } from '../state/ToastContext'
import { authErrorMessage, validPassword } from './auth/messages'
import '../styles/mypage.css'

const joinedText = (iso: string | undefined) => {
  const time = iso ? Date.parse(iso) : NaN
  return Number.isNaN(time) ? '' : new Date(time).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
}

// 계정 정보 보기와 이름·비밀번호 변경, 회원 탈퇴. 모두 서버(/auth/me, /auth/password, /auth/withdraw)가 처리한다.
export default function MyPage() {
  const user = useAuthUser()
  const { showToast } = useToast()
  const navigate = useNavigate()

  const [name, setName] = useState(user?.name ?? '')
  const [nameBusy, setNameBusy] = useState(false)
  const [nameError, setNameError] = useState('')
  const [marketingBusy, setMarketingBusy] = useState(false)

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordError, setPasswordError] = useState('')

  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [withdrawPassword, setWithdrawPassword] = useState('')
  const [withdrawSure, setWithdrawSure] = useState(false)
  const [withdrawBusy, setWithdrawBusy] = useState(false)
  const [withdrawError, setWithdrawError] = useState('')

  useEffect(() => { if (user) setName(user.name) }, [user])

  if (!user) {
    return (
      <PlannerShell>
        <div className="pl-page narrow">
          <h2 className="pl-h2">마이페이지</h2>
          <div className="pl-empty">로그인한 뒤에 볼 수 있어요.</div>
          <div><Link className="pl-btn" style={{ textDecoration: 'none', display: 'inline-block' }} to="/login?next=/mypage">로그인하기</Link></div>
        </div>
      </PlannerShell>
    )
  }

  async function saveName(event: FormEvent) {
    event.preventDefault()
    const clean = name.trim()
    if (!clean) { setNameError('이름을 입력해 주세요.'); return }
    if (clean.length > 20) { setNameError('이름은 20자 이하로 입력해 주세요.'); return }
    if (clean === user?.name) { setNameError('지금 이름과 같아요.'); return }
    setNameBusy(true); setNameError('')
    try {
      setAuthUser(await api.auth.updateProfile({ name: clean }))
      showToast('이름을 바꿨어요.')
    } catch (caught) { setNameError(authErrorMessage(caught)) } finally { setNameBusy(false) }
  }

  async function toggleMarketing(checked: boolean) {
    setMarketingBusy(true)
    try {
      setAuthUser(await api.auth.updateProfile({ marketingConsent: checked }))
      showToast(checked ? '마케팅 정보 수신에 동의했어요.' : '마케팅 정보 수신 동의를 해제했어요.')
    } catch (caught) { showToast(authErrorMessage(caught)) } finally { setMarketingBusy(false) }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault()
    if (!current) { setPasswordError('현재 비밀번호를 입력해 주세요.'); return }
    if (!validPassword(next)) { setPasswordError('새 비밀번호는 영문과 숫자를 포함해 8자 이상이어야 해요.'); return }
    if (next === current) { setPasswordError('현재 비밀번호와 다른 비밀번호로 바꿔 주세요.'); return }
    if (next !== again) { setPasswordError('새 비밀번호가 서로 일치하지 않아요.'); return }
    setPasswordBusy(true); setPasswordError('')
    try {
      await api.auth.changePassword({ currentPassword: current, newPassword: next })
      setCurrent(''); setNext(''); setAgain('')
      showToast('비밀번호를 바꿨어요.')
    } catch (caught) { setPasswordError(authErrorMessage(caught)) } finally { setPasswordBusy(false) }
  }

  async function withdraw(event: FormEvent) {
    event.preventDefault()
    if (!withdrawPassword) { setWithdrawError('비밀번호를 입력해 주세요.'); return }
    if (!withdrawSure) { setWithdrawError('탈퇴하면 되돌릴 수 없다는 안내를 확인해 주세요.'); return }
    setWithdrawBusy(true); setWithdrawError('')
    try {
      await api.auth.withdraw(withdrawPassword)
      await logout().catch(() => undefined)
      showToast('탈퇴했어요. 이용해 주셔서 감사합니다.')
      navigate('/')
    } catch (caught) { setWithdrawError(authErrorMessage(caught)); setWithdrawBusy(false) }
  }

  const joined = joinedText(user.createdAt)
  return (
    <PlannerShell>
      <div className="pl-page mp-page">
        <div className="mp-heading">
          <div className="pl-eyebrow pl-mono">마이페이지</div>
          <h2 className="pl-h2" style={{ fontSize: 26 }}>{user.name} 님</h2>
          <span className="pl-note">{user.email}{joined ? ` · ${joined} 가입` : ''}</span>
        </div>

        <section className="pl-card mp-card">
          <h3>계정 정보</h3>
          <form className="mp-form" onSubmit={saveName} noValidate>
            <label className="pl-field">이메일<input value={user.email} readOnly disabled /></label>
            <label className="pl-field">이름
              <input value={name} maxLength={20} onChange={event => { setName(event.target.value); setNameError('') }} />
            </label>
            {nameError && <div className="pl-alert bad" role="alert">{nameError}</div>}
            <div className="mp-actions"><button type="submit" className="pl-btn" disabled={nameBusy}>{nameBusy ? '저장하는 중…' : '이름 저장'}</button></div>
          </form>
          <label className="mp-check">
            <input type="checkbox" checked={Boolean(user.marketingConsent)} disabled={marketingBusy} onChange={event => void toggleMarketing(event.target.checked)} />
            <span>마케팅 정보 수신에 동의합니다 <small>(선택)</small></span>
          </label>
        </section>

        <section className="pl-card mp-card">
          <h3>비밀번호 변경</h3>
          <form className="mp-form" onSubmit={savePassword} noValidate>
            <label className="pl-field">현재 비밀번호<input type="password" autoComplete="current-password" value={current} onChange={event => { setCurrent(event.target.value); setPasswordError('') }} /></label>
            <label className="pl-field">새 비밀번호<input type="password" autoComplete="new-password" value={next} onChange={event => { setNext(event.target.value); setPasswordError('') }} placeholder="영문·숫자 포함 8자 이상" /></label>
            <label className="pl-field">새 비밀번호 확인<input type="password" autoComplete="new-password" value={again} onChange={event => { setAgain(event.target.value); setPasswordError('') }} /></label>
            {passwordError && <div className="pl-alert bad" role="alert">{passwordError}</div>}
            <div className="mp-actions"><button type="submit" className="pl-btn" disabled={passwordBusy}>{passwordBusy ? '바꾸는 중…' : '비밀번호 변경'}</button></div>
          </form>
        </section>

        <section className="pl-card mp-card mp-danger">
          <h3>회원 탈퇴</h3>
          {!withdrawOpen ? (
            <>
              <p className="pl-note">탈퇴하면 계정 정보가 삭제되고 되돌릴 수 없어요.</p>
              <div className="mp-actions"><button type="button" className="mp-danger-btn" onClick={() => setWithdrawOpen(true)}>탈퇴 진행하기</button></div>
            </>
          ) : (
            <form className="mp-form" onSubmit={withdraw} noValidate>
              <p className="pl-note">본인 확인을 위해 비밀번호를 입력해 주세요. 탈퇴하면 계정 정보가 삭제되고 되돌릴 수 없어요.</p>
              <label className="pl-field">비밀번호<input type="password" autoComplete="current-password" value={withdrawPassword} onChange={event => { setWithdrawPassword(event.target.value); setWithdrawError('') }} /></label>
              <label className="mp-check">
                <input type="checkbox" checked={withdrawSure} onChange={event => { setWithdrawSure(event.target.checked); setWithdrawError('') }} />
                <span>탈퇴하면 되돌릴 수 없다는 점을 확인했어요.</span>
              </label>
              {withdrawError && <div className="pl-alert bad" role="alert">{withdrawError}</div>}
              <div className="mp-actions">
                <button type="button" className="pl-btn ghost" disabled={withdrawBusy} onClick={() => { setWithdrawOpen(false); setWithdrawPassword(''); setWithdrawSure(false); setWithdrawError('') }}>취소</button>
                <button type="submit" className="mp-danger-btn" disabled={withdrawBusy}>{withdrawBusy ? '탈퇴하는 중…' : '회원 탈퇴'}</button>
              </div>
            </form>
          )}
        </section>
      </div>
    </PlannerShell>
  )
}
