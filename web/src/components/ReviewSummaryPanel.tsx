import { useState } from 'react'
import { ApiError, api, type ReviewSummary } from '../api'

const stars = (value: number) => value.toFixed(2).replace(/0$/, '')

// 부품 하나의 리뷰 요약(제품 키로 서버에서 읽는다). 펼칠 때 한 번만 부른다.
// 실제로 모은 값(리뷰 수·평점·제외한 리뷰·관측 사실)만 보여 준다. 서버의 합성 데모 블록은 "실사용자 노출 금지" 값이라 읽지 않는다.
export default function ReviewSummaryPanel({ productKey }: { productKey: string }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<{ status: 'idle' | 'loading' | 'ready' | 'missing' | 'error'; data?: ReviewSummary }>({ status: 'idle' })

  function toggle() {
    const next = !open
    setOpen(next)
    if (!next || state.status === 'loading' || state.status === 'ready' || state.status === 'missing') return
    setState({ status: 'loading' })
    api.reviews.summary(productKey)
      .then(data => setState({ status: 'ready', data }))
      .catch(caught => setState({ status: caught instanceof ApiError && caught.code === 'not_found' ? 'missing' : 'error' }))
  }

  const data = state.data
  const hasNumbers = data && (data.totalCount > 0 || (data.ratingRaw !== null && data.ratingCount !== null) || data.ratingRefined !== null)
  return (
    <div className="pl-revsum">
      <button type="button" className="pl-revsum-toggle" aria-expanded={open} onClick={toggle}>리뷰 요약 {open ? '접기 ▲' : '보기 ▼'}</button>
      {open && (
        <div className="pl-revsum-body" role="status">
          {state.status === 'loading' && <span className="pl-note">리뷰 요약을 불러오는 중이에요…</span>}
          {state.status === 'missing' && <span className="pl-note">이 제품의 리뷰 요약은 아직 없어요.</span>}
          {state.status === 'error' && <span className="pl-note">리뷰 요약을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.</span>}
          {state.status === 'ready' && data && (
            <>
              {hasNumbers ? (
                <div className="pl-revsum-nums">
                  {data.totalCount > 0 && <span><small>수집한 리뷰</small><b className="pl-mono">{data.totalCount.toLocaleString('ko-KR')}건</b></span>}
                  {data.ratingRaw !== null && data.ratingCount !== null && <span><small>평균 별점</small><b className="pl-mono">★ {stars(data.ratingRaw)}{data.ratingCount !== data.totalCount ? ` · 별점 ${data.ratingCount.toLocaleString('ko-KR')}건` : ''}</b></span>}
                  {data.ratingRefined !== null && <span><small>검수 후 평점</small><b className="pl-mono">★ {stars(data.ratingRefined)}</b></span>}
                  {data.excludedCount !== null && <span><small>검수에서 제외</small><b className="pl-mono">{data.excludedCount.toLocaleString('ko-KR')}건{data.excludedRatio !== null ? ` · ${Math.round(data.excludedRatio * 100)}%` : ''}</b></span>}
                </div>
              ) : <span className="pl-note">서버가 이 제품의 실제 리뷰 분석을 아직 갖고 있지 않아요.</span>}
              {data.aspectFacts.length > 0 && (
                <ul className="pl-revsum-facts">{data.aspectFacts.map(text => <li key={text}>{text}</li>)}</ul>
              )}
              {data.riskEvidence.length > 0 && (
                <ul className="pl-revsum-facts">{data.riskEvidence.map(text => <li key={text}>{text}</li>)}</ul>
              )}
              {data.dataNotice && <small className="pl-revsum-notice">{data.dataNotice}</small>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
