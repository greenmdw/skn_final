import { Link, NavLink } from 'react-router-dom'
import { logout, useAuthUser } from '../state/authStore'
import truefitLogo from '../assets/truefit-logo.png'

// 메인·시작 방식 선택 화면의 상단 바. 로그인 상태는 서버 세션(/auth/me)에서 온 값이다.
// 저장한 견적·대화 내역은 플래너(/start)의 좌측 패널에서 본다.
export default function MarketingHeader() {
  const user = useAuthUser()
  return (
    <header className="tf-home-header">
      <Link className="tf-home-brand" to="/" aria-label="TrueFit 홈">
        <img src={truefitLogo} alt="" aria-hidden="true" />
      </Link>
      <nav className="tf-home-nav" aria-label="주요 메뉴">
        <NavLink to="/start">새 컴퓨터 본체</NavLink>
        <NavLink to="/check">받은 견적 점검</NavLink>
        <NavLink to="/peripherals">주변기기 견적</NavLink>
      </nav>
      <div className="tf-home-spacer" />
      <div className="tf-home-auth">
        {user ? (
          <>
            <span style={{ fontSize: 13, color: '#a8bac3' }}>{user.name} 님</span>
            <Link to="/start"><button type="button">내 견적 보기</button></Link>
            <button type="button" onClick={() => void logout()}>로그아웃</button>
          </>
        ) : (
          <>
            <Link to="/login"><button type="button">로그인</button></Link>
            <Link to="/signup"><button type="button">회원가입</button></Link>
          </>
        )}
      </div>
    </header>
  )
}
