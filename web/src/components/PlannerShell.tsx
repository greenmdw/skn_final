import type { ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import ChatPanel from './ChatPanel'
import SidePanel from './SidePanel'
import Brand from './Brand'
import ThemeToggle from './ThemeToggle'
import { usePlan } from '../state/PlanContext'
import '../styles/planner.css'

// 조건 대화·추천 결과 화면이 함께 쓰는 틀: 상단 바 + 왼쪽 접이식 패널 + (채팅) + 내용.
export default function PlannerShell({ chatTitle, placeholder, sidebar, children }: { chatTitle?: string; placeholder?: string; sidebar?: ReactNode; children: ReactNode }) {
  const location = useLocation()
  const { pathname } = location
  const { state: planState, customHeading } = usePlan()
  type PlannerMode = 'computer' | 'check' | 'peripherals'
  const requestedMode = (location.state as { plannerMode?: PlannerMode } | null)?.plannerMode
  // /cart와 /report는 세 모드가 함께 쓰는 주소다. 이동할 때 전달한 모드를 우선하고,
  // 직접 열거나 새로고침한 경우에는 현재 장바구니 구성으로 한 번 더 판정한다.
  const sharedPageMode: PlannerMode = requestedMode
    ?? (customHeading?.title === '받은 견적 점검' ? 'check'
      : (!planState.currentPlan && planState.peripherals.length > 0 ? 'peripherals' : 'computer'))
  // 각 전용 화면은 경로로, 공용 장바구니·리포트는 위에서 판정한 유입 모드로 메뉴를 활성화한다.
  const activeSection = pathname.startsWith('/check') ? 'check'
    : pathname.startsWith('/peripherals') ? 'peripherals'
      : pathname.startsWith('/community') ? 'community'
        : (pathname === '/cart' || pathname.startsWith('/report/')) ? sharedPageMode
          : 'computer'
  const navClass = (section: typeof activeSection) => section === activeSection ? 'on' : ''
  return (
    <div className="pl-root">
      <header className="pl-top">
        <Link className="pl-brand" to="/" aria-label="TrueFit 홈"><Brand /></Link>
        <nav className="pl-nav" aria-label="주요 메뉴">
          <NavLink to="/start" className={navClass('computer')}>새 컴퓨터 본체</NavLink>
          <NavLink to="/check" className={navClass('check')}>받은 견적 점검</NavLink>
          <NavLink to="/peripherals" className={navClass('peripherals')}>주변기기 견적</NavLink>
          <NavLink to="/community" className={navClass('community')}>커뮤니티</NavLink>
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
