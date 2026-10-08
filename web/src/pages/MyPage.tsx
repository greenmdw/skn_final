import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import MarketingHeader from '../components/MarketingHeader'
import Modal from '../components/Modal'
import { logout, useAuthUser } from '../state/authStore'
import { useSetups } from '../state/SetupsContext'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import { authErrorMessage } from './auth/messages'
import Dashboard from './mypage/Dashboard'
import { ConfigsPage, ConsultsPage, ReportsPage } from './mypage/ListPages'
import MyPcPage from './mypage/MyPcPage'
import ProfilePage from './mypage/ProfilePage'
import { NAV, type MyPageId } from './mypage/nav'
import { PC_FIELDS, configKey, dateText, pcQuestion, readMyPc, reportPath, setupSpecs, setupTotal, writeMyPc, type MyPc, type PcParts } from './mypage/model'
import '../styles/mypage.css'

const PAGE_IDS = NAV.flatMap(item => (item === 'separator' ? [] : [item[0]]))
const isPage = (value: string | null): value is MyPageId => PAGE_IDS.includes(value as MyPageId)

function ConfigDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { savedSetups } = useSetups()
  const setup = id ? savedSetups.find(item => configKey(item) === id) : undefined
  return (
    <Modal open={Boolean(setup)} onClose={onClose} className="mp-dialog mp-dialog-sm">
      {setup && (
        <div className="mp-dialog-body">
          <header className="mp-dialog-head">
            <div><h2>{setup.title} 상세 구성</h2><p>{dateText(setup.savedAt)} 확정 · 합계 {wonFmt(setupTotal(setup))}</p></div>
            <button className="mp-close" type="button" onClick={onClose} aria-label="닫기">×</button>
          </header>
          <div className="mpx-spec-grid">
            {setupSpecs(setup).map(([label, value], index) => <div key={label + index}><small>{label}</small>{value}</div>)}
          </div>
          <div className="mp-dialog-actions">
            <Link className="mp-btn mp-link-btn" to={reportPath(setup)}>리포트 열기</Link>
            <button className="mp-btn primary" type="button" onClick={onClose}>닫기</button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function WithdrawDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { showToast } = useToast()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { if (!open) { setPassword(''); setSure(false); setBusy(false); setError('') } }, [open])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) { setError('비밀번호를 입력해 주세요.'); return }
    if (!sure) { setError('탈퇴하면 되돌릴 수 없다는 안내를 확인해 주세요.'); return }
    setBusy(true); setError('')
    try {
      await api.auth.withdraw(password)
      await logout().catch(() => undefined)
      showToast('탈퇴했어요. 이용해 주셔서 감사합니다.')
      navigate('/')
    } catch (caught) { setError(authErrorMessage(caught)); setBusy(false) }
  }

  return (
    <Modal open={open} onClose={onClose} className="mp-dialog mp-dialog-sm">
      <form className="mp-dialog-body" onSubmit={submit} noValidate>
        <header className="mp-dialog-head">
          <div><h2>회원 탈퇴</h2><p>TrueFit 계정을 탈퇴하시겠어요?</p></div>
          <button className="mp-close" type="button" onClick={onClose} aria-label="닫기">×</button>
        </header>
        <div className="mp-danger" style={{ marginTop: 18 }}>
          <div><h2>복구할 수 없어요</h2><p>탈퇴하면 저장한 PC 구성, AI 상담 기록, 추천 리포트가 모두 삭제되며 복구할 수 없습니다.</p></div>
        </div>
        <label style={{ display: 'grid', gap: 6, marginTop: 16, fontWeight: 700, fontSize: 13 }}>본인 확인을 위해 비밀번호를 입력해 주세요
          <input className="mp-input" type="password" autoComplete="current-password" value={password} disabled={busy}
            onChange={event => { setPassword(event.target.value); setError('') }} />
        </label>
        <label className="mp-check" style={{ marginTop: 12 }}>
          <input type="checkbox" checked={sure} disabled={busy} onChange={event => { setSure(event.target.checked); setError('') }} />
          <span>탈퇴하면 되돌릴 수 없다는 점을 확인했어요.</span>
        </label>
        {error && <div className="mp-alert" role="alert">{error}</div>}
        <div className="mp-dialog-actions">
          <button className="mp-btn" type="button" disabled={busy} onClick={onClose}>취소</button>
          <button className="mp-btn" type="submit" disabled={busy} style={{ color: '#fff', background: 'var(--bad)', borderColor: 'var(--bad)' }}>{busy ? '탈퇴하는 중…' : '탈퇴하기'}</button>
        </div>
      </form>
    </Modal>
  )
}

// My TrueFit: 왼쪽 메뉴 + 화면들. 구성·리포트·상담 기록은 서버에 저장된 내 견적 데이터를 그대로 보여 준다.
export default function MyPage() {
  const user = useAuthUser()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const page: MyPageId = isPage(params.get('tab')) ? (params.get('tab') as MyPageId) : 'dashboard'
  const [configId, setConfigId] = useState<string | null>(null)
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const mainRef = useRef<HTMLElement>(null)

  const email = user?.email ?? ''
  const [myPc, setMyPc] = useState<MyPc | null>(() => (email ? readMyPc(email) : null))
  useEffect(() => { setMyPc(email ? readMyPc(email) : null) }, [email])
  useEffect(() => { mainRef.current?.scrollTo({ top: 0 }) }, [page])

  const go = (next: MyPageId) => setParams(next === 'dashboard' ? {} : { tab: next })

  function registerPc(parts: PcParts, source: string, title: string): boolean {
    const clean: PcParts = {}
    for (const [key] of PC_FIELDS) { const value = (parts[key] ?? '').trim(); if (value) clean[key] = value }
    if (!Object.keys(clean).length) { showToast('부품을 한 가지 이상 입력해 주세요.'); return false }
    const next: MyPc = { parts: clean, source, title, savedAt: new Date().toISOString() }
    writeMyPc(email, next); setMyPc(next)
    showToast('내 현재 PC로 등록했어요.')
    return true
  }
  function resetPc() {
    if (!window.confirm('등록한 내 현재 PC를 삭제할까요?')) return
    writeMyPc(email, null); setMyPc(null)
    showToast('내 현재 PC를 삭제했어요.')
  }
  function usePc() {
    if (!myPc) return
    showToast('내 PC 구성을 견적 점검 질문에 넣어 두었어요.')
    navigate('/check', { state: { question: pcQuestion(myPc) } })
  }

  if (!user) {
    return (
      <div className="mp-root">
        <MarketingHeader />
        <div className="mp-page" style={{ margin: 'auto' }}>
          <div className="mp-section">
            <div className="mp-empty-card">
              <strong>마이페이지는 로그인한 뒤에 볼 수 있어요</strong>
              <span>저장한 구성과 상담 기록, 리포트를 한곳에서 모아 볼 수 있어요.</span>
              <Link className="mp-btn primary mp-link-btn" to="/login?next=/mypage">로그인하기</Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const pages: Record<MyPageId, React.ReactNode> = {
    dashboard: <Dashboard user={user} myPc={myPc} go={go} openConfig={setConfigId} />,
    mypc: <MyPcPage myPc={myPc} onRegister={registerPc} onReset={resetPc} onUse={usePc} />,
    configs: <ConfigsPage openConfig={setConfigId} />,
    consults: <ConsultsPage />,
    reports: <ReportsPage />,
    profile: <ProfilePage user={user} onWithdraw={() => setWithdrawOpen(true)} />,
  }

  return (
    <div className="mp-root">
      <MarketingHeader />
      <section className="mypage-shell" aria-label="My TrueFit 마이페이지">
        <aside className="mp-sidebar">
          <h2>My TrueFit</h2>
          <nav className="mp-nav" aria-label="마이페이지 메뉴">
            {NAV.map(item => (item === 'separator'
              ? <span className="mp-separator" aria-hidden="true" key="sep" />
              : (
                <button key={item[0]} className={page === item[0] ? 'on' : ''} type="button" aria-current={page === item[0] ? 'page' : undefined} onClick={() => go(item[0])}>
                  <span className="mp-icon">{item[1]}</span>{item[2]}
                </button>
              )))}
          </nav>
        </aside>
        <main className="mp-main" ref={mainRef}>
          <div className="mp-page">{pages[page]}</div>
        </main>
      </section>
      <ConfigDialog id={configId} onClose={() => setConfigId(null)} />
      <WithdrawDialog open={withdrawOpen} onClose={() => setWithdrawOpen(false)} />
    </div>
  )
}
