import { useEffect, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { QuoteDraft, QuoteDraftComparison, QuoteMatchStatus } from '../../api'
import { itemStatus, signedWon, sourceBadge, wonText } from '../../utils/checkReview'

export type CompareChoice = { kind: 'recognized'; itemId: string } | { kind: 'recommended'; productId: string }

const MATCH_LABEL: Record<QuoteMatchStatus, string> = {
  confirmed: '카탈로그 대응', ambiguous: '후보 여러 개', candidate: '비슷한 제품', inferred: '글에서 일부만 읽음', unmatched: '카탈로그에 없음',
}

function specText(value: unknown, unit: string): string {
  if (value == null || value === '') return '정보 없음'
  if (typeof value === 'number') return `${value.toLocaleString('ko-KR')}${unit}`
  return `${String(value)}${unit && typeof value === 'string' && !value.endsWith(unit) ? unit : ''}`
}

function pressToChoose(action: () => void) {
  return (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action() }
  }
}

export default function PartCompareDialog({ category, data, loading, error, draft, selectedItemId, choice, onChoice, onApply, onClose }: {
  category: string
  data: QuoteDraftComparison | null
  loading: boolean
  error: string
  draft: QuoteDraft
  selectedItemId: string | undefined
  choice: CompareChoice | null
  onChoice: (choice: CompareChoice) => void
  onApply: () => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const recognized = data?.recognized ?? []
  const recommended = data?.recommended ?? []
  const isRecognized = choice?.kind === 'recognized'
  const isCurrentChoice = choice?.kind === 'recognized' && choice.itemId === selectedItemId

  return (
    <div className="ck-dialog-back" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section className="ck-dialog ck-compare-dialog" role="dialog" aria-modal="true" aria-label={`${category} 제품 비교`}>
        <div className="ck-modal-head">
          <div>
            <h2>{category} 제품 비교</h2>
            <p className="ck-modal-intro">{data ? `인식 제품 ${recognized.length}개와 추가 추천 제품 ${recommended.length}개를 함께 비교합니다.` : '인식 제품과 추가 추천 제품의 가격·핵심 사양·호환 사실을 나란히 확인하세요.'}</p>
          </div>
          <button type="button" className="ck-close" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="ck-modal-grid">
          {loading && <div className="ck-modal-state"><div className="pl-spin" /><span>같은 부품군 후보를 불러오는 중이에요…</span></div>}
          {!loading && error && <div className="ck-modal-state bad" role="alert">{error}</div>}
          {!loading && !error && data && (
            <>
              {data.notes.length > 0 && <div className="ck-compare-note">{data.notes.join(' · ')}</div>}
              <div className="ck-compare-section-title"><b>견적에서 인식한 제품</b><span>{recognized.length}개</span></div>
              {recognized.map((option, index) => {
                const item = draft.items.find(entry => entry.id === option.itemId)
                const status = item ? itemStatus(item) : null
                const current = option.itemId === selectedItemId
                const selected = choice?.kind === 'recognized' && choice.itemId === option.itemId
                return (
                  <div role="button" tabIndex={0} key={option.itemId} className={`ck-candidate${selected ? ' current' : ''}`} onClick={() => onChoice({ kind: 'recognized', itemId: option.itemId })} onKeyDown={pressToChoose(() => onChoice({ kind: 'recognized', itemId: option.itemId }))} aria-pressed={selected}>
                    <div className="ck-candidate-kicker"><span className={`ck-status ${status?.tone ?? 'ok'}`}>인식 제품 {index + 1}</span><b>{current ? '현재 분석 기준' : '인식된 비교안'}</b></div>
                    <div className="ck-candidate-source">{item ? `견적 이미지 ${sourceBadge(item, draft)}` : '받은 견적'} · {MATCH_LABEL[option.matchStatus]}</div>
                    <h3>{option.name}{option.quantity > 1 ? ` × ${option.quantity}` : ''}</h3>
                    <div className="ck-amount">{wonText(option.quoteLineTotal)}</div>
                    <div className="ck-candidate-specs">
                      {option.specs.slice(0, 4).map(spec => <span key={spec.key}>{spec.label}<b>{specText(spec.candidate, spec.unit)}</b></span>)}
                      {option.specs.length === 0 && <span>사양<b>확인된 정보 없음</b></span>}
                    </div>
                    <p>{status?.checked ? '카탈로그와 대응된 제품이에요.' : '모델을 정확히 확인하지 못해 사양을 비교할 수 없는 항목이 있어요.'}</p>
                  </div>
                )
              })}

              <div className="ck-compare-section-title"><b>추가 추천 제품</b><span>{recommended.length}개 · 현재 구성과 같은 부품군</span></div>
              {recommended.length === 0 && <div className="ck-compare-empty">지금 구성에서 추천할 수 있는 같은 부품군 제품을 찾지 못했어요.</div>}
              {recommended.map((option, index) => {
                const selected = choice?.kind === 'recommended' && choice.productId === option.productId
                const delta = option.priceDelta
                return (
                  <div role="button" tabIndex={0} key={option.productId} className={`ck-candidate recommended${selected ? ' current' : ''}`} onClick={() => onChoice({ kind: 'recommended', productId: option.productId })} onKeyDown={pressToChoose(() => onChoice({ kind: 'recommended', productId: option.productId }))} aria-pressed={selected}>
                    <div className="ck-candidate-kicker"><span className="ck-status ok">추천 제품 {index + 1}</span><b>{delta == null ? '가격 차이 정보 없음' : delta === 0 ? '가격 같음' : `${Math.abs(delta).toLocaleString('ko-KR')}원 ${delta > 0 ? '높음' : '낮음'}`}</b></div>
                    <div className="ck-candidate-source">카탈로그·호환 규칙 기반</div>
                    <h3>{option.name}</h3>
                    <div className="ck-amount">{wonText(option.price)}</div>
                    <div className="ck-candidate-specs">
                      {option.specs.slice(0, 4).map(spec => <span key={spec.key}>{spec.label}<b>{specText(spec.candidate, spec.unit)}</b></span>)}
                      {option.specs.length === 0 && <span>사양<b>확인된 정보 없음</b></span>}
                    </div>
                    {option.reason && <p>{option.reason}</p>}
                    {option.incompatible.length > 0 && <p className="ck-candidate-warn">⚠ 현재 구성과 호환 문제 · {option.incompatible.join(', ')}</p>}
                    {option.compatChanges.filter(change => change.to !== 'ok').slice(0, 3).map(change => (
                      <p className="ck-candidate-warn" key={`${change.axis}-${change.to}`}>{change.label} · {change.detail}</p>
                    ))}
                    {option.additionalReplacements.length > 0 && (
                      <p className="ck-candidate-warn">함께 바꿔야 할 부품 · {option.additionalReplacements.map(row => `${row.category}(${row.reason})`).join(', ')}</p>
                    )}
                    {delta != null && <p className={delta > 0 ? 'ck-delta-up' : 'ck-delta-down'}>받은 견적 대비 {signedWon(delta)}</p>}
                  </div>
                )
              })}
            </>
          )}
        </div>

        <div className="ck-modal-foot">
          <span className="ck-modal-foot-note">
            {isRecognized ? '선택한 인식 제품 하나만 종합 분석과 선택 합계에 반영됩니다.' : '다른 부품의 추천 제품도 계속 담은 뒤 한 번에 반영할 수 있습니다.'}
          </span>
          <button type="button" className="ck-primary" disabled={!choice || loading || isCurrentChoice} onClick={onApply}>
            {isRecognized ? (isCurrentChoice ? '현재 분석 기준이에요' : '이 제품을 분석 기준으로 선택') : '추천 제품을 교체 목록에 담기'}
          </button>
        </div>
      </section>
    </div>
  )
}
