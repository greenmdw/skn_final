import { Link } from 'react-router-dom'
import { logout, useAuthUser } from '../state/authStore'
import { useDrawer } from '../state/DrawerContext'

// 메인·시작 방식 선택 화면의 상단 바. 로그인 상태는 서버 세션(/auth/me)에서 온 값이다.
export default function MarketingHeader() {
  const user = useAuthUser()
  const { openSaved } = useDrawer()
  return (
    <header className="tf-home-header">
      <Link className="tf-home-brand" to="/" aria-label="TrueFit 홈">
        <span className="tf-home-logo" aria-hidden="true"><i></i><i></i><i></i></span>
        <span>True<span>Fit</span></span>
      </Link>
      <div className="tf-home-auth">
        {user ? (
          <>
            <span style={{ fontSize: 13, color: '#a8bac3' }}>{user.name} 님</span>
            <button type="button" onClick={openSaved}>저장한 견적</button>
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
