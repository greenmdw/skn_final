import { useEffect, useState, type FormEvent } from 'react'
import { api, type AuthUser } from '../../api'
import { setAuthUser } from '../../state/authStore'
import { useToast } from '../../state/ToastContext'
import { authErrorMessage, validPassword } from '../auth/messages'
import { Hero } from './parts'
import { dateText } from './model'

// 내 정보 관리: 이름·마케팅 동의·비밀번호 변경·회원 탈퇴. 모두 서버(/auth/me, /auth/password, /auth/withdraw)가 처리한다.
export default function ProfilePage({ user, onWithdraw }: { user: AuthUser; onWithdraw: () => void }) {
  const { showToast } = useToast()
  const [name, setName] = useState(user.name)
  const [editingName, setEditingName] = useState(false)
  const [nameBusy, setNameBusy] = useState(false)
  const [nameError, setNameError] = useState('')
  const [marketingBusy, setMarketingBusy] = useState(false)

  const [passwordOpen, setPasswordOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordError, setPasswordError] = useState('')

  useEffect(() => { setName(user.name) }, [user.name])

  async function saveName(event: FormEvent) {
    event.preventDefault()
    const clean = name.trim()
    if (!clean) { setNameError('이름을 입력해 주세요.'); return }
    if (clean.length > 20) { setNameError('이름은 20자 이하로 입력해 주세요.'); return }
    if (clean === user.name) { setEditingName(false); setNameError(''); return }
    setNameBusy(true); setNameError('')
    try {
      setAuthUser(await api.auth.updateProfile({ name: clean }))
      setEditingName(false)
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
      setCurrent(''); setNext(''); setAgain(''); setPasswordOpen(false)
      showToast('비밀번호를 바꿨어요.')
    } catch (caught) { setPasswordError(authErrorMessage(caught)) } finally { setPasswordBusy(false) }
  }

  return (
    <>
      <Hero icon="👤" title="내 정보 관리" description="계정 정보를 확인하고 이름·비밀번호를 바꿀 수 있어요." />
      <section className="mp-section">
        <div className="mp-profile-card">
          <div className="mp-form-row">
            <b>이름</b>
            {editingName ? (
              <form className="mp-inline" onSubmit={saveName} noValidate>
                <input className="mp-input" value={name} maxLength={20} autoFocus disabled={nameBusy} aria-label="이름"
                  onChange={event => { setName(event.target.value); setNameError('') }} />
                <button className="mp-btn primary" type="submit" disabled={nameBusy}>{nameBusy ? '저장 중…' : '저장'}</button>
                <button className="mp-btn" type="button" disabled={nameBusy} onClick={() => { setEditingName(false); setName(user.name); setNameError('') }}>취소</button>
              </form>
            ) : <span>{user.name}</span>}
            {!editingName && <button className="mp-btn" type="button" onClick={() => setEditingName(true)}>수정</button>}
            {editingName && <i />}
          </div>
          {nameError && <div className="mp-alert" role="alert" style={{ margin: '0 20px 14px' }}>{nameError}</div>}
          <div className="mp-form-row"><b>이메일</b><span>{user.email}</span><i /></div>
          <div className="mp-form-row"><b>가입일</b><span>{dateText(user.createdAt) || '확인할 수 없어요'}</span><i /></div>
          <div className="mp-form-row">
            <b>마케팅 정보 수신</b>
            <label className="mp-check">
              <input type="checkbox" checked={Boolean(user.marketingConsent)} disabled={marketingBusy} onChange={event => void toggleMarketing(event.target.checked)} />
              <span>이벤트·혜택 안내를 받아요 (선택)</span>
            </label>
            <i />
          </div>
          <div className="mp-form-row">
            <b>비밀번호</b><span>{passwordOpen ? '새 비밀번호를 입력해 주세요.' : '주기적으로 바꾸면 계정을 더 안전하게 지킬 수 있어요.'}</span>
            <button className="mp-btn" type="button" onClick={() => { setPasswordOpen(open => !open); setPasswordError('') }}>{passwordOpen ? '닫기' : '변경'}</button>
          </div>
          {passwordOpen && (
            <form className="mp-pw-form" onSubmit={savePassword} noValidate>
              <label>현재 비밀번호<input className="mp-input" type="password" autoComplete="current-password" value={current} onChange={event => { setCurrent(event.target.value); setPasswordError('') }} /></label>
              <label>새 비밀번호<input className="mp-input" type="password" autoComplete="new-password" placeholder="영문·숫자 포함 8자 이상" value={next} onChange={event => { setNext(event.target.value); setPasswordError('') }} /></label>
              <label>새 비밀번호 확인<input className="mp-input" type="password" autoComplete="new-password" value={again} onChange={event => { setAgain(event.target.value); setPasswordError('') }} /></label>
              {passwordError && <div className="mp-alert" role="alert">{passwordError}</div>}
              <div><button className="mp-btn primary" type="submit" disabled={passwordBusy}>{passwordBusy ? '바꾸는 중…' : '비밀번호 변경'}</button></div>
            </form>
          )}
        </div>
      </section>
      <section className="mp-danger">
        <div><h2>회원 탈퇴</h2><p>계정과 모든 활동 데이터를 영구적으로 삭제합니다.</p></div>
        <button type="button" onClick={onWithdraw}>회원 탈퇴</button>
      </section>
    </>
  )
}
