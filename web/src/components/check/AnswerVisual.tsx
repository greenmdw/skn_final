import { useState } from 'react'
import type { QuoteGuideRef, QuoteVisual } from '../../api'
import { wonText } from '../../utils/checkReview'

const STATE_LABEL: Record<string, string> = { ok: '통과', fail: '문제', unknown: '확인 못 함', skipped: '해당 없음' }

function cell(value: unknown, moneyColumn: boolean, deltaColumn: boolean): { text: string; tone: string } {
  if (value == null || value === '') return { text: '—', tone: '' }
  if (Array.isArray(value)) return { text: value.map(String).join(', '), tone: '' }
  if (typeof value === 'number') {
    if (deltaColumn) return { text: `${value > 0 ? '+' : ''}${value.toLocaleString('ko-KR')}원`, tone: value > 0 ? 'positive' : value < 0 ? 'negative' : '' }
    return { text: moneyColumn ? `${value.toLocaleString('ko-KR')}원` : value.toLocaleString('ko-KR'), tone: '' }
  }
  return { text: String(value), tone: '' }
}

function ProductCard({ item, category }: { item: Extract<QuoteVisual, { type: 'product_comparison' }>['items'][number]; category: string | null }) {
  const [broken, setBroken] = useState(false)
  const side = item.side === 'received' ? '받은 견적' : item.side === 'saved' ? '저장 견적' : item.side
  return (
    <div className="ck-answer-product-card">
      {item.imageUrl && !broken
        ? <img src={item.imageUrl} alt={`${item.name} 제품 이미지`} loading="lazy" onError={() => setBroken(true)} />
        : <div className="ck-answer-product-fallback" aria-hidden="true">{category ?? '제품'}</div>}
      <div className="ck-answer-product-copy">
        <small>{side}{category ? ` · ${category}` : ''}</small>
        <b title={item.name}>{item.name}</b>
        <span>{item.price == null ? '가격 정보 없음' : wonText(item.price)}</span>
      </div>
    </div>
  )
}

export function GuideRefs({ refs }: { refs: QuoteGuideRef[] }) {
  return (
    <>
      {refs.map(ref => (
        <aside className="ck-answer-guide" key={`${ref.id}-${ref.kind}`}>
          <div className="ck-answer-guide-mark">i</div>
          <div className="ck-answer-guide-copy">
            <small>제품 가이드 참고</small>
            <b>{ref.slot} {ref.kind === 'install' ? '설치 가이드' : '구매 전 확인'}</b>
            <p>{ref.text}</p>
          </div>
        </aside>
      ))}
    </>
  )
}

export default function AnswerVisual({ visual }: { visual: QuoteVisual }) {
  if (visual.type === 'product_comparison') {
    return (
      <section className="ck-answer-visual">
        <div className="ck-answer-visual-title"><b>{visual.title}</b>{visual.category && <small>{visual.category}만 개별 비교</small>}</div>
        <div className="ck-answer-product-grid">
          {visual.items.map(item => <ProductCard key={`${item.side}-${item.name}`} item={item} category={visual.category} />)}
        </div>
      </section>
    )
  }

  if (visual.type === 'table') {
    const moneyTitle = /가격/.test(visual.title)
    return (
      <section className="ck-answer-visual">
        <div className="ck-answer-visual-title"><b>{visual.title}</b>{visual.category && <small>{visual.category}</small>}</div>
        <div className="ck-answer-table-wrap">
          <table className="ck-answer-table">
            <thead><tr>{visual.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {visual.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((value, index) => {
                    const diffColumn = /차이/.test(visual.columns[index] ?? '')
                    const rendered = cell(value, moneyTitle && index > 0 && !diffColumn, diffColumn)
                    return <td key={index} className={rendered.tone}>{rendered.text}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    )
  }

  const axes = [...new Set(visual.items.map(item => item.axis || item.label))]
  const find = (axis: string, side: string) => visual.items.find(item => (item.axis || item.label) === axis && item.side === side)
  return (
    <section className="ck-answer-visual">
      <div className="ck-answer-visual-title"><b>{visual.title}</b><small>완성 구성 기준</small></div>
      <div className="ck-answer-table-wrap">
        <table className="ck-answer-table">
          <thead><tr><th>검사 항목</th><th>받은 견적</th><th>저장 견적</th></tr></thead>
          <tbody>
            {axes.map(axis => {
              const received = find(axis, 'received')
              const saved = find(axis, 'saved')
              const label = (received ?? saved)?.label || axis
              const render = (item: typeof received) => item
                ? <><span className={`ck-answer-state ${item.state}`}>{STATE_LABEL[item.state] ?? item.state}</span><br /><small>{item.detail}</small></>
                : '—'
              return <tr key={axis}><td>{label}</td><td>{render(received)}</td><td>{render(saved)}</td></tr>
            })}
          </tbody>
        </table>
      </div>
      <p className="ck-answer-visual-note">※ 호환 판정은 서버의 규격 데이터로 계산한 값입니다. 확인 못 함은 비호환이 아니라 정보가 없다는 뜻이에요.</p>
    </section>
  )
}
