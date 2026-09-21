import { useState } from 'react'
import { usePlan } from '../../state/PlanContext'
import { planTotal } from '../../state/planModel'
import { wonFmt } from '../../utils/format'
import { BudgetEditor } from './BudgetEditor'
import { isMockApi } from '../../api'
const colors = ['#60edc0', '#79d7ee', '#9b7ff2', '#ffb54d', '#f87186', '#86a6b5']

export function BudgetOverview() {
  const { state } = usePlan()
  const [view, setView] = useState<'part' | 'product'>('part')
  const plan = state.currentPlan
  if (!plan) return null
  const total = planTotal(plan)
  const remaining = plan.budget === null ? null : plan.budget - total
  return <section className="cost-overview">
    <div className="summary-cards">
      <div className="summary-card"><span>{plan.mode === 'upgrade' ? '업그레이드 추가 비용' : '구성 예상 합계'}</span><strong data-testid="plan-total">{wonFmt(total)}</strong><em>{plan.items.length}개 항목 기준</em></div>
      <div className="summary-card"><span>최대 예산</span><strong>{plan.budget === null ? '미설정' : wonFmt(plan.budget)}</strong><em>적용한 예산</em></div>
      <div className="summary-card"><span>{remaining !== null && remaining < 0 ? '예산 초과' : '남은 예산'}</span><strong>{remaining === null ? '미설정' : wonFmt(Math.abs(remaining))}</strong><em>{remaining !== null && remaining < 0 ? '예산을 조정한 뒤 확정해주세요.' : isMockApi ? '가상 가격 기준' : '데모 가격 기준'}</em></div>
    </div>
    <BudgetEditor key={plan.id} />
    <div className="allocation-card">
      <div className="allocation-head"><div><h2>예산은 어디에 쓰이나요?</h2><p>선택한 목록의 가격 합계 기준</p></div></div>
      <div className="allocation-toggle">
        <button type="button" className={view === 'part' ? 'active' : ''} onClick={() => setView('part')}>파트별</button>
        <button type="button" className={view === 'product' ? 'active' : ''} onClick={() => setView('product')}>제품별</button>
      </div>
      <div className="budget-bar" aria-label="부품별 가격 비중">{plan.items.map((p, i) => <span key={p.id} style={{ width: (total ? p.price / total * 100 : 0) + '%', background: colors[i % colors.length] }} />)}</div>
      <div className="allocation-legend">{plan.items.map(p => <div key={p.id} className="allocation-item"><span><strong>{view === 'part' ? p.type : p.name}</strong><span>{wonFmt(p.price)} · {total ? (p.price / total * 100).toFixed(1) : 0}%</span></span></div>)}</div>
      <div className="allocation-foot"><span>목록 합계 <strong>{wonFmt(total)}</strong></span><span>확정·리포트에도 같은 금액이 적용됩니다.</span></div>
    </div>
  </section>
}
