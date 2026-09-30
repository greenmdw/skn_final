import { useEffect, useState, type ReactNode } from 'react'
import { api, type ConversationSummary } from '../api'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { planTotal } from '../state/planModel'
import { useSetups } from '../state/SetupsContext'
import { logout, useAuthUser } from '../state/authStore'
import { wonFmt } from '../utils/format'
import '../styles/sidepanel.css'

// 플래너 화면 왼쪽의 접이식 패널: 새 견적 · 작성 중인 견적 · 저장한 견적(견적서 여러 개면 펼침) · 대화 내역 · 사용자/로그아웃.
// 접으면 아이콘만 남는 56px 한 줄이 된다. 대화 내역은 서버 목록(GET /lists) 하나가 대화 하나다
// (docs/개발요청_백엔드_및_타팀.md 10번).
const KEY = 'truefit.sidepanel.collapsed'
type Tab = 'saved' | 'history'
const STAGE_LABEL: Record<ConversationSummary['stage'], string> = {
  category: '시작 전', conditions: '조건 정하는 중', results: '추천 결과', report: '확정',
}

function shortDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const today = new Date()
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' })
}

const Icon = ({ children }: { children: ReactNode }) => (
  <svg className="sp-ico" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
)

// 화면을 옮기면 패널이 새로 그려진다 — 대화 내역에서 대화를 연 뒤에도 같은 탭이 보이게 선택을 기억한다.
const TAB_KEY = 'truefit.sidepanel.tab'
function readTab(): Tab {
  try { return localStorage.getItem(TAB_KEY) === 'history' ? 'history' : 'saved' } catch { return 'saved' }
}

function readCollapsed() {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export default function SidePanel() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [menuOpen, setMenuOpen] = useState(false)
  const user = useAuthUser()
  const { state, resetPlan, openConversation } = usePlan()
  const { savedSetups, loading, storageError, removeSetup } = useSetups()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [tab, setTab] = useState<Tab>(readTab)
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null)
  const [historyError, setHistoryError] = useState('')

  useEffect(() => {
    try { localStorage.setItem(TAB_KEY, tab) } catch { /* 보관 실패는 무시 */ }
  }, [tab])
  // 대화 내역은 탭을 열 때와, 열어 둔 채 화면을 옮길 때(대화가 늘었을 수 있다) 다시 읽는다.
  useEffect(() => {
    if (tab !== 'history') return
    let alive = true
    api.lists.list()
      .then(items => { if (alive) { setConversations(items); setHistoryError('') } })
      .catch(() => { if (alive) setHistoryError('대화 내역을 불러오지 못했어요.') })
    return () => { alive = false }
  }, [tab, pathname, user?.email, savedSetups])

  async function openHistory(item: ConversationSummary) {
    if (item.stage === 'report') { navigate('/report/' + item.listId); return }
    const opened = await openConversation(item.listId, item.stage === 'results')
    if (opened) navigate(opened === 'plan' ? '/plan' : '/start')
  }

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

        <div className="sp-tabs" role="tablist" aria-label="패널 보기">
          <button type="button" role="tab" aria-selected={tab === 'saved'} className={tab === 'saved' ? 'on' : ''} onClick={() => setTab('saved')}>견적</button>
          <button type="button" role="tab" aria-selected={tab === 'history'} className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>대화 내역</button>
        </div>

        {tab === 'history' && (
          <div className="sp-list">
            {historyError && <div className="sp-note bad" role="alert">{historyError}</div>}
            {!historyError && conversations === null && <div className="sp-note">불러오는 중이에요…</div>}
            {conversations?.length === 0 && <div className="sp-note">아직 나눈 대화가 없어요. 새 견적으로 시작해 보세요.</div>}
            {conversations?.map(item => (
              <button type="button" key={item.listId} onClick={() => void openHistory(item)}
                className={'sp-item sp-item-btn' + (state.sessionId === item.listId ? ' on' : '')}>
                <span className="sp-name">{item.firstMessage || item.name}</span>
                <span className="sp-meta">{[STAGE_LABEL[item.stage], item.conditionsSummary, shortDate(item.lastActiveAt)].filter(Boolean).join(' · ')}</span>
              </button>
            ))}
          </div>
        )}

        <div className="sp-list" hidden={tab !== 'saved'}>
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
            const reports = setup.reports ?? []
            const openVersion = pathname === to ? Number(new URLSearchParams(search).get('v')) || setup.revisionNo : null
            return (
              <div key={setup.id}>
                <div className={'sp-item with-del' + (pathname === to && reports.length < 2 ? ' on' : '')}>
                  <Link to={to} className="sp-item-link">
                    <span className="sp-name">{setup.title}</span>
                    <span className="sp-meta">{[wonFmt(planTotal(setup.plan)), setup.date, `부품 ${setup.plan.items.length}개`,
                      reports.length > 1 ? `견적서 ${reports.length}개` : ''].filter(Boolean).join(' · ')}</span>
                  </Link>
                  <button type="button" className="sp-del" aria-label={`${setup.title} 삭제`} onClick={() => void remove(setup.id, setup.title)}>삭제</button>
                </div>
                {reports.length > 1 && [...reports].reverse().map(report => (
                  <Link key={report.revisionNo} to={`${to}?v=${report.revisionNo}`}
                    className={'sp-item sp-sub' + (openVersion === report.revisionNo ? ' on' : '')}>
                    <span className="sp-name">견적서 {report.revisionNo} · {report.name}</span>
                    <span className="sp-meta">{[wonFmt(report.total), `부품 ${report.itemCount}개`, shortDate(report.confirmedAt)].join(' · ')}</span>
                  </Link>
                ))}
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
