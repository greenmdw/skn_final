import { usePlan } from '../../state/PlanContext'
import { wonFmt } from '../../utils/format'
import { isMockApi } from '../../api'

export function PartsList() {
  const { state, selectPart } = usePlan()
  const plan = state.currentPlan
  if (!plan) return null
  return <section className="parts-list-card">
    <div className="parts-list-head"><h2>{plan.mode === 'upgrade' ? '선택한 변경 부품' : '추천 부품'}</h2><span>{plan.items.length}개 항목{isMockApi ? ' · 샘플' : ''}</span></div>
    <div className="parts-list">{plan.items.map(p => (
      <button key={p.id} type="button" className={'part-row' + (p.key === state.selectedPart ? ' selected' : '')}
        aria-pressed={p.key === state.selectedPart} onClick={() => { if (p.key) selectPart(p.key) }} disabled={!p.key}>
        <span className="part-icon">{p.label}</span>
        <span className="part-main"><strong>{p.name}</strong><span>{p.meta}</span></span>
        <span className="part-price"><small>{plan.mode === 'upgrade' ? '추가 비용' : '가격'}</small><strong>{wonFmt(p.price)}</strong><span>{p.source}</span></span>
        <span className={'part-action ' + p.actionClass}>{p.action}</span><span className="part-arrow">›</span>
      </button>
    ))}</div>
  </section>
}
