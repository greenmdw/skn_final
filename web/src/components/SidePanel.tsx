import { useEffect, useState, type ReactNode } from 'react'
import { api, errorMessage, type ConversationSummary } from '../api'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { planTotal } from '../state/planModel'
import { useSetups } from '../state/SetupsContext'
import { useToast } from '../state/ToastContext'
import { logout, useAuthUser } from '../state/authStore'
import { wonFmt } from '../utils/format'
import '../styles/sidepanel.css'

// 플래너 화면 왼쪽의 접이식 패널: 새 견적 · 작성 중인 견적 · 저장한 견적(견적서 여러 개면 펼침) · 대화 내역 · 사용자/로그아웃.
// 접으면 아이콘만 남는 56px 한 줄이 된다. 대화 내역은 서버 목록(GET /lists) 하나가 대화 하나다.
const KEY = 'truefit.sidepanel.collapsed'
type Tab = 'saved' | 'history'
// 서버는 제목을 안 정한 대화를 "컴퓨터 장바구니"로 내려 준다 — 그건 제목이 아니라 자리표시라 첫 사용자 말로 대신한다.
const DEFAULT_TITLE = '컴퓨터 장바구니'
const conversationTitle = (item: ConversationSummary) => (item.name && item.name !== DEFAULT_TITLE ? item.name : item.firstMessage || item.name)

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

// 대화 내역을 마지막 활동 시점으로 묶는 제목. 자정 기준 날짜 차이로 나누고, 30일이 지나면 월별(예: 2026년 8월)로 나눈다.
function dateGroup(iso: string | null): string {
  if (!iso) return '날짜 없음'
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86400000)
  if (days <= 0) return '오늘'
  if (days === 1) return '어제'
  if (days <= 7) return '지난 7일'
  if (days <= 30) return '지난 30일'
  const date = new Date(iso)
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월`
}

function groupConversations(items: ConversationSummary[]): { label: string; items: ConversationSummary[] }[] {
  const sorted = [...items].sort((a, b) => (b.lastActiveAt ?? '').localeCompare(a.lastActiveAt ?? ''))
  const groups: { label: string; items: ConversationSummary[] }[] = []
  for (const item of sorted) {
    const label = dateGroup(item.lastActiveAt)
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.items.push(item)
    else groups.push({ label, items: [item] })
  }
  return groups
}

const Icon = ({ children }: { children: ReactNode }) => (
  <svg className="sp-ico" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
)

// 화면을 옮기면 패널이 새로 그려진다 — 대화 내역에서 대화를 연 뒤에도 같은 탭이 보이게 선택을 기억한다.
const TAB_KEY = 'truefit.sidepanel.tab'
function readTab(): Tab {
  try { return localStorage.getItem(TAB_KEY) === 'saved' ? 'saved' : 'history' } catch { return 'history' }
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
  const { showToast } = useToast()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [tab, setTab] = useState<Tab>(readTab)
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null)
  const [historyError, setHistoryError] = useState('')
  // 견적서를 펼친 견적(목록 id). 지금 보고 있는 리포트의 견적은 처음부터 펼쳐 둔다.
  const [opened, setOpened] = useState<Set<string>>(new Set())
  const toggle = (id: string) => setOpened(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  // 대화 한 줄의 ⋯ 메뉴와 제목 바꾸기(입력 중인 줄)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const viewingId = pathname.startsWith('/report/') ? pathname.slice('/report/'.length) : null
  const isOpen = (id: string) => opened.has(id) || id === viewingId
  const viewingVersion = Number(new URLSearchParams(search).get('v')) || null

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
    if (!menuFor) return
    const close = () => setMenuFor(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menuFor])
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

  function startRename(item: ConversationSummary) {
    setMenuFor(null)
    setDraft(conversationTitle(item) ?? '')
    setEditingId(item.listId)
  }
  async function commitRename(item: ConversationSummary) {
    const name = draft.trim().slice(0, 60)
    setEditingId(null)
    if (!name || name === conversationTitle(item)) return
    try {
      await api.lists.rename(item.listId, name)
      setConversations(prev => prev && prev.map(row => (row.listId === item.listId ? { ...row, name } : row)))
    } catch (error) {
      showToast(errorMessage(error, '제목을 바꾸지 못했습니다. 잠시 후 다시 시도해주세요.'))
    }
  }
  async function removeConversation(item: ConversationSummary) {
    setMenuFor(null)
    const title = conversationTitle(item) ?? '이 대화'
    const sheets = item.reports.length > 0 ? ` 저장한 견적서 ${item.reports.length}개도 함께 지워져요.` : ''
    if (!window.confirm(`“${title}” 대화를 삭제할까요?${sheets} 되돌릴 수 없어요.`)) return
    try {
      // 확정한 견적이면 저장한 견적 목록도 함께 갱신되게 setups 쪽 삭제를 쓴다(같은 DELETE /lists/{id}).
      if (savedSetups.some(setup => setup.id === item.listId)) await removeSetup(item.listId)
      else await api.lists.remove(item.listId)
      setConversations(prev => prev && prev.filter(row => row.listId !== item.listId))
      // 지금 열어 둔 대화나 리포트를 지웠으면 빈 새 견적으로 돌아간다.
      if (state.sessionId === item.listId || viewingId === item.listId) { resetPlan(); navigate('/start') }
    } catch (error) {
      showToast(errorMessage(error, '삭제하지 못했습니다. 잠시 후 다시 시도해주세요.'))
    }
  }

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
          <button type="button" role="tab" aria-selected={tab === 'history'} className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>대화 내역</button>
          <button type="button" role="tab" aria-selected={tab === 'saved'} className={tab === 'saved' ? 'on' : ''} onClick={() => setTab('saved')}>견적</button>
        </div>

        {tab === 'history' && (
          <div className="sp-list">
            {historyError && <div className="sp-note bad" role="alert">{historyError}</div>}
            {!historyError && conversations === null && <div className="sp-note">불러오는 중이에요…</div>}
            {conversations?.length === 0 && <div className="sp-note">아직 나눈 대화가 없어요. 새 견적으로 시작해 보세요.</div>}
            {conversations && groupConversations(conversations).map(group => (
              <div key={group.label}>
                <div className="sp-group">{group.label}</div>
                {group.items.map(item => (
                  <div key={item.listId}>
                    <div className={'sp-item sp-conv' + (state.sessionId === item.listId ? ' on' : '')}>
                      {item.reports.length > 0
                        ? <button type="button" className={'sp-chev' + (isOpen(item.listId) ? ' open' : '')} aria-label={isOpen(item.listId) ? '견적서 접기' : '견적서 펼치기'}
                          aria-expanded={isOpen(item.listId)} onClick={() => toggle(item.listId)}>▶</button>
                        : <span className="sp-chev none" aria-hidden="true">▶</span>}
                      {editingId === item.listId ? (
                        <input className="sp-rename" value={draft} maxLength={60} autoFocus aria-label="대화 제목"
                          onChange={event => setDraft(event.target.value)} onFocus={event => event.target.select()}
                          onKeyDown={event => { if (event.key === 'Enter') void commitRename(item); if (event.key === 'Escape') setEditingId(null) }}
                          onBlur={() => void commitRename(item)} />
                      ) : (
                        <button type="button" className="sp-conv-main" onClick={() => void openHistory(item)}>
                          <span className="sp-name">{conversationTitle(item)}</span>
                          <span className="sp-meta">{[STAGE_LABEL[item.stage], shortDate(item.lastActiveAt)].filter(Boolean).join(' · ')}</span>
                        </button>
                      )}
                      {item.reports.length > 0 && editingId !== item.listId && <span className="sp-count">견적서 {item.reports.length}</span>}
                      {editingId !== item.listId && (
                        <button type="button" className="sp-more" aria-label={`${conversationTitle(item)} 메뉴`} aria-haspopup="menu" aria-expanded={menuFor === item.listId}
                          onClick={event => { event.stopPropagation(); setMenuFor(menuFor === item.listId ? null : item.listId) }}>⋯</button>
                      )}
                      {menuFor === item.listId && (
                        <div className="sp-rowmenu" role="menu" onClick={event => event.stopPropagation()}>
                          <button type="button" role="menuitem" onClick={() => startRename(item)}>제목 바꾸기</button>
                          <button type="button" role="menuitem" className="out" onClick={() => void removeConversation(item)}>삭제</button>
                        </div>
                      )}
                    </div>
                    {item.reports.length > 0 && isOpen(item.listId) && [...item.reports].reverse().map(report => (
                      <Link key={report.revisionNo} to={`/report/${item.listId}?v=${report.revisionNo}`}
                        className={'sp-item sp-sub' + (viewingId === item.listId && (viewingVersion ?? item.reports[item.reports.length - 1].revisionNo) === report.revisionNo ? ' on' : '')}>
                        <span className="sp-name">견적서 {report.revisionNo} · {report.name}</span>
                        <span className="sp-meta">{[wonFmt(report.total), `부품 ${report.itemCount}개`, shortDate(report.confirmedAt)].join(' · ')}</span>
                      </Link>
                    ))}
                  </div>
                ))}
              </div>
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
                  {reports.length > 1 && (
                    <button type="button" className={'sp-chev sp-chev-abs' + (isOpen(setup.id) ? ' open' : '')} aria-label={isOpen(setup.id) ? '견적서 접기' : '견적서 펼치기'}
                      aria-expanded={isOpen(setup.id)} onClick={() => toggle(setup.id)}>▶</button>
                  )}
                  <button type="button" className="sp-del" aria-label={`${setup.title} 삭제`} onClick={() => void remove(setup.id, setup.title)}>삭제</button>
                </div>
                {reports.length > 1 && isOpen(setup.id) && [...reports].reverse().map(report => (
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
