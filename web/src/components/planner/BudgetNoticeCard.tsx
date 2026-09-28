import { usePlan } from '../../state/PlanContext'
import { isMockApi } from '../../api'

// 가성비·저소음 우선이라 예산을 많이 남긴 구성에, 서버가 만든 이유 문장과 "성능 우선으로 다시" 버튼을 보여 준다.
// 버튼은 인터뷰 세션이 있는 새 구성에서만 — 업그레이드는 서버가 이 안내를 주지 않는다.
export function BudgetNoticeCard() {
  const { state, retryWithPerformance } = usePlan()
  const notice = state.currentPlan?.budgetNotice
  if (!notice) return null
  const canRetry = !isMockApi && state.mode === 'new' && !!state.sessionId
  return <section className="budget-notice" aria-label="예산 사용 안내">
    <p>{notice.message}</p>
    {canRetry && <button type="button" className="ghost-btn" onClick={retryWithPerformance}>성능 우선으로 다시 추천받기</button>}
  </section>
}
