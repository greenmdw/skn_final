import { BudgetEditor } from './BudgetEditor'
import { wonFmt } from '../../utils/format'
import { usePlan } from '../../state/PlanContext'
import { isMockApi } from '../../api'

export function GoalPanel() {
  const { state, startAnalysis } = usePlan()
  const progress = state.stage === 1 ? 46 : 82
  const perf = state.performance || '확인 중'
  const quiet = state.quiet || '확인 중'

  return (
    <div className="goal-panel">
      <div className="status-line"><span className="status-pulse" />조건 수집 중 · {progress}%</div>
      <h2 className="goal-heading">입력한 조건을 확인해주세요</h2>
      <div className="goal-grid">
        <div className="goal-card"><span>주요 용도</span><strong>{state.intent}</strong><em>우선순위 높음</em></div>
        <div className="goal-card"><span>최대 예산</span><strong>{state.budget === null ? '미설정' : wonFmt(state.budget)}</strong><em>본체 + 모니터</em></div>
        <div className="goal-card"><span>성능 목표</span><strong>{perf}</strong><em>게임 프레임</em></div>
        <div className="goal-card"><span>소음 선호</span><strong>{quiet}</strong><em>작업 환경</em></div>
        <div className="goal-card"><span>저장 공간</span><strong>2TB</strong><em>추천값 적용</em></div>
        <div className="goal-card"><span>구매 시점</span><strong>이번 달</strong><em>{isMockApi ? '가상 시세 기준' : '데모 가격 기준'}</em></div>
      </div>
      <BudgetEditor />
      <div className="readiness">
        <div className="readiness-head"><span>분석 준비도</span><strong>{progress}%</strong></div>
        <div className="readiness-track"><div className="readiness-fill" style={{ width: progress + '%' }} /></div>
      </div>
      {state.stage >= 2 && state.quiet ? (
        <button className="analyze-btn" type="button" onClick={startAnalysis}>AI 구성 분석 시작 <span>→</span></button>
      ) : (
        <button className="analyze-btn" type="button" disabled>조건을 조금 더 알려주세요</button>
      )}
    </div>
  )
}
