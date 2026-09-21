import { usePlan } from '../state/PlanContext'
import { useNavigate } from 'react-router-dom'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function StartPage() {
  useDocumentTitle('시작하기')
  const navigate = useNavigate()
  const { resetPlan } = usePlan()

  return (
    <section className="landing" aria-labelledby="landingTitle">
      <div className="landing-inner">
        <button type="button" className="back-link" onClick={() => navigate('/')}>← 처음으로</button>
        <p className="eyebrow">CHOOSE YOUR STARTING POINT</p>
        <h1 className="landing-title" id="landingTitle">지금 필요한 도움부터<br />바로 시작하세요.</h1>
        <p className="landing-desc">새 PC를 처음부터 구성하거나, 사용 중인 PC와 작성해둔 견적을 점검할 수 있습니다.</p>
        <div className="landing-grid">
          <button className="landing-card" type="button" onClick={() => { resetPlan(); navigate('/plan') }}>
            <span className="landing-icon" aria-hidden="true">＋</span>
            <strong>새 PC 처음부터 구성</strong>
            <span className="landing-card-desc">하고 싶은 일과 예산을 알려주면 전체 부품 구성과 구매 시점을 추천합니다.</span>
            <span className="landing-link">추천 요청 시작 →</span>
          </button>
          <button className="landing-card" type="button" onClick={() => navigate('/check')}>
            <span className="landing-icon" aria-hidden="true">✓</span>
            <strong>내 PC·견적 점검</strong>
            <span className="landing-card-desc">현재 PC 업그레이드 또는 작성한 견적을 파일과 시스템 정보로 검토합니다.</span>
            <span className="landing-link">점검 시작 →</span>
          </button>
        </div>
      </div>
    </section>
  )
}
