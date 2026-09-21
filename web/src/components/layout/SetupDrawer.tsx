import { useNavigate, Link } from 'react-router-dom'
import { useSetups } from '../../state/SetupsContext'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import { useModalFocus } from '../../hooks/useModalFocus'
import { planTotal } from '../../state/planModel'
import { wonFmt } from '../../utils/format'
import type { SavedSetup } from '../../state/types'
import { isMockApi } from '../../api'

export function SetupDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { savedSetups, loading, removeSetup, storageError } = useSetups()
  const { resetPlan, loadFromSavedSetup } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const ref = useModalFocus(open, onClose)
  if (!open) return null
  function select(setup: SavedSetup) {
    loadFromSavedSetup(setup)
    onClose()
    navigate('/plan')
  }
  async function remove(id: string) {
    if (await removeSetup(id)) showToast('저장한 구성을 삭제했습니다.')
    ref.current?.querySelector<HTMLButtonElement>('.setup-close')?.focus()
  }
  return <div ref={ref} className="setup-drawer" role="dialog" aria-modal="true" aria-labelledby="setupTitle" tabIndex={-1}>
    <div className="setup-backdrop" onClick={onClose} />
    <aside className="setup-panel">
      <div className="setup-head"><div><p className="eyebrow">MY SETUP</p><h2 id="setupTitle">내 구성</h2></div><button type="button" className="setup-close" aria-label="닫기" onClick={onClose}>×</button></div>
      <p className="setup-hint">{isMockApi ? '이 브라우저에 임시 저장됩니다. 다른 기기와 동기화되지 않습니다.' : '확정한 리스트는 계정에 저장됩니다. 로그인하면 볼 수 있어요.'}</p>
      <p className="confirm-error" role="alert">{storageError}</p>
      <div className="setup-list-head"><span>저장한 구성</span><span>{savedSetups.length}개</span></div>
      {loading && <p className="setup-hint" role="status">저장 목록을 불러오는 중입니다...</p>}
      {!loading && !savedSetups.length && <p className="setup-hint">아직 저장한 구성이 없습니다. 구성을 만든 뒤 리스트를 확정해주세요.</p>}
      <div className="setup-list">{savedSetups.map(setup => <div key={setup.id} className="setup-item">
        <button className="setup-select" type="button" onClick={() => select(setup)}>
          <span className="setup-item-main"><strong>{setup.title}</strong><span>구매 예정: {setup.date}</span></span>
          <span className="setup-item-price">{wonFmt(planTotal(setup.plan))}</span>
        </button>
        <div className="setup-item-actions"><Link to={'/plan/report/' + setup.id} onClick={onClose}>리포트</Link><button type="button" className="ghost-btn" aria-label={setup.title + ' 삭제'} onClick={() => remove(setup.id)}>삭제</button></div>
      </div>)}</div>
      <button type="button" className="setup-reset" onClick={() => { resetPlan(); onClose(); navigate('/plan') }}>↺ 처음부터 새로 설계하기</button>
    </aside>
  </div>
}
