import type { ReactNode, RefObject } from 'react'
import type { LiveSpecLookupResult, QuoteDraftAnalysis, QuoteDraftItem } from '../../api'
import { checkedAgo, conditionTags, searchedAgo, signedWon, wonText } from '../../utils/checkReview'

export type LiveLookupState = { status: 'loading' | 'done'; result?: LiveSpecLookupResult; error?: string }

const STATE_LABEL = { ok: '통과', fail: '문제', unknown: '확인 못 함', skipped: '해당 없음' } as const
const STATE_CLASS = { ok: 'ok', fail: 'miss', unknown: 'warn', skipped: 'warn' } as const

export default function AnalysisView({
  analysis, conditions, sectionRef, onBack, onOpenSaved, savedOpen, onCart, cartBusy, onUpgrade, savedPanel, liveLookup, onLiveLookup,
}: {
  analysis: QuoteDraftAnalysis
  conditions: Record<string, unknown>
  sectionRef: RefObject<HTMLElement | null>
  onBack: () => void
  onOpenSaved: () => void
  savedOpen: boolean
  onCart: () => void
  cartBusy: boolean
  onUpgrade: () => void
  savedPanel: ReactNode
  liveLookup: Record<string, LiveLookupState>
  onLiveLookup: (item: QuoteDraftItem) => void
}) {
  const checks = analysis.compat.checks
  const failed = checks.filter(check => check.state === 'fail')
  const unknown = checks.filter(check => check.state === 'unknown')
  const passed = checks.filter(check => check.state === 'ok')
  const considered = failed.length + unknown.length + passed.length

  const balance = analysis.balance
  const balanceRows = balance?.available ? balance.rows : []
  const short = balanceRows.filter(row => row.state === 'short')
  const excess = balanceRows.filter(row => row.state === 'excess')
  const shortParts = [...new Set(short.map(row => row.part))]

  const title = failed.length > 0
    ? `호환되지 않는 항목이 ${failed.length}개 있어요`
    : unknown.length > 0 ? '확인된 호환 문제는 없어요' : considered > 0 ? '확인한 호환 항목은 모두 통과했어요' : '호환 검사 결과가 없어요'

  const sentences: string[] = []
  if (considered > 0) {
    sentences.push(`호환 검사 ${considered}개 중 통과 ${passed.length}, 문제 ${failed.length}, 확인 못 함 ${unknown.length}입니다.`)
    if (failed.length > 0) sentences.push(`문제 항목: ${failed.map(check => check.label).join(', ')}.`)
    if (unknown.length > 0) sentences.push('확인 못 함은 비호환이 아니라 세부 정보가 없어 직접 확인이 필요한 항목이에요.')
  }
  if (balance?.available) {
    sentences.push(...short.slice(0, 2).map(row => row.detail), ...excess.slice(0, 1).map(row => row.detail))
    if (short.length === 0 && excess.length === 0 && balanceRows.length > 0) sentences.push(`${analysis.requirementLabel ?? '입력한 용도'} 기준으로 확인한 항목은 모두 적정해요.`)
  } else if (balance?.reason) {
    sentences.push(balance.reason)
  }

  const tags = conditionTags(conditions, analysis.requirementLabel)
  const analysisTitle = analysis.requirementLabel ? `${analysis.requirementLabel} 견적 종합 평가` : '견적 종합 평가'

  const priceRows = analysis.priceRows.length > 0
    ? analysis.priceRows.map(row => ({ part: row.category, quantity: row.quantity, quoted: row.quoteLineTotal, catalog: row.catalogLineTotal, diff: row.diffLineTotal }))
    : (analysis.prices?.rows ?? []).map(row => ({ part: row.part, quantity: row.quantity, quoted: row.quoted, catalog: row.catalog, diff: row.diff }))
  const comparable = priceRows.filter(row => row.quoted != null && row.catalog != null && row.diff != null)
  const totalDiff = comparable.reduce((sum, row) => sum + (row.diff ?? 0), 0)
  const checkedTimes = analysis.priceRows.map(row => row.catalogCheckedAt).filter((value): value is string => Boolean(value)).sort()
  const lookupItems = analysis.usedItems.filter(item => ['unmatched', 'inferred', 'candidate'].includes(item.matchStatus))

  return (
    <section className="ck-analysis-view" ref={sectionRef}>
      <header className="ck-analysis-head">
        <div>
          <small>받은 견적 점검 · 비교 분석</small>
          <h2>{analysisTitle}</h2>
          {analysis.question && <p className="ck-analysis-question">질문 · {analysis.question}</p>}
        </div>
        <button type="button" className="ck-outline" onClick={onOpenSaved}>{savedOpen ? '다른 저장 견적과 비교' : '저장 견적 비교'}</button>
      </header>

      <section className="ck-conditions-card">
        <div><small>입력하신 조건</small><b>{tags.length ? '이 조건을 기준으로 평가했어요' : '입력한 조건이 없어요'}</b></div>
        <div className="ck-condition-tags">
          {tags.length ? tags.map(tag => <span key={tag}>{tag}</span>) : <span>용도를 입력하면 용도 대비 균형도 함께 평가해요</span>}
        </div>
      </section>

      <article className="ck-verdict">
        <div className="ck-score"><strong>{considered > 0 ? passed.length : '—'}</strong><span>{considered > 0 ? `/${considered} 통과` : ''}</span></div>
        <div><h3>{title}</h3><p>{sentences.join(' ')}</p></div>
        <div className="ck-verdict-points">
          <span>✓ 호환성 {passed.length}개 통과</span>
          <span>△ 직접 확인 {unknown.length}개</span>
          {failed.length > 0 && <span>✕ 호환 문제 {failed.length}개</span>}
          {shortParts.length > 0 && <span>↗ 보강 필요 {shortParts.join('·')}</span>}
        </div>
      </article>

      <div className="ck-analysis-grid">
        <article className="ck-summary-card">
          <div className="ck-summary-title"><h3>호환 검사</h3><span>문제와 정보 부족을 먼저 보여드려요</span></div>
          {checks.length === 0 ? <div className="pl-empty">서버가 반환한 호환성 검사 항목이 없습니다.</div> : (
            <>
              <div className="ck-compat-summary">
                <span className="pass">통과 {passed.length}</span>
                <span className="attention">우선 확인 {failed.length}</span>
                <span className="unknown">정보 부족 {unknown.length}</span>
              </div>
              {failed.length > 0 && (
                <details className="ck-compat-details" open>
                  <summary>우선 확인할 항목 {failed.length}개</summary>
                  <div className="ck-compat-list">{failed.map(check => <CompatRow key={check.axis} check={check} />)}</div>
                </details>
              )}
              {unknown.length > 0 && (
                <details className="ck-compat-details" open={failed.length === 0}>
                  <summary>정보가 부족한 항목 {unknown.length}개</summary>
                  <div className="ck-compat-list">{unknown.map(check => <CompatRow key={check.axis} check={check} />)}</div>
                </details>
              )}
              {passed.length > 0 && (
                <details className="ck-compat-details">
                  <summary>통과한 항목 {passed.length}개</summary>
                  <div className="ck-compat-list">{passed.map(check => <CompatRow key={check.axis} check={check} />)}</div>
                </details>
              )}
            </>
          )}
        </article>

        <article className="ck-summary-card">
          <div className="ck-summary-title"><h3>가격 비교</h3><span>인식한 가격 vs 카탈로그 가격 · 수량 반영</span></div>
          {analysis.prices?.available && priceRows.length > 0 ? (
            <>
              <div className="ck-table-wrap">
                <table className="ck-price-table">
                  <thead><tr><th>슬롯</th><th>수량</th><th>인식한 가격</th><th>카탈로그</th><th>차이</th></tr></thead>
                  <tbody>
                    {priceRows.map(row => (
                      <tr key={row.part}>
                        <td><b>{row.part}</b></td>
                        <td>×{row.quantity}</td>
                        <td>{wonText(row.quoted)}</td>
                        <td>{row.catalog == null ? '—' : wonText(row.catalog)}</td>
                        <td className={row.diff == null || row.diff === 0 ? '' : row.diff > 0 ? 'delta-up' : 'delta-down'}>{row.diff == null ? '—' : row.diff === 0 ? '0원' : signedWon(row.diff)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="ck-price-summary">
                선택한 구성 중 가격을 비교할 수 있는 <b>{comparable.length}개 품목</b> 기준, 받은 견적이 카탈로그보다{' '}
                {totalDiff === 0 ? <b>같아요</b> : <b className={totalDiff > 0 ? 'delta-up' : 'delta-down'}>{wonText(Math.abs(totalDiff))} {totalDiff > 0 ? '비싸요' : '저렴해요'}</b>}.
                선택하지 않은 비교 제품은 합계에서 제외했습니다.
                {analysis.priceExcluded.length > 0 && ` 가격을 알 수 없어 뺀 항목 · ${analysis.priceExcluded.map(row => `${row.category}(${row.reason})`).join(', ')}.`}
              </p>
              <p className="ck-price-disclaimer">ⓘ 카탈로그와 판매처 가격은 시점·재고·배송비에 따라 달라질 수 있습니다.{checkedTimes.length > 0 && ` 카탈로그 가격 ${checkedAgo(checkedTimes[checkedTimes.length - 1])}.`}</p>
            </>
          ) : <div className="pl-empty">{analysis.prices?.reason ?? '가격 비교 결과가 없습니다.'}</div>}
        </article>
      </div>

      {analysis.compare?.available && analysis.compare.notes.length > 0 && (
        <article className="ck-summary-card ck-notes-card">
          <div className="ck-summary-title"><h3>우리 추천과 비교</h3><span>같은 조건으로 추천한 구성과의 차이</span></div>
          <ul>{analysis.compare.notes.map(note => <li key={note}>{note}</li>)}</ul>
        </article>
      )}

      {savedPanel}

      {lookupItems.length > 0 && (
        <article className="ck-summary-card ck-unmatched-card">
          <div className="ck-summary-title"><h3>정확한 정보를 못 찾은 부품</h3><span>카탈로그에 없거나, 비슷한 제품·글에서 짐작한 값으로 점검한 부품이에요</span></div>
          <div className="ck-unmatched-list">
            {lookupItems.map(item => {
              const lookup = liveLookup[item.id]
              return (
                <div className="ck-unmatched-row" key={item.id}>
                  <div className="ck-unmatched-head">
                    <div><b>{item.category}</b><span>{item.name}</span></div>
                    {!lookup && <button type="button" className="ck-group-compare" onClick={() => onLiveLookup(item)}>실시간으로 찾아볼까요?</button>}
                    {lookup?.status === 'loading' && <span className="ck-unmatched-loading"><span className="pl-spin" />검색 중…</span>}
                  </div>
                  {lookup?.status === 'done' && (
                    <div className="ck-unmatched-result">
                      {lookup.error ? <p className="bad">{lookup.error}</p>
                        : lookup.result && lookup.result.relevant && Object.values(lookup.result.supportedFields).some(value => value != null) ? (
                          <>
                            <dl>
                              {Object.entries(lookup.result.supportedFields).filter(([, value]) => value != null).map(([key, value]) => (
                                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
                              ))}
                            </dl>
                            {lookup.result.sourceUrl && <p className="ck-unmatched-source">출처: <a href={lookup.result.sourceUrl} target="_blank" rel="noreferrer">{lookup.result.sourceUrl}</a></p>}
                            {lookup.result.referencePrice != null && <p className="ck-unmatched-source">참고가 약 {lookup.result.referencePrice.toLocaleString('ko-KR')}원 · 합계·가격 비교에는 넣지 않았어요</p>}
                            <p className="ck-unmatched-disclaimer">
                              {lookup.result.reviewStatus === 'confirmed' && <span className="ck-unmatched-badge">확인됨</span>}
                              {searchedAgo(lookup.result.fetchedAt)} · 카탈로그 정식 등재 값이 아니라 실시간 검색 결과예요 — 구매 전 공식 사이트에서 다시 확인하세요.
                            </p>
                          </>
                        ) : (
                          <p className="ck-unmatched-disclaimer">실시간 검색으로도 찾지 못했어요. <button type="button" className="ck-unmatched-retry" onClick={() => onLiveLookup(item)}>다시 시도</button></p>
                        )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </article>
      )}

      <div className="ck-analysis-actions">
        <button type="button" className="ck-outline" onClick={onBack}>인식 결과 고치기</button>
        <button type="button" className="ck-outline" onClick={onUpgrade} title="이 견적의 부품을 유지하고, 예산 안에서 바꾸면 좋은 부품을 추천받아요">업그레이드 추천 받기</button>
        <button type="button" className="ck-primary" disabled={cartBusy} onClick={onCart}>{cartBusy ? '반영 중…' : '이 견적으로 장바구니 담기'}</button>
      </div>
    </section>
  )
}

function CompatRow({ check }: { check: QuoteDraftAnalysis['compat']['checks'][number] }) {
  return (
    <div className="ck-compat-row">
      <span className={`ck-status ${STATE_CLASS[check.state]}`}>{STATE_LABEL[check.state]}</span>
      <div><b>{check.label}</b><p>{check.detail}</p></div>
    </div>
  )
}
