import { useState } from 'react'
import { useModalFocus } from '../../hooks/useModalFocus'
import { usePlan } from '../../state/PlanContext'

export function DeskModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? <DeskDialog onClose={onClose} /> : null
}
function DeskDialog({ onClose }: { onClose: () => void }) {
  const { state, setDesk } = usePlan()
  const [width, setWidth] = useState(state.deskWidth)
  const [depth, setDepth] = useState(state.deskDepth)
  const [height, setHeight] = useState(state.deskHeight)
  const ref = useModalFocus(true, onClose)
  const [error, setError] = useState('')
  function handleSave() {
    if (setDesk(width, depth, height)) onClose()
    else setError('입력 범위를 확인해주세요. 가로 800~3000, 세로 400~1500, 높이 500~1300mm입니다.')
  }

  return (
    <div
      ref={ref}
      tabIndex={-1}
      className="desk-modal-backdrop"
      id="deskModal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="deskModalTitle"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="desk-modal">
        <div className="desk-modal-head">
          <div>
            <p className="eyebrow">MY DESK</p>
            <h2 id="deskModalTitle">책상 치수를 입력해주세요</h2>
          </div>
          <button className="modal-close" type="button" aria-label="치수 입력 닫기" onClick={onClose}>×</button>
        </div>
        <div className="desk-modal-body">
          <p className="desk-modal-copy">책상 상판의 가로·세로와 바닥부터 상판까지의 높이를 mm 단위로 입력합니다.</p>
          <div className="dimension-fields">
            <div className="dimension-field">
              <label htmlFor="deskWidthInput">가로</label>
              <div className="dimension-input">
                <input data-autofocus id="deskWidthInput" type="number" min={800} max={3000} step={10} value={width} onChange={e => setWidth(Number(e.target.value))} />
                <span>mm</span>
              </div>
            </div>
            <div className="dimension-field">
              <label htmlFor="deskDepthInput">세로</label>
              <div className="dimension-input">
                <input id="deskDepthInput" type="number" min={400} max={1500} step={10} value={depth} onChange={e => setDepth(Number(e.target.value))} />
                <span>mm</span>
              </div>
            </div>
            <div className="dimension-field">
              <label htmlFor="deskHeightInput">높이</label>
              <div className="dimension-input">
                <input id="deskHeightInput" type="number" min={500} max={1300} step={10} value={height} onChange={e => setHeight(Number(e.target.value))} />
                <span>mm</span>
              </div>
            </div>
          </div>
          <p className="confirm-error" role="alert">{error}</p>
          <div className="desk-modal-actions">
            <button className="desk-later" type="button" onClick={onClose}>나중에</button>
            <button className="desk-save" type="button" onClick={handleSave}>치수 저장하고 보기</button>
          </div>
        </div>
      </div>
    </div>
  )
}
