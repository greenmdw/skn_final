import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api'
import { communityApi, relativeTime, type WireNotification } from '../api/http/community'

// 커뮤니티 알림 종. 내 글에 새 댓글이 달리거나 내 댓글에 답글이 달리면 서버가 알림을 만들고, 종은 안 읽은 개수만 주기적으로 묻는다(60초).
// 종을 누르면 알림 목록을 불러오고, 알림 행을 누르면 읽음 처리하고 글로 이동한다.
const POLL_MS = 60_000

export default function CommunityNotifications() {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState<WireNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const root = useRef<HTMLDivElement>(null)

  const pollUnread = useCallback(() => {
    communityApi.me.unreadCount().then(result => setUnread(result.unread_count)).catch(() => undefined)   // 로그아웃 직후 등 실패는 조용히 넘긴다
  }, [])

  useEffect(() => {
    pollUnread()
    const timer = window.setInterval(() => { if (!document.hidden) pollUnread() }, POLL_MS)
    const onVisible = () => { if (!document.hidden) pollUnread() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [pollUnread])

  const load = useCallback(() => {
    setLoading(true)
    communityApi.me.notifications({ pageSize: 10 })
      .then(result => { setItems(result.items); setUnread(result.unread_count); setError('') })
      .catch(caught => setError(errorMessage(caught, '알림을 불러오지 못했어요.')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', escape) }
  }, [open, load])

  const readOne = (id: string) => {
    setItems(current => current.map(item => (item.id === id ? { ...item, read: true } : item)))
    setUnread(current => Math.max(0, current - 1))
    communityApi.me.markRead(id).then(result => setUnread(result.unread_count)).catch(() => pollUnread())
    setOpen(false)
  }
  const readAll = () => {
    setItems(current => current.map(item => ({ ...item, read: true })))
    setUnread(0)
    communityApi.me.markAllRead().catch(() => pollUnread())
  }

  return (
    <div className="tf-notifications" ref={root}>
      <button type="button" className="tf-notification-button" aria-label={unread ? `새 알림 ${unread}개` : '알림'} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" /><path d="M10 21h4" /></svg>
        {unread > 0 && <span className="tf-notification-dot" />}
      </button>
      {open && <section className="tf-notification-pop" role="dialog" aria-label="커뮤니티 알림">
        <header><h2>알림</h2><button type="button" disabled={!unread} onClick={readAll}>모두 읽음</button></header>
        <div className="tf-notification-list">
          {error
            ? <article><div><strong>{error}</strong></div></article>
            : loading && items.length === 0
              ? <article><div><strong>불러오는 중이에요</strong></div></article>
              : items.length === 0
                ? <article><div><strong>새 알림이 없어요</strong><p>내 글에 댓글이 달리면 여기에 보여 드려요.</p></div></article>
                : items.map(item => (
                  <Link className={'tf-notification-item' + (item.read ? ' read' : '')} key={item.id}
                    to={`/community?view=post&post=${encodeURIComponent(item.post_id)}`} onClick={() => readOne(item.id)}>
                    <span className="tf-notification-kind">{item.type === 'new_reply' ? '답' : '댓'}</span>
                    <div><strong>{item.title}</strong><p>{item.message}</p><small>{relativeTime(item.created_at)}</small></div>
                    <span className="tf-notification-action">{item.read ? '보기' : '확인'}</span>
                  </Link>
                ))}
        </div>
        <footer><span /><Link to="/mypage?tab=community" onClick={() => setOpen(false)}>나의 커뮤니티 〉</Link></footer>
      </section>}
    </div>
  )
}
