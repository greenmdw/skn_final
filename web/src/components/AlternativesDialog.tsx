import { useEffect, useMemo, useState } from 'react'
import { errorMessage, type AlternativeOption } from '../api'
import { usePlan } from '../state/PlanContext'
import type { PlanItem } from '../state/types'
import { wonFmt } from '../utils/format'
import ProductThumb from './ProductThumb'

const PAGE = 6
const sign = (n: number) => (n > 0 ? '+' : n < 0 ? '-' : '') + wonFmt(Math.abs(n))

// 한 부품 자리에 넣을 수 있는 대안을 서버에서 받아 나란히 보여 주고, 고르면 서버가 교체와 호환 검사를 다시 한다.
export default function AlternativesDialog({ item, onClose }: { item: PlanItem; onClose: () => void }) {
  const { loadAlternatives, swapItem } = usePlan()
  const [options, setOptions] = useState<AlternativeOption[] | null>(null)
  const [error, setError] = useState('')
  const [swapping, setSwapping] = useState<string | null>(null)
  const [shown, setShown] = useState(PAGE)
  // 서버는 그 자리의 모든 후보를 주므로, 지금 제품과 가격이 가까운 순으로 보여 준다(지금 고른 것이 있으면 맨 앞).
  const sorted = useMemo(
    () => (options ? [...options].sort((a, b) => Number(b.current) - Number(a.current) || Math.abs(a.priceDelta) - Math.abs(b.priceDelta)) : null),
    [options],
  )

  useEffect(() => {
    let alive = true
    loadAlternatives(item.id)
      .then(list => { if (alive) setOptions(list) })
      .catch(err => { if (alive) setError(errorMessage(err, '대안 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.')) })
    return () => { alive = false }
  }, [item.id, loadAlternatives])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function choose(option: AlternativeOption) {
    setSwapping(option.candidateId)
    const ok = await swapItem(item.id, option.candidateId)
    if (ok) onClose()
    else setSwapping(null)
  }

  return (
    <div className="pl-modal-back" onClick={onClose}>
      <div className="pl-modal" role="dialog" aria-modal="true" aria-label={`${item.type} 대안 비교`} onClick={event => event.stopPropagation()}>
        <div className="pl-modal-head">
          <div>
            <div style={{ fontSize: 17, fontWeight: 700 }}>{item.type} 대안 비교</div>
            <div className="pl-note" style={{ marginTop: 4 }}>고르면 가격과 예산, 호환 검사를 서버가 다시 계산해요.</div>
          </div>
          <button type="button" className="pl-pill" onClick={onClose}>닫기</button>
        </div>
        <div className="pl-modal-body">
          {error && <div className="pl-alert bad" role="alert">{error}</div>}
          {!error && options === null && <div className="pl-note">대안을 불러오는 중이에요…</div>}
          {options && options.length === 0 && <div className="pl-note">이 자리에 바꿔 넣을 수 있는 다른 제품이 없어요.</div>}
          <div className="pl-alt-grid">
            {sorted?.slice(0, shown).map(option => (
              <div className={'pl-alt' + (option.current ? ' current' : '')} key={option.candidateId}>
                <div className="pl-alt-top">
                  <ProductThumb imageUrl={option.imageUrl} partKey={item.key} name={option.name} />
                  <div style={{ minWidth: 0 }}>
                    <div className="pl-alt-label">{option.current ? '지금 고른 제품' : option.label}</div>
                    <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{option.name}</div>
                  </div>
                </div>
                {option.specSummary && <div className="pl-note">{option.specSummary}</div>}
                <div className="pl-alt-price">
                  <b className="pl-mono">{wonFmt(option.price)}</b>
                  {!option.current && option.priceDelta !== 0 && (
                    <span className={'pl-delta ' + (option.priceDelta > 0 ? 'up' : 'down')}>{sign(option.priceDelta)}</span>
                  )}
                </div>
                <div className="pl-note">
                  {option.rating !== '-' || option.reviews !== '없음' ? `★ ${option.rating} · 리뷰 ${option.reviews}` : '리뷰 관측 없음'}
                </div>
                {option.current
                  ? <button type="button" className="pl-btn ghost" style={{ padding: '9px 14px', fontSize: 13 }} disabled>선택됨</button>
                  : <button type="button" className="pl-btn" style={{ padding: '9px 14px', fontSize: 13 }} disabled={swapping !== null} onClick={() => void choose(option)}>
                    {swapping === option.candidateId ? '바꾸는 중…' : '이걸로 바꾸기'}
                  </button>}
              </div>
            ))}
          </div>
          {sorted && sorted.length > shown && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button type="button" className="pl-btn ghost" style={{ padding: '9px 14px', fontSize: 13 }} onClick={() => setShown(count => count + PAGE)}>
                더 보기 ({sorted.length - shown}개 남음)
              </button>
              <span className="pl-note">지금 제품과 가격이 가까운 순서예요.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
