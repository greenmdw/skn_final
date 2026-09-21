import { useNavigate } from 'react-router-dom'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import { logout, useAuthUser } from '../../state/authStore'
import { Brand } from './Brand'
import { isMockApi } from '../../api'

export function AppTopBar({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const { state } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const user = useAuthUser()

  async function handleLogout() {
    try { await logout(); showToast('로그아웃했습니다.') } catch { showToast('로그아웃하지 못했습니다. 잠시 후 다시 시도해주세요.') }
  }

  function handleSave() {
    if (state.stage < 4) {
      showToast('먼저 PC 구성을 완성해주세요.')
      return
    }
    navigate('/plan/confirm')
  }

  return (
    <header className="topbar">
      <Brand />
      <span className="status-pill"><i className="status-dot" />{isMockApi ? '샘플 가격' : '데모 가격'}</span>
      <div className="top-actions">
        <div className="profile-pill">
          <span className="avatar">{user ? user.name.slice(0, 1).toUpperCase() : 'U'}</span>
          <span className="profile-text"><strong>{user ? user.name : isMockApi ? '브라우저 사용자' : '방문자'}</strong><small>{user ? user.email : isMockApi ? '임시 저장' : '확정할 때 로그인'}</small></span>
        </div>
        {user && !isMockApi && <button className="ghost-btn" type="button" onClick={handleLogout}>로그아웃</button>}
        <button className="ghost-btn" type="button" onClick={() => navigate('/check')}>내 PC·견적 점검</button>
        <button className="save-btn" type="button" aria-label="구성 저장" onClick={handleSave}>
          <span aria-hidden="true">⇧</span><span>구성 저장</span>
        </button>
        <button className="icon-btn" type="button" aria-label="메뉴 열기" onClick={onOpenDrawer}>☰</button>
      </div>
    </header>
  )
}
