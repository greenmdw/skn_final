import { BudgetEditor } from './BudgetEditor'
import { wonFmt } from '../../utils/format'
import { usePlan } from '../../state/PlanContext'
import { isMockApi } from '../../api'

export function GoalPanel() {
  const { state, startAnalysis } = usePlan()
  // 실서버는 세션이 판정한 can_recommend로 준비 여부를 본다(한 문장에 조건이 다 담기면 1턴만에 준비될 수 있다).
  // 목업은 세션이 없어 예전처럼 정해진 3단계를 다 거쳤는지로 본다.
  const ready = isMockApi ? state.stage >= 2 && !!state.quiet : state.canRecommend
  // 목업은 예전 그대로(정해진 질문 단계 기준). 실서버는 세션이 준비됐다고 판정할 때만 82%로 올린다.
  const progress = isMockApi ? (state.stage === 1 ? 46 : 82) : (ready ? 82 : state.stage === 1 ? 46 : 20)
  const intent = state.intent || '확인 중'
  const perf = state.performance || '확인 중'
  const quiet = state.quiet || '확인 중'

  return (
    <div className="goal-panel">
      <div className="status-line"><span className="status-pulse" />조건 수집 중 · {progress}%</div>
      <h2 className="goal-heading">입력한 조건을 확인해주세요</h2>
      <div className="goal-grid">
        <div className="goal-card"><span>주요 용도</span><strong>{intent}</strong><em>우선순위 높음</em></div>
        <div className="goal-card"><span>최대 예산</span><strong>{state.budget === null ? '미설정' : wonFmt(state.budget)}</strong><em>본체 + 모니터</em></div>
        <div className="goal-card"><span>성능 목표</span><strong>{perf}</strong><em>게임 프레임</em></div>
        <div className="goal-card"><span>소음 선호</span><strong>{quiet}</strong><em>작업 환경</em></div>
        <div className="goal-card"><span>저장 공간</span><strong>2TB</strong><em>추천값 적용</em></div>
        <div className="goal-card"><span>구매 시점</span><strong>이번 달</strong><em>{isMockApi ? '가상 시세 기준' : '데모 가격 기준'}</em></div>
      </div>
      <BudgetEditor />
      {!isMockApi && state.budgetWarning && <div className={'budget-warning ' + state.budgetWarning.level} role="status">
        <strong>{state.budgetWarning.level === 'infeasible' ? '예산이 부족할 수 있어요' : '예산이 빠듯해요'}</strong>
        <span>{state.budgetWarning.message}</span>
      </div>}
      <div className="readiness">
        <div className="readiness-head"><span>분석 준비도</span><strong>{progress}%</strong></div>
        <div className="readiness-track"><div className="readiness-fill" style={{ width: progress + '%' }} /></div>
      </div>
      {ready ? (
        <button className="analyze-btn" type="button" onClick={startAnalysis}>AI 구성 분석 시작 <span>→</span></button>
      ) : (
        <button className="analyze-btn" type="button" disabled>조건을 조금 더 알려주세요</button>
      )}
    </div>
  )
}
