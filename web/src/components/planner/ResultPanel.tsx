import { useNavigate } from 'react-router-dom'
import { usePlan } from '../../state/PlanContext'
import { BudgetOverview } from './BudgetOverview'
import { PartsList } from './PartsList'
import { DigitalTwin } from './DigitalTwin'
import { CompatNotice } from './CompatNotice'
import { isMockApi } from '../../api'

export function ResultPanel({ onOpenDeskModal }: { onOpenDeskModal: () => void }) {
  const { state } = usePlan()
  const navigate = useNavigate()
  const plan = state.currentPlan
  if (!plan) return <p>먼저 구성을 만들어주세요.</p>
  return <div className="result-panel">
    {plan.checkSnapshot && <section className="parts-list-card transferred-conditions">
      <h2>전달된 점검 조건</h2>
      <p style={{ whiteSpace: 'pre-line' }}>{plan.checkSnapshot.question || '질문 미입력'}</p>
      <p>처음 입력한 예산: {plan.checkSnapshot.budget || '미입력'}</p>
      <ul>{plan.checkSnapshot.rows.map(row => <li key={row.part}>{row.part}: {row.matched}</li>)}</ul>
      <button type="button" className="ghost-btn" onClick={() => navigate('/check/review')}>입력·부품 다시 수정</button>
      <p className="setup-hint">{isMockApi ? '아래는 샘플 업그레이드입니다. 실제 추천·호환성 분석은 아직 연결되지 않았습니다.' : '입력하지 않은 유지 부품 정보(플랫폼·메모리 종류·파워 용량)는 확인하지 못한 채 추천합니다. 구매 전에 호환성을 다시 확인해주세요.'}</p>
    </section>}
    <BudgetOverview />
    <CompatNotice />
    <button className="analyze-btn" type="button" style={{ margin: '14px 0 18px' }} onClick={() => navigate('/plan/confirm')}>이 구성으로 리스트 확정하기 →</button>
    <PartsList />
    <DigitalTwin onOpenDeskModal={onOpenDeskModal} />
  </div>
}
