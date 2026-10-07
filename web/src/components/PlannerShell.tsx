import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import ChatPanel from './ChatPanel'
import SidePanel from './SidePanel'
import truefitLogo from '../assets/truefit-logo.png'
import truefitLogoLight from '../assets/truefit-logo-light.png'
import { useTheme } from '../state/theme'
import ThemeToggle from './ThemeToggle'
import '../styles/planner.css'

// 조건 대화·추천 결과 화면이 함께 쓰는 틀: 상단 바 + 왼쪽 접이식 패널 + (채팅) + 내용.
export default function PlannerShell({ chatTitle, placeholder, sidebar, children }: { chatTitle?: string; placeholder?: string; sidebar?: ReactNode; children: ReactNode }) {
  const pcActive = ({ isActive }: { isActive: boolean }) => (isActive ? 'on' : '')
  const { theme } = useTheme()
  return (
    <div className="pl-root">
      <header className="pl-top">
        <Link className="pl-brand" to="/" aria-label="TrueFit 홈"><img src={theme === 'light' ? truefitLogoLight : truefitLogo} alt="" aria-hidden="true" /></Link>
        <nav className="pl-nav" aria-label="주요 메뉴">
          <NavLink to="/start" className={pcActive}>새 컴퓨터 본체</NavLink>
          <NavLink to="/check" className={pcActive}>받은 견적 점검</NavLink>
          <NavLink to="/peripherals" className={pcActive}>주변기기 견적</NavLink>
        </nav>
        <div className="pl-spacer" />
        <ThemeToggle />
      </header>
      <div className="pl-body">
        <SidePanel />
        {sidebar ?? (chatTitle && placeholder ? <ChatPanel title={chatTitle} placeholder={placeholder} /> : null)}
        <main className="pl-main">{children}</main>
      </div>
    </div>
  )
}
