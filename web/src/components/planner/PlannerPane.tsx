import { usePlan } from '../../state/PlanContext'
import { EmptyPlan } from './EmptyPlan'
import { GoalPanel } from './GoalPanel'
import { AnalyzingPanel } from './AnalyzingPanel'
import { ResultPanel } from './ResultPanel'
import { isMockApi } from '../../api'

function getHeading(stage: number, mode: string): { title: string; desc: string } {
  if (mode === 'upgrade' && stage >= 4) {
    return { title: '선택한 업그레이드를\n플래너에서 확인하세요.', desc: '기존 PC 구성은 유지하고, 앞에서 선택한 변경 제품만 표시합니다.' }
  }
  if (stage === 0) return { title: '나에게 딱 맞는 PC를\n함께 만들어볼까요?', desc: '왼쪽에서 원하는 조건을 말씀해주시면,\nTrueFit이 분석하고 최적의 구성을 제안해드립니다.' }
  if (stage <= 2) return { title: '원하는 조건을\n하나씩 정리하고 있어요.', desc: '현재까지 이해한 목표입니다.\n대화를 마치면 최적의 부품 조합을 분석합니다.' }
  if (stage === 3) return { title: '예산 안에서 가장 좋은\n조합을 찾고 있어요.', desc: '성능, 가격, 호환성을 함께 비교하고 있습니다.\n잠시만 기다려주세요.' }
  return { title: '선택한 구성을\n확인해주세요.', desc: isMockApi ? '샘플 부품 목록 · 합계와 예산을 확인한 뒤 저장하세요.' : '부품 목록 · 합계와 예산을 확인한 뒤 확정하세요.' }
}

export function PlannerPane({ onOpenDeskModal, mobileActive }: { onOpenDeskModal: () => void; mobileActive: boolean }) {
  const { state, analyzingIndex, customHeading } = usePlan()
  const heading = customHeading ?? getHeading(state.stage, state.mode)

  let stageContent
  if (state.stage === 0) stageContent = <EmptyPlan />
  else if (state.stage <= 2) stageContent = <GoalPanel />
  else if (state.stage === 3) stageContent = <AnalyzingPanel progressIndex={analyzingIndex} />
  else stageContent = <ResultPanel onOpenDeskModal={onOpenDeskModal} />

  return (
    <section className={'pane planner-pane' + (mobileActive ? ' mobile-active' : '')} data-pane="planner" aria-labelledby="plannerTitle">
      <div className="planner-kicker"><p className="eyebrow">PLAN 01 · 나의 PC 구성</p><span className="demo-badge">{isMockApi ? '가상 데이터' : '데모 데이터'}</span></div>
      <h1 className="planner-title" id="plannerTitle" style={{ whiteSpace: 'pre-line' }}>{heading.title}</h1>
      <p className="planner-desc" style={{ whiteSpace: 'pre-line' }}>{heading.desc}</p>
      <div className="stage-shell">{stageContent}</div>
      <div className="quote">
        <div className="quote-mark">"</div>
        <p><strong>좋은 PC는 비싼 PC가 아니라,<br />당신에게 맞는 PC입니다.</strong><br /><span style={{ color: '#80939d' }}>— TrueFit</span></p>
      </div>
    </section>
  )
}
