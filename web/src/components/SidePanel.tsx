import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { planTotal } from '../state/planModel'
import { useSetups } from '../state/SetupsContext'
import { logout, useAuthUser } from '../state/authStore'
import { wonFmt } from '../utils/format'
import '../styles/sidepanel.css'

// 플래너 화면 왼쪽의 접이식 패널: 새 견적 · 작성 중인 견적 · 저장한 견적 · 사용자/로그아웃.
// 접으면 아이콘만 남는 56px 한 줄이 된다. 서버가 견적별 대화 제목·견적서 묶음을 주지 않으므로 그 부분은 만들지 않는다
// (docs/개발요청_백엔드_및_타팀.md 10번 참고).
const KEY = 'truefit.sidepanel.collapsed'

const Icon = ({ children }: { children: ReactNode }) => (
  <svg className="sp-ico" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
)

function readCollapsed() {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export default function SidePanel() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [menuOpen, setMenuOpen] = useState(false)
  const user = useAuthUser()
  const { state, resetPlan } = usePlan()
  const { savedSetups, loading, storageError, removeSetup } = useSetups()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  useEffect(() => {
    try { localStorage.setItem(KEY, collapsed ? '1' : '0') } catch { /* 보관 실패는 무시 */ }
  }, [collapsed])
  useEffect(() => {
    if (!menuOpen) return
    const close = () => setMenuOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menuOpen])

  const inProgress = state.stage > 0 && (state.sessionId !== null || state.currentPlan !== null)
  const inProgressTitle = state.currentPlan ? '작성 중인 견적' : '조건 대화 중'
  const inProgressMeta = [state.budget ? wonFmt(state.budget) : '', state.currentPlan ? '추천 결과' : '조건 정하는 중'].filter(Boolean).join(' · ')
  const inProgressTo = state.currentPlan ? '/plan' : '/start'

  function startNew() {
    resetPlan()
    navigate('/start')
  }
  async function remove(id: string, title: string) {
    if (window.confirm(`“${title}” 견적을 삭제할까요? 되돌릴 수 없어요.`)) await removeSetup(id)
  }

  return (
    <aside className={'sp-root' + (collapsed ? ' collapsed' : '')} aria-label="견적 패널">
      <div className="sp-inner">
        <div className="sp-head">
          <button type="button" className="sp-row icon-only" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? '패널 펴기' : '패널 접기'} aria-expanded={!collapsed}>
            <Icon><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Icon>
          </button>
        </div>

        <div className="sp-menu">
          <button type="button" className="sp-row new" onClick={startNew} title="새 견적">
            <Icon><path d="M12 5v14M5 12h14" /></Icon><span className="sp-lbl">새 견적 (새 대화)</span>
          </button>
          <button type="button" className="sp-row" onClick={() => setCollapsed(false)} title="저장한 견적" hidden={!collapsed}>
            <Icon><path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /></Icon>
          </button>
        </div>

        <div className="sp-list">
          {inProgress && (
            <>
              <div className="sp-group">진행 중</div>
              <Link to={inProgressTo} className={'sp-item' + (pathname === inProgressTo ? ' on' : '')}>
                <span className="sp-name">{inProgressTitle}</span>
                {inProgressMeta && <span className="sp-meta">{inProgressMeta}</span>}
              </Link>
            </>
          )}

          <div className="sp-group">저장한 견적{user && savedSetups.length > 0 ? ` · ${savedSetups.length}` : ''}</div>
          {!user && (
            <div className="sp-note">
              저장한 견적은 로그인한 계정에만 있어요.{' '}
              <Link to={`/login?next=${encodeURIComponent(pathname)}`}>로그인하기 →</Link>
            </div>
          )}
          {storageError && <div className="sp-note bad" role="alert">{storageError}</div>}
          {user && loading && <div className="sp-note">불러오는 중이에요…</div>}
          {user && !loading && savedSetups.length === 0 && !storageError && (
            <div className="sp-note">아직 확정한 견적이 없어요. 추천을 받고 장바구니에서 확정하면 여기에 저장돼요.</div>
          )}
          {savedSetups.map(setup => {
            const to = '/report/' + setup.id
            return (
              <div key={setup.id} className={'sp-item with-del' + (pathname === to ? ' on' : '')}>
                <Link to={to} className="sp-item-link">
                  <span className="sp-name">{setup.title}</span>
                  <span className="sp-meta">{[wonFmt(planTotal(setup.plan)), setup.date, `부품 ${setup.plan.items.length}개`].filter(Boolean).join(' · ')}</span>
                </Link>
                <button type="button" className="sp-del" aria-label={`${setup.title} 삭제`} onClick={() => void remove(setup.id, setup.title)}>삭제</button>
              </div>
            )
          })}
        </div>

        <div className="sp-user">
          {menuOpen && (
            <div className="sp-pop" onClick={event => event.stopPropagation()}>
              {user
                ? <button type="button" className="out" onClick={() => { setMenuOpen(false); void logout() }}>로그아웃</button>
                : <Link to={`/login?next=${encodeURIComponent(pathname)}`}>로그인</Link>}
            </div>
          )}
          <button type="button" className="sp-row who" title={user ? `${user.name} 님` : '게스트'}
            onClick={event => { event.stopPropagation(); setMenuOpen(o => !o) }} aria-haspopup="menu" aria-expanded={menuOpen}>
            <span className="sp-avatar">{(user?.name ?? '게').slice(0, 1)}</span>
            <span className="sp-lbl sp-who"><b>{user ? `${user.name} 님` : '게스트'}</b><small>{user ? '로그인됨' : '로그인하지 않음'}</small></span>
          </button>
        </div>
      </div>
    </aside>
  )
}
