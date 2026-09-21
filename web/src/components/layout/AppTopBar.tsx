import { useNavigate } from 'react-router-dom'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import { Brand } from './Brand'
import { isMockApi } from '../../api'

export function AppTopBar({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const { state } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()

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
          <span className="avatar">U</span>
          <span className="profile-text"><strong>{isMockApi ? '브라우저 사용자' : '방문자'}</strong><small>{isMockApi ? '임시 저장' : '확정할 때 로그인'}</small></span>
        </div>
        <button className="ghost-btn" type="button" onClick={() => navigate('/check')}>내 PC·견적 점검</button>
        <button className="save-btn" type="button" aria-label="구성 저장" onClick={handleSave}>
          <span aria-hidden="true">⇧</span><span>구성 저장</span>
        </button>
        <button className="icon-btn" type="button" aria-label="메뉴 열기" onClick={onOpenDrawer}>☰</button>
      </div>
    </header>
  )
}
