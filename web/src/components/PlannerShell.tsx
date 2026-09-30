import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import ChatPanel from './ChatPanel'
import SidePanel from './SidePanel'
import '../styles/planner.css'

// 조건 대화·추천 결과 화면이 함께 쓰는 틀: 상단 바 + 왼쪽 접이식 패널 + (채팅) + 내용.
// 견적 점검·주변기기는 아직 개발 전이라 준비 중 화면으로 이동한다.
export default function PlannerShell({ chatTitle, placeholder, children }: { chatTitle?: string; placeholder?: string; children: ReactNode }) {
  const pcActive = ({ isActive }: { isActive: boolean }) => (isActive ? 'on' : '')
  return (
    <div className="pl-root">
      <header className="pl-top">
        <Link className="pl-brand" to="/"><i />True<b>Fit</b></Link>
        <nav className="pl-nav" aria-label="주요 메뉴">
          <NavLink to="/start" className={pcActive}>새 컴퓨터 본체</NavLink>
          <NavLink to="/check" className={pcActive}>받은 견적 점검</NavLink>
          <NavLink to="/peripherals" className={pcActive}>주변기기 견적</NavLink>
        </nav>
      </header>
      <div className="pl-body">
        <SidePanel />
        {chatTitle && placeholder && <ChatPanel title={chatTitle} placeholder={placeholder} />}
        <main className="pl-main">{children}</main>
      </div>
    </div>
  )
}
