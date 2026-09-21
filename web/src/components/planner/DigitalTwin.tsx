import { useState } from 'react'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import { isMockApi } from '../../api'

export function DigitalTwin({ onOpenDeskModal }: { onOpenDeskModal: () => void }) {
  const { state } = usePlan()
  const { showToast } = useToast()
  const [view, setView] = useState<'2d' | '3d'>('2d')
  const size = `${state.deskWidth} × ${state.deskDepth} × ${state.deskHeight}mm`

  function handleViewClick(next: '2d' | '3d') {
    if (!state.deskUnlocked) {
      onOpenDeskModal()
      return
    }
    setView(next)
    showToast(next === '3d' ? '3D 미리보기 각도를 적용했습니다.' : '2D 배치도로 돌아왔습니다.')
  }

  return (
    <section className="digital-twin-card">
      <div className="twin-head">
        <div><h2>책상 디지털 트윈</h2><p>{size} · 실제 비율</p></div>
        <div className="twin-controls">
          {state.deskUnlocked && (
            <button className="desk-edit-btn" type="button" onClick={onOpenDeskModal}>↔ 치수 변경</button>
          )}
          <div className="view-toggle" role="group" aria-label="디지털 트윈 보기 방식">
            <button type="button" className={view === '2d' ? 'active' : ''} aria-pressed={view === '2d'} onClick={() => handleViewClick('2d')}>2D</button>
            <button type="button" className={view === '3d' ? 'active' : ''} aria-pressed={view === '3d'} onClick={() => handleViewClick('3d')}>3D 미리보기</button>
          </div>
        </div>
      </div>
      <div className="twin-stage">
        <div
          className={'twin-canvas' + (state.deskUnlocked ? '' : ' locked')}
          style={{ transform: state.deskUnlocked && view === '3d' ? 'perspective(800px) rotateX(8deg)' : undefined }}
        >
          <div className="desk-outline" data-size={`${state.deskWidth} × ${state.deskDepth}mm`} />
          <div className="twin-device twin-speaker left">SPK</div>
          <div className="twin-device twin-monitor-main">MAIN 27″</div>
          <div className="twin-device twin-speaker right">SPK</div>
          <div className="twin-device twin-keyboard">KEYBOARD</div>
          <div className="twin-device twin-mouse">M</div>
          <div className="twin-air-zone">통풍 80mm</div>
          <div className="twin-device twin-pc-detailed">PC</div>
        </div>
        {state.deskUnlocked ? (
          <div className="twin-status">입력한 치수 기준 배치 가능 · 마우스 가용 폭 312mm</div>
        ) : (
          <div className="twin-lock">
            <div className="twin-lock-icon">▣</div>
            <h3>책상 치수를 입력해주세요</h3>
            <p>{isMockApi ? '책상 치수는 이 브라우저에 임시 보관되며 리스트 확정 시 구성과 함께 저장됩니다.' : '책상 치수는 이 브라우저에만 보관됩니다.'}</p>
            <button type="button" onClick={onOpenDeskModal}>책상 치수 입력</button>
          </div>
        )}
      </div>
    </section>
  )
}
