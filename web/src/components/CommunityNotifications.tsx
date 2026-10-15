import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

// 커뮤니티 알림 종. 서버 API 는 준비돼 있다(GET /community/me/notifications, /unread-count, 읽음 처리 — 폴링 방식, 같은 글은 한 알림으로 묶음).
// 화면은 아직 연결 전이라 목록이 비어 있고 "준비 중" 안내만 보인다. 연결하면 아래 items 를 서버 응답으로 채우고,
// unread 로 점 표시와 aria-label 을 낸다. (요청서: 개발요청_커뮤니티_마이페이지_백엔드 A-5)
export default function CommunityNotifications() {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const unread = 0

  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', escape) }
  }, [open])

  return (
    <div className="tf-notifications" ref={root}>
      <button type="button" className="tf-notification-button" aria-label={unread ? `새 알림 ${unread}개` : '알림'} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" /><path d="M10 21h4" /></svg>
        {unread > 0 && <span className="tf-notification-dot" />}
      </button>
      {open && <section className="tf-notification-pop" role="dialog" aria-label="커뮤니티 알림">
        <header><h2>알림</h2></header>
        <div className="tf-notification-list">
          <article><div><strong>알림 기능은 준비 중이에요</strong><p>내 글에 댓글이 달리면 여기에 보여 드릴 예정이에요.</p></div></article>
        </div>
        <footer><span /><Link to="/mypage?tab=community" onClick={() => setOpen(false)}>나의 커뮤니티 〉</Link></footer>
      </section>}
    </div>
  )
}
