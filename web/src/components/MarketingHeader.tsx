import { Link, NavLink } from 'react-router-dom'
import { useAuthUser } from '../state/authStore'
import Brand from './Brand'
import ThemeToggle from './ThemeToggle'
import UserMenu from './UserMenu'

// 메인·시작 방식 선택 화면의 상단 바. 로그인 상태는 서버 세션(/auth/me)에서 온 값이다.
// 오른쪽 끝은 테마 전환 버튼이고, 로그인하면 "OOO 님"에 마우스를 올려 마이페이지·로그아웃을 연다.
// 저장한 견적·대화 내역은 플래너(/start)의 좌측 패널에서 본다.
export default function MarketingHeader() {
  const user = useAuthUser()
  return (
    <header className="tf-home-header">
      <Link className="tf-home-brand" to="/" aria-label="TrueFit 홈">
        <Brand />
      </Link>
      <nav className="tf-home-nav" aria-label="주요 메뉴">
        <NavLink to="/start">새 컴퓨터 본체</NavLink>
        <NavLink to="/check">받은 견적 점검</NavLink>
        <NavLink to="/peripherals">주변기기 견적</NavLink>
      </nav>
      <div className="tf-home-spacer" />
      {user ? (
        <UserMenu name={user.name} />
      ) : (
        <div className="tf-home-auth">
          <Link to="/login"><button type="button">로그인</button></Link>
          <Link to="/signup"><button type="button">회원가입</button></Link>
        </div>
      )}
      <ThemeToggle />
    </header>
  )
}
