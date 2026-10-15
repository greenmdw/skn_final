import type { QuoteGuideRef, QuoteSavedComparison, QuoteVisual } from '../../api'
import { signedWon, wonText } from '../../utils/checkReview'
import { Linkified } from '../../utils/linkify'
import AnswerVisual, { GuideRefs } from './AnswerVisual'

export interface ComparisonAnswer {
  id: string
  question: string
  reply: string
  visuals: QuoteVisual[]
  guideRefs: QuoteGuideRef[]
  loading?: boolean
  via?: 'agent' | 'rules' | null
}

export default function SavedComparisonPanel({ comparison, differenceOnly, onDifferenceOnly, onClose, answers, openIds, onToggle, onCollapseAll, pulse }: {
  comparison: QuoteSavedComparison
  differenceOnly: boolean
  onDifferenceOnly: (value: boolean) => void
  onClose: () => void
  answers: ComparisonAnswer[]
  openIds: Set<string>
  onToggle: (id: string, open: boolean) => void
  onCollapseAll: () => void
  pulse: number
}) {
  const rows = differenceOnly ? comparison.rows.filter(row => !row.sameProduct) : comparison.rows
  const { totalDiff } = comparison
  // 올린 두 견적끼리 비교(draft_quotes)는 두 견적의 이름을 쓰고, 저장 견적 비교는 기존 문구("받은 견적"·저장 견적 이름)를 쓴다.
  const between = comparison.kind === 'draft_quotes'
  const labelA = between ? comparison.labels.received : '받은 견적'
  const labelB = between ? comparison.labels.saved : '저장한 견적'
  const comparable = comparison.comparableCategories.length
  // 사진에 가격이 없으면 합계가 0으로 오므로, 그 쪽에 가격이 하나도 없으면 "0원" 대신 "금액 정보 없음"으로 보인다(모르는 값을 0으로 말하지 않는다).
  const hasPrice = (side: 'received' | 'saved') => comparison.rows.some(row => row[side]?.lineTotal != null)
  const totalText = (side: 'received' | 'saved', total: number) => (hasPrice(side) ? wonText(total) : '금액 정보 없음')
  const noDiff = comparable === 0
  const points = [
    `다른 부품 · ${comparison.briefSummary.changedCount}/${comparison.rows.length}`,
    comparison.briefSummary.largestPriceDifferenceCategory ? `가장 큰 가격 차이 · ${comparison.briefSummary.largestPriceDifferenceCategory}` : '가격 비교 가능한 항목 없음',
    between ? `${labelA} ↔ ${labelB}` : `저장 견적 · ${comparison.savedName}`,
  ]

  return (
    <section className="ck-card ck-saved-comparison show" id="ck-saved-comparison">
      <div className="ck-saved-compare-head">
        <div><small>{between ? '올린 두 견적' : '받은 견적과 저장 견적'}</small><h3>{between ? `견적 비교 · ${labelA} ↔ ${labelB}` : `저장 견적 비교 · ${comparison.savedName}`}</h3></div>
        <label className="ck-diff-toggle"><input type="checkbox" checked={differenceOnly} onChange={event => onDifferenceOnly(event.target.checked)} /> 다른 부품만 보기</label>
        <button type="button" className="ck-close" onClick={onClose} aria-label="비교 닫기">×</button>
      </div>

      <div className="ck-compare-overview">
        <div className="ck-overview-item"><small>{labelA} 합계</small><strong>{totalText('received', comparison.receivedTotal)}</strong></div>
        <div className="ck-overview-item"><small>{between ? labelB : comparison.savedName} 합계</small><strong>{totalText('saved', comparison.savedTotal)}</strong></div>
        <div className={`ck-overview-item delta ${totalDiff < 0 ? 'less' : 'more'}`} title="금액이 양쪽에 모두 있는 부품만 비교한 차이예요">
          <small>{between ? `${labelB}와(과)의 차이` : '저장 견적과의 차이'} · {comparable}개 부품 기준</small><strong>{noDiff ? '비교 불가' : totalDiff === 0 ? '0원' : signedWon(totalDiff)}</strong>
        </div>
      </div>

      {comparison.criteria.length > 0 && (
        <div className="ck-criteria" aria-label="기준별 비교">
          <b>기준별 비교 <span>· 기준마다 따로 봐요</span></b>
          <table>
            <thead><tr><th>기준</th><th>{labelA}</th><th>{labelB}</th><th>어느 쪽이 더 좋은가</th></tr></thead>
            <tbody>
              {comparison.criteria.map(row => (
                <tr key={row.key} className={row.info ? 'info' : ''}>
                  <td>{row.label}</td>
                  <td className={row.better === 'a' ? 'win' : ''}>{row.aText}</td>
                  <td className={row.better === 'b' ? 'win' : ''}>{row.bText}</td>
                  <td>{row.info ? '참고' : row.better === 'a' ? `${labelA} 쪽이 ${row.higherIsBetter ? '높음' : '낮음'}` : row.better === 'b' ? `${labelB} 쪽이 ${row.higherIsBetter ? '높음' : '낮음'}` : row.better === 'tie' ? '같음' : '비교 안 함(확인 못 한 값)'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <small>기준마다 값을 나란히 놓은 것이며, 어느 견적이 종합적으로 더 낫다고 판단하지 않아요. 카탈로그로 확정되지 않은 부품은 호환·등급이 &quot;확인 못 함&quot;으로 남아요.</small>
        </div>
      )}

      <div className="ck-saved-compare-columns"><span>부품</span><span>{labelA}</span><span>{labelB}</span><span style={{ textAlign: 'right' }}>가격 차이</span></div>
      <div>
        {rows.map(row => {
          const diff = row.priceDiff
          const tone = diff == null || diff === 0 ? '' : diff > 0 ? 'delta-up' : 'delta-down'
          return (
            <div className={`ck-saved-compare-row${row.sameProduct ? '' : ' changed'}`} key={row.category}>
              <div className="ck-slot-cell"><b>{row.category}</b><span className={`ck-difference-badge ${row.sameProduct ? 'same' : 'changed'}`}>{row.sameProduct ? '같음' : '다름'}</span></div>
              <div className="ck-quote-product"><b>{row.received?.name ?? `${labelA}에 없음`}</b><span>{row.received ? `×${row.received.quantity} · ${wonText(row.received.lineTotal)}` : '—'}</span></div>
              <div className="ck-quote-product"><b>{row.saved?.name ?? (between ? `${labelB}에 없음` : '저장 정보 없음')}</b><span>{row.saved ? `×${row.saved.quantity} · ${wonText(row.saved.lineTotal)}` : '—'}</span></div>
              <div className={`ck-row-delta ${tone}`}>{diff == null ? '비교 불가' : diff === 0 ? '0원' : signedWon(diff)}</div>
            </div>
          )
        })}
        {rows.length === 0 && <div className="ck-table-empty">다른 부품이 없습니다.</div>}
      </div>

      <div className="ck-saved-compare-summary">
        <div className="ck-numeric-summary">
          받은 견적 <b>{totalText('received', comparison.receivedTotal)}</b> · 저장한 견적 <b>{totalText('saved', comparison.savedTotal)}</b> ·{' '}
          {noDiff ? '금액이 양쪽에 모두 있는 부품이 없어 가격 차이는 비교하지 않았어요.' : totalDiff === 0 ? '비교한 부품의 합계가 같아요.' : <>저장한 견적이 <b className={totalDiff > 0 ? 'delta-up' : 'delta-down'}>{wonText(Math.abs(totalDiff))} {totalDiff > 0 ? '비쌉니다' : '저렴합니다'}</b>.</>}{' '}
          {comparison.excludedReceivedCategories.length > 0
            ? `금액을 인식하지 못한 ${comparison.excludedReceivedCategories.join('·')}은(는) 합계에서 제외했습니다.`
            : '금액을 인식하지 못한 품목은 합계에서 제외합니다.'}
        </div>

        <article className={`ck-llm-insight${pulse ? ' answer-updated' : ''}`} key={pulse}>
          <div className="ck-llm-mark">AI</div>
          <div>
            <div className="ck-llm-head"><b>두 견적 차이 해설</b><span>핵심 차이 요약</span></div>
            <p className="ck-llm-copy">{comparison.briefSummary.text} 더 궁금한 차이는 왼쪽 대화창에서 질문해 주세요.</p>
            <div className="ck-llm-points">{points.map(point => <span key={point}>{point}</span>)}</div>

            {answers.length > 0 && (
              <section className="ck-llm-history">
                <div className="ck-llm-history-head"><b>질문별 해설 <span>· {answers.length}개</span></b><button type="button" onClick={onCollapseAll}>모두 접기</button></div>
                {answers.map(answer => (
                  <details className={`ck-llm-answer${answer.loading ? ' loading' : ''}`} id={`ck-answer-${answer.id}`} key={answer.id} open={openIds.has(answer.id)}
                    onToggle={event => onToggle(answer.id, (event.currentTarget as HTMLDetailsElement).open)}>
                    <summary><span>{answer.question}</span><small>{answer.loading ? '답변 작성 중' : '답변 보기'}</small></summary>
                    <div className="ck-llm-answer-body">
                      <p><Linkified text={answer.reply} /></p>
                      {!answer.loading && answer.visuals.map((visual, index) => <AnswerVisual key={`${visual.type}-${index}`} visual={visual} />)}
                      {!answer.loading && <GuideRefs refs={answer.guideRefs} />}
                    </div>
                  </details>
                ))}
              </section>
            )}
          </div>
          <p className="ck-llm-disclaimer">요약 문장과 금액은 서버가 계산한 값이고, 질문별 해설은 AI가 현재 확인 가능한 상품명·규격·가격을 바탕으로 정리한 설명입니다. 정보가 없는 항목은 판단에 포함하지 않습니다.</p>
        </article>
      </div>
    </section>
  )
}
