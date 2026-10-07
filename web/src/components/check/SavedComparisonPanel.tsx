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
  const comparable = comparison.comparableCategories.length
  const points = [
    `다른 부품 · ${comparison.briefSummary.changedCount}/${comparison.rows.length}`,
    comparison.briefSummary.largestPriceDifferenceCategory ? `가장 큰 가격 차이 · ${comparison.briefSummary.largestPriceDifferenceCategory}` : '가격 비교 가능한 항목 없음',
    `저장 견적 · ${comparison.savedName}`,
  ]

  return (
    <section className="ck-card ck-saved-comparison show" id="ck-saved-comparison">
      <div className="ck-saved-compare-head">
        <div><small>받은 견적과 저장 견적</small><h3>저장 견적 비교 · {comparison.savedName}</h3></div>
        <label className="ck-diff-toggle"><input type="checkbox" checked={differenceOnly} onChange={event => onDifferenceOnly(event.target.checked)} /> 다른 부품만 보기</label>
        <button type="button" className="ck-close" onClick={onClose} aria-label="비교 닫기">×</button>
      </div>

      <div className="ck-compare-overview">
        <div className="ck-overview-item"><small>받은 견적 합계</small><strong>{wonText(comparison.receivedTotal)}</strong></div>
        <div className="ck-overview-item"><small>{comparison.savedName} 합계</small><strong>{wonText(comparison.savedTotal)}</strong></div>
        <div className={`ck-overview-item delta ${totalDiff < 0 ? 'less' : 'more'}`} title="금액이 양쪽에 모두 있는 부품만 비교한 차이예요">
          <small>저장 견적과의 차이 · {comparable}개 부품 기준</small><strong>{totalDiff === 0 ? '0원' : signedWon(totalDiff)}</strong>
        </div>
      </div>

      <div className="ck-saved-compare-columns"><span>부품</span><span>받은 견적</span><span>저장한 견적</span><span style={{ textAlign: 'right' }}>가격 차이</span></div>
      <div>
        {rows.map(row => {
          const diff = row.priceDiff
          const tone = diff == null || diff === 0 ? '' : diff > 0 ? 'delta-up' : 'delta-down'
          return (
            <div className={`ck-saved-compare-row${row.sameProduct ? '' : ' changed'}`} key={row.category}>
              <div className="ck-slot-cell"><b>{row.category}</b><span className={`ck-difference-badge ${row.sameProduct ? 'same' : 'changed'}`}>{row.sameProduct ? '같음' : '다름'}</span></div>
              <div className="ck-quote-product"><b>{row.received?.name ?? '받은 견적에 없음'}</b><span>{row.received ? `×${row.received.quantity} · ${wonText(row.received.lineTotal)}` : '—'}</span></div>
              <div className="ck-quote-product"><b>{row.saved?.name ?? '저장 정보 없음'}</b><span>{row.saved ? `×${row.saved.quantity} · ${wonText(row.saved.lineTotal)}` : '—'}</span></div>
              <div className={`ck-row-delta ${tone}`}>{diff == null ? '비교 불가' : diff === 0 ? '0원' : signedWon(diff)}</div>
            </div>
          )
        })}
        {rows.length === 0 && <div className="ck-table-empty">다른 부품이 없습니다.</div>}
      </div>

      <div className="ck-saved-compare-summary">
        <div className="ck-numeric-summary">
          받은 견적 <b>{wonText(comparison.receivedTotal)}</b> · 저장한 견적 <b>{wonText(comparison.savedTotal)}</b> ·{' '}
          {totalDiff === 0 ? '비교한 부품의 합계가 같아요.' : <>저장한 견적이 <b className={totalDiff > 0 ? 'delta-up' : 'delta-down'}>{wonText(Math.abs(totalDiff))} {totalDiff > 0 ? '비쌉니다' : '저렴합니다'}</b>.</>}{' '}
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
