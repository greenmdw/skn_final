import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { logout, useAuthUser } from '../state/authStore'
import ChatPanel from './ChatPanel'
import '../styles/planner.css'

// 조건 대화·추천 결과 화면이 함께 쓰는 틀: 상단 바 + (왼쪽 채팅) + 내용.
// 아직 React 로 옮기지 않은 화면(견적 점검·주변기기·장바구니)은 /screen/<이름> 으로 프로토타입을 연다.
export default function PlannerShell({ chatTitle, placeholder, children }: { chatTitle: string; placeholder: string; children: ReactNode }) {
  const user = useAuthUser()
  const pcActive = ({ isActive }: { isActive: boolean }) => (isActive ? 'on' : '')
  return (
    <div className="pl-root">
      <header className="pl-top">
        <Link className="pl-brand" to="/"><i />True<b>Fit</b></Link>
        <nav className="pl-nav" aria-label="주요 메뉴">
          <NavLink to="/start" className={pcActive}>새 컴퓨터 본체</NavLink>
          <NavLink to="/screen/check" className={pcActive}>받은 견적 점검</NavLink>
          <NavLink to="/screen/peri" className={pcActive}>주변기기 견적</NavLink>
        </nav>
        <div className="pl-spacer" />
        <Link className="pl-pill" to="/screen/drawer">저장한 견적</Link>
        <Link className="pl-pill mint" to="/screen/cart">장바구니</Link>
        {user ? (
          <>
            <span className="pl-user">{user.name} 님</span>
            <button type="button" className="pl-pill" onClick={() => void logout()}>로그아웃</button>
          </>
        ) : (
          <>
            <span className="pl-user">게스트</span>
            <Link className="pl-pill" to="/login">로그인</Link>
          </>
        )}
      </header>
      <div className="pl-body">
        <ChatPanel title={chatTitle} placeholder={placeholder} />
        <main className="pl-main">{children}</main>
      </div>
    </div>
  )
}
