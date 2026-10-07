import { useEffect } from 'react'
import type { SavedSetup } from '../../state/types'
import { setupDate, setupPriority, setupPurpose, wonText } from '../../utils/checkReview'

export default function SavedQuotePicker({ setups, loading, error, selectedId, busy, onSelect, onConfirm, onClose }: {
  setups: SavedSetup[]
  loading: boolean
  error: string
  selectedId: string | null
  busy: boolean
  onSelect: (setup: SavedSetup) => void
  onConfirm: () => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const sorted = [...setups].sort((a, b) => b.savedAt.localeCompare(a.savedAt))
  return (
    <div className="ck-dialog-back" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section className="ck-dialog ck-saved-dialog" role="dialog" aria-modal="true" aria-label="비교할 저장 견적 선택">
        <div className="ck-modal-head">
          <div><h2>비교할 저장 견적 선택</h2><p className="ck-modal-intro">PC 본체 견적만 보여드려요. 용도·우선순위·금액을 확인하고 하나를 선택하세요.</p></div>
          <button type="button" className="ck-close" onClick={onClose} aria-label="닫기">×</button>
        </div>
        <div className="ck-saved-list">
          {loading && <div className="pl-empty">저장한 견적을 불러오는 중이에요…</div>}
          {!loading && error && <div className="pl-alert bad" role="alert">{error}</div>}
          {!loading && !error && sorted.length === 0 && <div className="pl-empty">비교할 수 있는 저장 견적이 없습니다. 견적을 확정해 저장하면 여기에 나타나요.</div>}
          {sorted.map(setup => {
            const total = setup.plan.items.reduce((sum, item) => sum + item.price, 0)
            return (
              <button type="button" key={setup.id} className={`ck-saved-option${selectedId === setup.id ? ' selected' : ''}`} onClick={() => onSelect(setup)}>
                <div><b>{setup.title}</b><small>{setupDate(setup)} · 부품 {setup.plan.items.length}개</small></div>
                <div className="ck-saved-tags"><span>용도 · {setupPurpose(setup)}</span><span>우선순위 · {setupPriority(setup)}</span></div>
                <strong>{wonText(total)}</strong>
              </button>
            )
          })}
        </div>
        <div className="ck-modal-foot">
          <span className="ck-modal-foot-note">선택 후 현재 분석 아래에 전체 폭 비교표가 표시됩니다.</span>
          <button type="button" className="ck-primary" disabled={!selectedId || busy} onClick={onConfirm}>{busy ? '비교 중…' : '선택한 견적 비교하기'}</button>
        </div>
      </section>
    </div>
  )
}
