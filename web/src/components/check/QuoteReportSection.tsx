import { useEffect, useState } from 'react'
import { quoteReportExtra, type QuoteReportExtra } from '../../api/checkV2'
import { wonText } from '../../utils/checkReview'

/** 받은 견적으로 만든 리포트인지·유지한 부품·서버가 계산한 합계를 읽는다. 다른 리포트면 source 가 recommendation 이다. */
export function useQuoteReportExtra(listId: string | undefined, revisionNo: number | null | undefined): QuoteReportExtra | null {
  const [extra, setExtra] = useState<QuoteReportExtra | null>(null)
  useEffect(() => {
    if (!listId) return
    let alive = true
    setExtra(null)
    quoteReportExtra(listId, revisionNo).then(result => { if (alive) setExtra(result) }).catch(() => { /* 섹션만 생략한다 */ })
    return () => { alive = false }
  }, [listId, revisionNo])
  return extra
}

/** 받은 견적 점검으로 만든 리포트의 "유지한 부품" — 견적에 적힌 그대로. 다른 리포트에서는 아무것도 그리지 않는다. */
export default function QuoteReportSection({ extra }: { extra: QuoteReportExtra | null }) {
  if (!extra || extra.source !== 'quote_check') return null
  return (
    <section>
      <div style={{ fontSize: 13, fontWeight: 700, padding: '14px 0 8px' }}>유지한 부품 (견적 그대로)</div>
      {extra.kept_parts.map(part => (
        <div className="pl-report-row" key={`${part.slot}-${part.source_text}`}>
          <span />
          <span className="cat" style={{ color: 'var(--muted)' }}>{part.slot_label}</span>
          <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
            <b>{part.name}{part.qty > 1 ? ` ×${part.qty}` : ''}</b>
            {part.match_status !== 'confirmed' && <span className="pl-note">카탈로그에 없는 제품 — 견적에 적힌 대로</span>}
          </div>
          <span className="pl-mono" style={{ textAlign: 'right' }}>{part.line_amount != null ? wonText(part.line_amount) : '가격 정보 없음'}</span>
          <span />
        </div>
      ))}
      {extra.quote_check?.total_partial && <div className="pl-note">가격을 모르는 부품은 합계에 넣지 않았어요.</div>}
    </section>
  )
}
