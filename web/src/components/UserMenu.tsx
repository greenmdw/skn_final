import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { logout } from '../state/authStore'

const CLOSE_DELAY_MS = 180

// 상단바의 "OOO 님". 마우스를 올리거나 키보드로 포커스하면 마이페이지·로그아웃이 열린다(눌러도 열고 닫힌다 — 터치 화면용).
export default function UserMenu({ name }: { name: string }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const timer = useRef<number | null>(null)

  const cancelClose = () => { if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null } }
  const openNow = () => { cancelClose(); setOpen(true) }
  // 이름에서 메뉴로 마우스를 옮기는 사이에 닫히지 않도록 잠깐 기다린다.
  const closeSoon = () => { cancelClose(); timer.current = window.setTimeout(() => setOpen(false), CLOSE_DELAY_MS) }

  useEffect(() => cancelClose, [])
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    const onPointer = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onPointer)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('pointerdown', onPointer) }
  }, [open])

  return (
    <div
      className="tf-user-menu" ref={root}
      onMouseEnter={openNow} onMouseLeave={closeSoon}
      onFocus={openNow} onBlur={event => { if (!root.current?.contains(event.relatedTarget as Node | null)) closeSoon() }}
    >
      <button type="button" className="tf-user-name" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {name} 님<span className="tf-user-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="tf-user-pop" role="menu">
          <Link role="menuitem" to="/mypage" onClick={() => setOpen(false)}>마이페이지</Link>
          <button type="button" role="menuitem" className="out" onClick={() => { setOpen(false); void logout() }}>로그아웃</button>
        </div>
      )}
    </div>
  )
}
