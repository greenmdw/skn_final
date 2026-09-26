import { usePlan } from '../../state/PlanContext'
import { QUIET_LABEL } from '../../state/conditionLabels'
import { useToast } from '../../state/ToastContext'
import { wonFmt } from '../../utils/format'
import { isMockApi } from '../../api'

function EmptyEvidence() {
  return (
    <div className="evidence-card evidence-empty">
      <div className="empty-doc">⌕</div>
      <h3>아직 선택된 부품이 없어요.</h3>
      <p>PC 구성이 시작되면, 여기에서 각 부품의 가격, 성능, 호환성, 선택 이유를 자세히 확인할 수 있습니다.</p>
      <div className="info-list">
        <h4>확인할 수 있는 정보</h4>
        <div><span className="check">✓</span> 실시간 최저가 및 가격 추이</div>
        <div><span className="check">✓</span> 성능 벤치마크 데이터</div>
        <div><span className="check">✓</span> 호환성 검증 결과</div>
        <div><span className="check">✓</span> 전문 리뷰 및 사용자 평가</div>
        <div><span className="check">✓</span> TrueFit의 추천 이유</div>
      </div>
    </div>
  )
}

function GoalsEvidence({ performance, quiet }: { performance: string; quiet: string }) {
  const { state } = usePlan()
  return (
    <div className="evidence-card evidence-empty">
      <div className="empty-doc">◌</div>
      <h3>추천 준비 중이에요.</h3>
      <p>목적과 예산을 파악했습니다. 성능 목표와 사용 환경을 확인한 뒤 부품별 추천 근거를 공개합니다.</p>
      <div className="info-list">
        <h4>현재 파악한 조건</h4>
        <div><span className="check">✓</span> 목적 · {state.intent}</div>
        <div><span className="check">✓</span> 예산 · {state.budget === null ? '미설정' : wonFmt(state.budget)}</div>
        <div><span className="check">{performance ? '✓' : '○'}</span> 성능 · {performance || '확인 중'}</div>
        <div><span className="check">{quiet ? '✓' : '○'}</span> {QUIET_LABEL} · {quiet || '확인 중'}</div>
      </div>
    </div>
  )
}

function AnalyzingEvidence() {
  return (
    <div className="evidence-card evidence-empty">
      <div className="empty-doc">⌁</div>
      <h3>근거 데이터를 모으고 있어요.</h3>
      <p>가격, 벤치마크, 전력, 규격 데이터를 교차 검증하고 있습니다.</p>
      <div className="info-list">
        <h4>분석 상태</h4>
        <div><span className="check">✓</span> 사용 목적 가중치 계산</div>
        <div><span className="check">✓</span> 예산 범위 설정</div>
        <div><span className="check">…</span> 부품 조합 비교 중</div>
        <div><span className="check">○</span> 최종 근거 정리</div>
      </div>
    </div>
  )
}

function PartEvidence() {
  const { state } = usePlan()
  const p = state.currentPlan?.items.find(item => item.key === state.selectedPart)
  if (!p) return <EmptyEvidence />
  return (
    <div className="evidence-stack">
      <div className="evidence-card evidence-detail">
        <div className="product-visual">
          <div className="chip-visual">{p.label}</div>
          <span className="selected-caption">{p.type} · SELECTED</span>
          <h3 className="selected-name">{p.name}</h3>
        </div>
      </div>
      {isMockApi && (
      <section className="evidence-card trend-card">
        <div className="card-label"><span>가격 동향</span><span>{p.type}</span></div>
        <div className="trend-price">{wonFmt(p.price)}</div>
        <svg className="trend-svg" viewBox="0 0 300 132" role="img" aria-label="최근 6개월 실측 가격과 향후 예측 가격">
          <g stroke="#263944" strokeWidth={1}><path d="M12 25H288M12 64H288M12 102H288" /></g>
          <path d="M12 25 L38 38 L62 59 L88 73 L114 81 L145 86" fill="none" stroke="#60edc0" strokeWidth={3} />
          <path d="M145 86 L181 96 L218 101 L254 108 L288 115" fill="none" stroke="#ffb84d" strokeWidth={3} strokeDasharray="7 5" />
          <path d="M145 11V116" stroke="#536974" strokeDasharray="4 4" />
          <circle cx={145} cy={86} r={6} fill="#e8fff8" stroke="#60edc0" strokeWidth={4} />
          <g fill="#7e929e" fontSize={9}>
            <text x={0} y={128}>6개월 전</text>
            <text x={133} y={128}>지금</text>
            <text x={260} y={128}>6개월 후</text>
          </g>
        </svg>
        <div className="trend-legend"><span><i className="legend-line" />실제 수집 가격</span><span><i className="legend-line forecast" />예측 범위 중앙값</span></div>
        <div className="evidence-source">가격·환율 출처　<strong>{p.source.replace('API · ', '')}</strong><br />향후 값은 가상 추정이며 실제 판매가를 보장하지 않습니다.</div>
      </section>
      )}
      <section className="evidence-card ai-reason-card">
        <div className="card-label"><span>AI 추천 이유</span><span>{p.type}</span></div>
        <h3>{p.reasonTitle}</h3>
        <p>{p.fit}</p>
        <div className="reason-tags">{p.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
        <div className="reason-basis"><span>설명 근거</span><strong>사용자 목적 · 공식 스펙 · 가격</strong></div>
      </section>
      {p.checks && p.checks.length > 0 && (
      <section className="evidence-card checks-card">
        <div className="card-label"><span>호환성 · 구매 전 확인</span><span>{p.type}</span></div>
        <ul>{p.checks.map(text => <li key={text}>{text}</li>)}</ul>
      </section>
      )}
      <section className="evidence-card review-card">
        <div className="card-label"><span>리뷰</span><span>{p.type}</span></div>
        <div className="review-score"><strong>{p.rating}<small> / 5</small></strong><span>총 리뷰 수<br />{p.reviews}</span></div>
        <div className="reason-basis"><span>출처</span><strong>{isMockApi ? 'Best Buy Products API' : '리뷰 요약 데이터'}</strong></div>
      </section>
    </div>
  )
}

export function EvidencePane({ mobileActive }: { mobileActive: boolean }) {
  const { state } = usePlan()
  const { showToast } = useToast()

  let content
  if (state.stage === 0) content = <EmptyEvidence />
  else if (state.stage <= 2) content = <GoalsEvidence performance={state.performance} quiet={state.quiet} />
  else if (state.stage === 3) content = <AnalyzingEvidence />
  else content = <PartEvidence />

  return (
    <aside className={'pane evidence-pane' + (state.stage === 4 ? ' result-mode' : '') + (mobileActive ? ' mobile-active' : '')} data-pane="evidence" aria-labelledby="evidenceTitle">
      <div className="pane-heading evidence-head"><h2 id="evidenceTitle">추천 근거</h2><span className="live-hint">LIVE EVIDENCE</span></div>
      <div>{content}</div>
      {state.stage !== 4 && (
        <div className="method-card">
          <h3><span aria-hidden="true">💡</span> 어떤 기준으로 추천하나요?</h3>
          <p>{isMockApi ? '수천 개의 제품 데이터와 실사용자 리뷰, 벤치마크 결과를 가상 분석해 가격 대비 성능이 가장 좋은 구성을 추천합니다.' : '용도와 예산에 맞는 후보를 걸러 점수를 매기고, 소켓·메모리·전력 같은 호환성을 지키는 조합을 찾은 뒤 세트 전체를 다시 검증합니다.'}</p>
          <button type="button" onClick={() => showToast(isMockApi ? '이 목업의 모든 추천 정보는 가상 데이터입니다.' : '가격과 리뷰는 데모 데이터 기준입니다. 구매 전 판매처에서 다시 확인해주세요.')}>자세히 보기　→</button>
        </div>
      )}
    </aside>
  )
}
