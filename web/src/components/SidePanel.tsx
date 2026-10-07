import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode, type TouchEvent as ReactTouchEvent } from 'react'
import { api, errorMessage, type ConversationSummary, type ReportSummary } from '../api'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { useSetups } from '../state/SetupsContext'
import { useToast } from '../state/ToastContext'
import { isCheckSession } from '../utils/checkSessions'
import { useRemoveSheet } from '../state/useRemoveSheet'
import { logout, useAuthUser } from '../state/authStore'
import { compactWon, dateGroup, fullDate, shortDate } from '../utils/format'
import ResizeHandle, { usePanelWidth } from './ResizeHandle'
import '../styles/sidepanel.css'

// 플래너 화면 왼쪽의 접이식 패널: 새 견적 · 대화 내역 · 저장한 견적 · 사용자/로그아웃.
// 접으면 아이콘만 남는 56px 한 줄이 되고, 아이콘에 마우스를 올리면 이름이 뜬다. 대화 내역은 서버 목록(GET /lists) 하나가 대화 하나이고,
// 저장한 견적은 그 안의 견적서를 대화별로 묶지 않고 시간 순으로 한 줄씩 나열한다(날짜·가격 정렬, 종류 필터).
// 대화와 견적서의 이름 바꾸기·삭제는 행을 우클릭(터치는 0.5초 길게 누르기)하면 뜨는 메뉴로 한다.
// 견적서에 주변기기 개수를 보여 주는 것도 서버가 값을 줄 때 붙인다 — 지금은 본체 부품 수만 있다.
const KEY = 'truefit.sidepanel.collapsed'
// 펼친 폭: 끌어서 조절한다(기본 288px, 240~400px). 접으면 56px 한 줄로 고정이다.
const PANEL_WIDTH = { key: 'truefit.sidepanel.width', initial: 288, min: 240, max: 400 }
type Tab = 'saved' | 'history'
type SortKey = 'date' | 'price'
/** 저장한 견적의 한 줄 — 어느 대화(listId)의 몇 번째 견적서인지 함께 든다 */
interface Sheet { listId: string; report: ReportSummary; latestRevisionNo: number }
/** 우클릭 메뉴가 가리키는 행: 대화 하나, 또는 그 대화의 견적서 하나 */
type CtxTarget = { kind: 'conv'; listId: string } | { kind: 'sheet'; listId: string; revisionNo: number }
const sameTarget = (a: CtxTarget | undefined, b: CtxTarget) => !!a && a.kind === b.kind && a.listId === b.listId && (a.kind === 'conv' || (b.kind === 'sheet' && a.revisionNo === b.revisionNo))
// 서버는 제목을 안 정한 대화를 "컴퓨터 장바구니"로 내려 준다 — 그건 제목이 아니라 자리표시라 첫 사용자 말로 대신한다.
const DEFAULT_TITLE = '컴퓨터 장바구니'
const conversationTitle = (item: ConversationSummary) => (item.name && item.name !== DEFAULT_TITLE ? item.name : item.firstMessage || item.name)

// 확정한 대화는 단계 이름을 적지 않는다(견적서가 있다는 것은 옆의 문서 아이콘과 숫자로 보인다).
const STAGE_LABEL: Record<ConversationSummary['stage'], string> = {
  category: '시작 전', conditions: '조건 정하는 중', results: '추천 결과', report: '',
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
const DocIcon = ({ size = 17, lines = false }: { size?: number; lines?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={lines ? 1.8 : 2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" />{lines && <path d="M9 13h6M9 17h6" />}
  </svg>
)

interface RowHandlers {
  onContextMenu: (event: ReactMouseEvent<HTMLElement>) => void
  onTouchStart: (event: ReactTouchEvent<HTMLElement>) => void
  onTouchMove: (event: ReactTouchEvent<HTMLElement>) => void
  onTouchEnd: () => void
  onTouchCancel: () => void
}
interface SheetEdit { draft: string; onChange: (value: string) => void; onCommit: () => void; onCancel: () => void }

// 견적서 한 줄: 문서 아이콘 · 저장할 때 정한 이름 · 부품 수와 시각 · 오른쪽 금액. 대화 아래에 세로선으로 이어진다.
// 우클릭/길게 누르기 메뉴(handlers)로 이름 바꾸기·삭제를 한다. 이름을 바꾸는 동안에는 링크가 아니라 입력창이 된다.
function SheetRow({ listId, report, active, menuOpen, handlers, edit, onLinkClick }: {
  listId: string; report: ReportSummary; active: boolean; menuOpen: boolean; handlers: RowHandlers
  edit: SheetEdit | null
  /** 길게 누른 손을 뗄 때 생기는 클릭이 리포트를 열지 않게 막는다 */
  onLinkClick: (event: ReactMouseEvent<HTMLElement>) => void
}) {
  const meta = [report.itemCount > 0 ? `부품 ${report.itemCount}` : '', report.peripheralCount ? `주변기기 ${report.peripheralCount}` : '', shortDate(report.confirmedAt)].filter(Boolean).join(' · ')
  const cls = 'sp-sheet' + (active ? ' on' : '') + (menuOpen ? ' ctx' : '')
  const body = (
    <>
      <span className="sp-sheet-ico"><DocIcon size={16} lines /></span>
      <span className="sp-sheet-main">
        {edit
          ? <input className="sp-rename" value={edit.draft} maxLength={60} autoFocus aria-label="견적서 이름"
            onChange={event => edit.onChange(event.target.value)} onFocus={event => event.target.select()}
            onKeyDown={event => { if (event.key === 'Enter') edit.onCommit(); if (event.key === 'Escape') edit.onCancel() }}
            onBlur={edit.onCommit} />
          : <span className="sp-name">{report.name}</span>}
        <span className="sp-meta">{meta}</span>
      </span>
      {!edit && <span className="sp-sheet-price">{compactWon(report.total)}</span>}
    </>
  )
  if (edit) return <div className={cls + ' editing'} {...handlers}>{body}</div>
  return <Link to={`/report/${listId}?v=${report.revisionNo}`} className={cls} onClick={onLinkClick} {...handlers}>{body}</Link>
}

// 화면을 옮기면 패널이 새로 그려진다 — 대화를 연 뒤에도 같은 보기(대화 내역 / 저장한 견적)가 보이게 선택을 기억한다.
const TAB_KEY = 'truefit.sidepanel.tab'
function readTab(): Tab {
  try { return localStorage.getItem(TAB_KEY) === 'saved' ? 'saved' : 'history' } catch { return 'history' }
}

function readCollapsed() {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

const LONG_PRESS_MS = 500

export default function SidePanel() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const size = usePanelWidth(PANEL_WIDTH.key, PANEL_WIDTH.initial, PANEL_WIDTH.min, PANEL_WIDTH.max)
  const [menuOpen, setMenuOpen] = useState(false)
  const user = useAuthUser()
  const { state, resetPlan, openConversation } = usePlan()
  const { removeSetup, reload: reloadSetups, conversations, conversationsError: historyError, refreshConversations } = useSetups()
  const { showToast } = useToast()
  const removeSheetApi = useRemoveSheet()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [tab, setTab] = useState<Tab>(readTab)
  const [sortKey, setSortKey] = useState<SortKey>('date')
  const [sortDir, setSortDir] = useState<Record<SortKey, 1 | -1>>({ date: -1, price: 1 })   // 날짜는 최신순, 가격은 낮은순이 처음
  const [kinds, setKinds] = useState({ body: true, periph: true })
  // 견적서를 펼치고 접은 견적(목록 id → 펼침 여부). 사용자가 직접 누른 것만 담고, 안 누른 견적은 지금 보고 있는 리포트의 견적만 펼쳐 둔다.
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  // 대화·견적서 행의 우클릭/길게 누르기 메뉴(대상과 열린 위치)와 이름 바꾸기(입력 중인 줄)
  const [ctx, setCtx] = useState<{ target: CtxTarget; x: number; y: number } | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingSheet, setEditingSheet] = useState<{ listId: string; revisionNo: number } | null>(null)
  const [draft, setDraft] = useState('')
  const pressTimer = useRef<number | null>(null)
  const pressOrigin = useRef({ x: 0, y: 0 })
  const suppressClick = useRef(false)
  const viewingId = pathname.startsWith('/report/') ? pathname.slice('/report/'.length) : null
  const isOpen = (id: string) => toggled[id] ?? id === viewingId
  const toggle = (id: string) => setToggled(prev => ({ ...prev, [id]: !(prev[id] ?? id === viewingId) }))
  const viewingVersion = Number(new URLSearchParams(search).get('v')) || null
  // 지금 보고 있는 리포트인가 — 주소에 ?v= 가 없으면 그 견적의 가장 최근 견적서다.
  const isViewing = (listId: string, revisionNo: number, latestRevisionNo: number) => viewingId === listId && (viewingVersion ?? latestRevisionNo) === revisionNo

  useEffect(() => {
    try { localStorage.setItem(TAB_KEY, tab) } catch { /* 보관 실패는 무시 */ }
  }, [tab])
  // 다른 견적서를 열면 그 견적은 직접 접어 둔 상태를 버리고 펼쳐서 보여 준다.
  useEffect(() => {
    if (viewingId) setToggled(prev => { if (!(viewingId in prev)) return prev; const { [viewingId]: _drop, ...rest } = prev; return rest })
  }, [viewingId])
  // 대화 목록은 SetupsProvider 가 한 곳에서 읽는다. 화면을 옮길 때(대화가 늘었을 수 있다)만 가볍게 다시 읽는다.
  const lastPath = useRef(pathname)
  useEffect(() => {
    if (lastPath.current === pathname) return   // 처음 그릴 때(와 개발 모드의 재실행)는 SetupsProvider 가 이미 읽는 중이다
    lastPath.current = pathname
    void refreshConversations()
  }, [pathname, refreshConversations])

  // 대화를 누르면 그 대화의 채팅과 함께 "2 추천 결과" 화면이 열린다. 확정된 대화는 구성을 보기만 하고(고치려면 견적 수정하기),
  // 구성을 못 읽으면 리포트로 간다. 견적서를 누르면 리포트가 열린다(견적서 행).
  async function openHistory(item: ConversationSummary) {
    // 받은 견적 점검으로 만든 대화는 점검 화면에서 이어 본다(이 브라우저에서 만든 것만 구분할 수 있다).
    if (isCheckSession(item.listId)) { navigate('/check?draft=' + item.listId); return }
    const confirmed = item.stage === 'report'
    const opened = await openConversation(item.listId, item.stage === 'results' || confirmed, confirmed)
    if (opened === 'plan') navigate('/plan')
    else if (opened) navigate(confirmed ? '/report/' + item.listId : '/start')
  }

  // 우클릭 메뉴는 바깥을 누르거나 Esc, 스크롤, 창 포커스가 빠질 때 닫는다.
  useEffect(() => {
    if (!ctx) return
    const close = () => setCtx(null)
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', close, true)
    window.addEventListener('blur', close)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('blur', close)
    }
  }, [ctx])
  useEffect(() => {
    if (!menuOpen) return
    const close = () => setMenuOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menuOpen])

  function go(next: Tab) {
    setTab(next)
    setCollapsed(false)
  }

  // 저장한 견적: 모든 대화의 견적서를 한 줄씩 시간 순으로. 종류 필터는 서버가 주변기기 개수를 줄 때만 쓴다.
  const sheets: Sheet[] = (conversations ?? []).flatMap(item => item.reports.map(report => ({ listId: item.listId, report, latestRevisionNo: item.reports[item.reports.length - 1].revisionNo })))
  const hasKindData = sheets.some(sheet => sheet.report.peripheralCount != null)
  const visibleSheets = sheets
    .filter(({ report }) => !hasKindData || (kinds.body && report.itemCount > 0) || (kinds.periph && (report.peripheralCount ?? 0) > 0))
    .sort((a, b) => {
      const dir = sortDir[sortKey]
      const diff = sortKey === 'date' ? a.report.confirmedAt.localeCompare(b.report.confirmedAt) : a.report.total - b.report.total
      return dir * diff || b.report.confirmedAt.localeCompare(a.report.confirmedAt)
    })
  function pickSort(key: SortKey) {
    if (sortKey === key) setSortDir(prev => ({ ...prev, [key]: prev[key] === 1 ? -1 : 1 }))
    else setSortKey(key)
  }
  function toggleKind(kind: 'body' | 'periph') {
    const other = kind === 'body' ? 'periph' : 'body'
    if (kinds[kind] && !kinds[other]) return   // 둘 다 끄는 것은 막는다(전체로 보인다)
    setKinds(prev => ({ ...prev, [kind]: !prev[kind] }))
  }

  // 우클릭(메뉴 키·Shift+F10 포함)과 길게 누르기(터치)로 같은 메뉴를 연다.
  function openCtx(target: CtxTarget, x: number, y: number) { setCtx({ target, x, y }) }
  function cancelPress() { if (pressTimer.current !== null) { window.clearTimeout(pressTimer.current); pressTimer.current = null } }
  function rowHandlers(target: CtxTarget): RowHandlers {
    return {
      onContextMenu: event => {
        event.preventDefault()
        let { clientX: x, clientY: y } = event
        if (x === 0 && y === 0) { const box = event.currentTarget.getBoundingClientRect(); x = box.left + 40; y = box.top + 20 }   // 키보드로 연 경우
        openCtx(target, x, y)
      },
      onTouchStart: event => {
        const touch = event.touches[0]
        pressOrigin.current = { x: touch.clientX, y: touch.clientY }
        cancelPress()
        pressTimer.current = window.setTimeout(() => {
          pressTimer.current = null
          suppressClick.current = true
          window.setTimeout(() => { suppressClick.current = false }, 600)   // 길게 누른 손을 뗄 때 생기는 클릭은 무시한다
          openCtx(target, pressOrigin.current.x, pressOrigin.current.y)
        }, LONG_PRESS_MS)
      },
      onTouchMove: event => {
        const touch = event.touches[0]
        if (Math.abs(touch.clientX - pressOrigin.current.x) > 8 || Math.abs(touch.clientY - pressOrigin.current.y) > 8) cancelPress()
      },
      onTouchEnd: cancelPress,
      onTouchCancel: cancelPress,
    }
  }
  const guard = (action: () => void) => () => { if (!suppressClick.current) action() }

  function startRename(item: ConversationSummary) {
    setCtx(null)
    setDraft(conversationTitle(item) ?? '')
    setEditingId(item.listId)
  }
  async function commitRename(item: ConversationSummary) {
    const name = draft.trim().slice(0, 60)
    setEditingId(null)
    if (!name || name === conversationTitle(item)) return
    try {
      await api.lists.rename(item.listId, name)
      await refreshConversations()
    } catch (error) {
      showToast(errorMessage(error, '제목을 바꾸지 못했습니다. 잠시 후 다시 시도해주세요.'))
    }
  }
  async function removeConversation(item: ConversationSummary) {
    setCtx(null)
    const title = conversationTitle(item) ?? '이 대화'
    const sheets = item.reports.length > 0 ? ` 저장한 견적서 ${item.reports.length}개도 함께 지워져요.` : ''
    if (!window.confirm(`“${title}” 대화를 삭제할까요?${sheets} 되돌릴 수 없어요.`)) return
    // 저장한 견적 목록도 함께 갱신되게 setups 쪽 삭제를 쓴다(DELETE /lists/{id}, 이미 없으면 지운 것으로 본다).
    if (!await removeSetup(item.listId)) { showToast('삭제하지 못했습니다. 잠시 후 다시 시도해주세요.'); return }
    await refreshConversations()
    // 지금 열어 둔 대화나 리포트를 지웠으면 빈 새 견적으로 돌아간다.
    if (state.sessionId === item.listId || viewingId === item.listId) { resetPlan(); navigate('/start') }
  }

  function startSheetRename(listId: string, report: ReportSummary) {
    setCtx(null)
    setDraft(report.name)
    setEditingSheet({ listId, revisionNo: report.revisionNo })
  }
  async function commitSheetRename(listId: string, report: ReportSummary) {
    const name = draft.trim().slice(0, 60)
    setEditingSheet(null)
    if (!name || name === report.name) return
    try {
      await api.lists.renameReport(listId, report.revisionNo, name)
      reloadSetups()   // 저장 목록·리포트 화면이 새 이름을 읽도록 다시 불러온다(대화 목록도 따라서 갱신된다)
    } catch (error) {
      showToast(errorMessage(error, '이름을 바꾸지 못했습니다. 잠시 후 다시 시도해주세요.'))
    }
  }
  async function removeSheet(listId: string, report: ReportSummary) {
    setCtx(null)
    const siblings = conversations?.find(item => item.listId === listId)?.reports ?? []
    const rest = siblings.filter(item => item.revisionNo !== report.revisionNo)
    const wasViewing = isViewing(listId, report.revisionNo, siblings[siblings.length - 1]?.revisionNo ?? 0)
    if (!await removeSheetApi(listId, report, rest.length === 0)) return
    // 지금 보던 견적서를 지웠으면 남은 가장 최근 견적서로, 없으면 시작 화면으로 간다.
    if (wasViewing) navigate(rest.length > 0 ? `/report/${listId}?v=${rest[rest.length - 1].revisionNo}` : '/start')
  }

  function startNew() {
    resetPlan()
    navigate('/start')
  }

  const ctxConv = ctx && conversations ? conversations.find(row => row.listId === ctx.target.listId) ?? null : null
  const ctxReport = ctx?.target.kind === 'sheet' ? ctxConv?.reports.find(item => item.revisionNo === (ctx.target as { revisionNo: number }).revisionNo) ?? null : null

  const sheetRow = (listId: string, report: ReportSummary, latestRevisionNo: number) => {
    const target: CtxTarget = { kind: 'sheet', listId, revisionNo: report.revisionNo }
    const editing = editingSheet?.listId === listId && editingSheet.revisionNo === report.revisionNo
    return (
      <SheetRow key={`${listId}:${report.revisionNo}`} listId={listId} report={report} active={isViewing(listId, report.revisionNo, latestRevisionNo)}
        menuOpen={sameTarget(ctx?.target, target)} handlers={rowHandlers(target)} onLinkClick={event => { if (suppressClick.current) event.preventDefault() }}
        edit={editing ? { draft, onChange: setDraft, onCommit: () => void commitSheetRename(listId, report), onCancel: () => setEditingSheet(null) } : null} />
    )
  }

  return (
    <aside className={'sp-root' + (collapsed ? ' collapsed' : '')} aria-label="견적 패널" style={collapsed ? undefined : { width: size.width }}>
      <div className="sp-inner">
        <div className="sp-head">
          <button type="button" className="sp-row icon-only" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? '패널 펴기' : '패널 접기'} aria-expanded={!collapsed}>
            <Icon><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Icon>
          </button>
        </div>

        <div className="sp-menu">
          <button type="button" className="sp-row new" onClick={startNew} data-tip="새 견적">
            <Icon><path d="M12 5v14M5 12h14" /></Icon><span className="sp-lbl">새 견적 (새 대화)</span>
          </button>
          <button type="button" className={'sp-row nav' + (tab === 'history' ? ' on' : '')} onClick={() => go('history')} data-tip="대화 내역" aria-current={tab === 'history'}>
            <Icon><path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /></Icon><span className="sp-lbl">대화 내역</span>
          </button>
          <button type="button" className={'sp-row nav' + (tab === 'saved' ? ' on' : '')} onClick={() => go('saved')} data-tip="저장한 견적" aria-current={tab === 'saved'}>
            <Icon><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h6" /></Icon><span className="sp-lbl">저장한 견적</span>
          </button>
        </div>

        {tab === 'history' && (
          <div className="sp-list">
            {historyError && <div className="sp-note bad" role="alert">{historyError}</div>}
            {!historyError && conversations === null && <div className="sp-note">불러오는 중이에요…</div>}
            {conversations?.length === 0 && <div className="sp-note">아직 나눈 대화가 없어요. 새 견적으로 시작해 보세요.</div>}
            {conversations && groupConversations(conversations).map(group => (
              <div key={group.label}>
                <div className="sp-group">{group.label}</div>
                {group.items.map(item => {
                  const sheetsOpen = item.reports.length > 0 && isOpen(item.listId)
                  const latestRevisionNo = item.reports[item.reports.length - 1]?.revisionNo ?? 0
                  return (
                    <div key={item.listId}>
                      <div className={'sp-item sp-conv' + (state.sessionId === item.listId ? ' on' : '') + (sameTarget(ctx?.target, { kind: 'conv', listId: item.listId }) ? ' ctx' : '')}
                        tabIndex={editingId === item.listId ? -1 : 0}
                        {...rowHandlers({ kind: 'conv', listId: item.listId })}>
                        {item.reports.length > 0
                          ? <button type="button" className={'sp-chev' + (sheetsOpen ? ' open' : '')} aria-label={sheetsOpen ? '견적서 접기' : '견적서 펼치기'}
                            aria-expanded={sheetsOpen} onClick={guard(() => toggle(item.listId))}>▶</button>
                          : <span className="sp-chev none" aria-hidden="true">▶</span>}
                        {editingId === item.listId ? (
                          <input className="sp-rename" value={draft} maxLength={60} autoFocus aria-label="대화 제목"
                            onChange={event => setDraft(event.target.value)} onFocus={event => event.target.select()}
                            onKeyDown={event => { if (event.key === 'Enter') void commitRename(item); if (event.key === 'Escape') setEditingId(null) }}
                            onBlur={() => void commitRename(item)} />
                        ) : (
                          <button type="button" className="sp-conv-main" onClick={guard(() => void openHistory(item))}>
                            <span className="sp-name sp-conv-name">{conversationTitle(item)}</span>
                            <span className="sp-meta">{[STAGE_LABEL[item.stage], fullDate(item.lastActiveAt)].filter(Boolean).join(' · ')}</span>
                          </button>
                        )}
                        {item.reports.length > 0 && editingId !== item.listId && (
                          <button type="button" className="sp-count" title={`저장한 견적서 ${item.reports.length}개 — 누르면 ${sheetsOpen ? '접어요' : '펼쳐요'}`}
                            aria-label={`저장한 견적서 ${item.reports.length}개 ${sheetsOpen ? '접기' : '펼치기'}`} aria-expanded={sheetsOpen}
                            onClick={guard(() => toggle(item.listId))}><DocIcon />{item.reports.length}</button>
                        )}
                      </div>
                      {sheetsOpen && (
                        <div className="sp-sheets">
                          {[...item.reports].reverse().map(report => sheetRow(item.listId, report, latestRevisionNo))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        )}

        {tab === 'saved' && (
          <>
            {user && sheets.length > 0 && (
              <div className="sp-filters">
                <div className="sp-frow">
                  <span className="sp-flabel">정렬</span>
                  <button type="button" className={'sp-chip' + (sortKey === 'date' ? ' on' : '')} onClick={() => pickSort('date')}>날짜 <span>{sortDir.date === -1 ? '↓' : '↑'}</span></button>
                  <button type="button" className={'sp-chip' + (sortKey === 'price' ? ' on' : '')} onClick={() => pickSort('price')}>가격 <span>{sortDir.price === -1 ? '↓' : '↑'}</span></button>
                </div>
                {hasKindData && (
                  <div className="sp-frow">
                    <span className="sp-flabel">종류</span>
                    <button type="button" className={'sp-chip' + (kinds.body ? ' on' : '')} onClick={() => toggleKind('body')}>PC 본체</button>
                    <button type="button" className={'sp-chip' + (kinds.periph ? ' on' : '')} onClick={() => toggleKind('periph')}>PC 주변기기</button>
                  </div>
                )}
              </div>
            )}
            <div className="sp-list">
              {!user && (
                <div className="sp-note">
                  저장한 견적은 로그인한 계정에만 있어요.{' '}
                  <Link to={`/login?next=${encodeURIComponent(pathname)}`}>로그인하기 →</Link>
                </div>
              )}
              {user && historyError && <div className="sp-note bad" role="alert">{historyError}</div>}
              {user && !historyError && conversations === null && <div className="sp-note">불러오는 중이에요…</div>}
              {user && conversations !== null && sheets.length === 0 && (
                <div className="sp-note">아직 확정한 견적이 없어요. 추천을 받고 장바구니에서 확정하면 여기에 저장돼요.</div>
              )}
              {user && sheets.length > 0 && <div className="sp-count-line">견적서 {visibleSheets.length}개</div>}
              {user && sheets.length > 0 && visibleSheets.length === 0 && <div className="sp-note">조건에 맞는 견적서가 없어요.</div>}
              <div className="sp-flat">
                {visibleSheets.map(({ listId, report, latestRevisionNo }) => sheetRow(listId, report, latestRevisionNo))}
              </div>
            </div>
          </>
        )}

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

      {!collapsed && <ResizeHandle width={size.width} min={size.min} max={size.max} label="좌측 패널 너비" onChange={size.setWidth} onReset={size.reset} />}

      {ctx && (ctxReport || (ctx.target.kind === 'conv' && ctxConv)) && (
        <div className="sp-ctxmenu" role="menu" style={{ left: Math.min(ctx.x, window.innerWidth - 168), top: Math.min(ctx.y, window.innerHeight - 100) }}
          onClick={event => event.stopPropagation()} onContextMenu={event => event.preventDefault()}>
          {ctxReport && ctx.target.kind === 'sheet' ? (
            <>
              <button type="button" role="menuitem" onClick={() => startSheetRename(ctx.target.listId, ctxReport)}>이름 바꾸기</button>
              <div className="sep" />
              <button type="button" role="menuitem" className="out" onClick={() => void removeSheet(ctx.target.listId, ctxReport)}>견적서 삭제</button>
            </>
          ) : ctxConv && (
            <>
              <button type="button" role="menuitem" onClick={() => startRename(ctxConv)}>제목 바꾸기</button>
              <div className="sep" />
              <button type="button" role="menuitem" className="out" onClick={() => void removeConversation(ctxConv)}>대화 삭제</button>
            </>
          )}
        </div>
      )}
    </aside>
  )
}
