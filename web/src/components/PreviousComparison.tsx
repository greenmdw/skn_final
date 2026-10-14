import { useEffect, useState } from 'react'
import { api, type PreviousComparison as Comparison } from '../api'
import { wonFmt } from '../utils/format'

type Loaded = Extract<Comparison, { available: true }>

const signed = (amount: number) => (amount > 0 ? '+' : amount < 0 ? '-' : '±') + wonFmt(Math.abs(amount))
const tone = (amount: number) => (amount > 0 ? 'up' : amount < 0 ? 'down' : 'same')

// 이번 추천을 이전 견적과 견준다: 바뀐 조건, 바뀐 부품(가격 차이와 이유), 그대로인 부품, 총액 차이.
// 서버가 규칙으로 만든 값이라 이유는 "요구 사양이 달라져서"인 경우에만 적히고, 그 외에는 원인을 짐작하지 않는다.
// 비교할 이전 견적이 없거나 비교할 수 없으면(서버가 available=false) 아무것도 보이지 않는다.
export default function PreviousComparison({ listId, signature }: { listId: string; signature: string }) {
  const [data, setData] = useState<Loaded | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    api.plans.previousComparison(listId)
      .then(result => { if (alive) setData(result.available ? result : null) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
    // signature: 부품·수량이 바뀌면 이번 견적도 달라지므로 다시 견준다
  }, [listId, signature])

  if (!data) return null
  const reasonOf = (slot: string) => data.reasons.find(reason => reason.slot === slot)
  return (
    <section className="pl-card pl-prevcmp" aria-label="이전 견적과 비교">
      <button type="button" className="pl-prevcmp-head" aria-expanded={open} aria-controls="pl-prevcmp-body" onClick={() => setOpen(value => !value)}>
        <span><b>이전 견적과 비교</b><small>{data.previousLabel} 견적 기준</small></span>
        <span className="pl-prevcmp-sum">
          <span>변경 부품 {data.partChanges.length}개</span>
          <span className={'diff ' + tone(data.totals.diff)}>총액 {signed(data.totals.diff)}</span>
        </span>
        <span className="chev" aria-hidden="true">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="pl-prevcmp-body" id="pl-prevcmp-body">
          <div className="pl-prevcmp-total">
            <span>{wonFmt(data.totals.before)}</span><i aria-hidden="true">→</i><b className="pl-mono">{wonFmt(data.totals.after)}</b>
            <em className={tone(data.totals.diff)}>{signed(data.totals.diff)}</em>
          </div>

          <div>
            <div className="pl-group-title">바뀐 조건</div>
            {data.conditionChanges.length > 0
              ? <ul className="pl-prevcmp-list">{data.conditionChanges.map(change => <li key={change.key}><b>{change.label}</b>{change.before} <i aria-hidden="true">→</i> {change.after}</li>)}</ul>
              : <p className="pl-note">조건은 같아요.</p>}
          </div>

          <div>
            <div className="pl-group-title">바뀐 부품</div>
            {data.partChanges.length > 0 ? (
              <div className="pl-prevcmp-parts">
                {data.partChanges.map(part => {
                  const reason = reasonOf(part.slot)
                  return (
                    <div className="pl-prevcmp-part" key={part.slot}>
                      <div className="cat">{part.label}</div>
                      <div className="names">
                        <span className="before">{part.before ?? '없음'}{part.beforePrice != null && <small>{wonFmt(part.beforePrice)}</small>}</span>
                        <i aria-hidden="true">→</i>
                        <span className="after">{part.after ?? '없음'}{part.afterPrice != null && <small>{wonFmt(part.afterPrice)}</small>}</span>
                      </div>
                      <em className={'diff ' + tone(part.priceDiff)}>{signed(part.priceDiff)}</em>
                      {reason && (
                        <div className="why">
                          <span>{reason.claim}</span>
                          {reason.evidence.length > 0 && <small>근거: {reason.evidence.join(' / ')}</small>}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : <p className="pl-note">부품 구성도 같아요.</p>}
          </div>

          {data.unchanged.length > 0 && (
            <div>
              <div className="pl-group-title">그대로인 부품</div>
              <div className="pl-chips">{data.unchanged.map(label => <span className="pl-chip" key={label}>{label}</span>)}</div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
