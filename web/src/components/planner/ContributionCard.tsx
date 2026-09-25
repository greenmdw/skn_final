import { usePlan } from '../../state/PlanContext'

// 축 이름은 서버가 정한다(가격·성능·밸런스·리뷰·호환여유). 화면은 뜻만 덧붙인다 — 모르는 축이 오면 설명 없이 그대로 보여 준다.
const MEANING: Record<string, string> = {
  가격: '예산 대비 얼마나 저렴한 부품인가',
  성능: '부품의 성능 등급',
  밸런스: '다른 부품과 성능 등급이 얼마나 어울리는가',
  리뷰: '리뷰에서 관측된 신호(진위 판정이 아니라 상품 단위 관측)',
  호환여유: '소켓·전력·크기 등 호환 검사에서 여유가 얼마나 있는가',
  소음: '소음 관련 스펙',
}

// 추천 당시 고른 구성이 점수를 어느 축에서 얻었는지. 서버가 [3-B] 점수의 축별 항을 부품마다 더해 낸 값이다.
export function ContributionCard() {
  const { state } = usePlan()
  const shares = state.currentPlan?.contribution
  if (!shares?.length) return null
  return <section className="contribution-card" aria-label="추천 기여도">
    <h2>이 구성이 점수를 얻은 곳</h2>
    <ul>{shares.map(({ axis, percent }) => <li key={axis} title={MEANING[axis]}>
      <span className="contribution-axis">{axis}</span>
      <span className="contribution-track" role="img" aria-label={axis + ' ' + percent + '%'}><span className="contribution-fill" style={{ width: percent + '%' }} /></span>
      <strong>{percent}%</strong>
    </li>)}</ul>
    <p className="setup-hint">추천 당시 구성 기준이고 합은 100%입니다. 부품을 바꿔도 이 값은 그대로예요.</p>
  </section>
}
