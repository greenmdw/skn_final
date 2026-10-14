import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage, type PriceWatch } from '../api'
import { fullDate, wonFmt } from '../utils/format'

const STATUS_TEXT: Record<PriceWatch['status'], string> = { waiting: '확인 대기', tracking: '추적 중', reached: '목표가 도달' }

// 확정한 견적(가장 최근 견적서)의 목표가 알림. 서버가 지금 카탈로그 가격으로 견적 총액을 다시 계산해 목표 금액과 견주고,
// 상태(확인 대기·추적 중·목표가 도달)와 마지막으로 확인한 총액·시각을 알려 준다. 확정 때 적은 "목표 금액"(기록용)과 따로 켜고 끈다.
export default function PriceWatchPanel({ listId, confirmedTarget }: { listId: string; confirmedTarget: number }) {
  const [watch, setWatch] = useState<PriceWatch | null>(null)
  const [loadError, setLoadError] = useState('')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let alive = true
    setWatch(null); setLoadError(''); setError(''); setSaved('')
    api.setups.priceWatch(listId)
      .then(found => {
        if (!alive) return
        setWatch(found)
        setAmount(String(found.targetAmount ?? confirmedTarget))
      })
      .catch(caught => { if (alive) setLoadError(errorMessage(caught, '목표가 알림 상태를 불러오지 못했어요.')) })
    return () => { alive = false }
  }, [listId, confirmedTarget, reload])

  async function apply(event: FormEvent | null, enabled: boolean) {
    event?.preventDefault()
    setError(''); setSaved('')
    let targetAmount: number | undefined
    if (enabled) {
      const won = Number(amount.replace(/[^0-9]/g, ''))
      if (!Number.isSafeInteger(won) || won <= 0) { setError('목표 금액을 원 단위 숫자로 입력해 주세요. 예: 1500000'); return }
      targetAmount = won
    }
    setBusy(true)
    try {
      const next = await api.setups.setPriceWatch(listId, { enabled, targetAmount })
      setWatch(next)
      if (next.targetAmount != null) setAmount(String(next.targetAmount))
      setSaved(enabled ? '목표가 알림을 켰어요.' : '목표가 알림을 껐어요.')
    } catch (caught) {
      setError(errorMessage(caught, '목표가 알림을 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.'))
    } finally { setBusy(false) }
  }

  const enabled = watch?.enabled ?? false
  const target = watch?.targetAmount ?? null
  const gap = watch && watch.latestTotal != null && target != null ? watch.latestTotal - target : null
  return (
    <section className="pl-card pl-noprint pl-pricewatch" aria-label="목표가 알림">
      <div className="pl-card-head">목표가 알림</div>
      <div className="pl-pricewatch-body">
        <p className="pl-note">
          이 견적의 총액을 지금 카탈로그 가격으로 다시 계산해 목표 금액과 견줘요. 켜면 90일 동안 추적하고, 목표가에 닿으면 이 화면에 표시돼요.
        </p>
        {loadError ? (
          <div className="pl-alert bad" role="alert">{loadError} <button type="button" className="pl-link-btn" onClick={() => setReload(value => value + 1)}>다시 불러오기</button></div>
        ) : !watch ? (
          <div className="pl-note" role="status">불러오는 중이에요…</div>
        ) : (
          <>
            <div className={'pl-pricewatch-state ' + (enabled ? watch.status : 'off')} role="status">
              <b>{enabled ? STATUS_TEXT[watch.status] : '꺼짐'}</b>
              {enabled && target != null && <span>목표 {wonFmt(target)}</span>}
              {enabled && watch.latestTotal != null && <span>지금 {wonFmt(watch.latestTotal)}{gap != null && gap > 0 ? ` · 목표까지 ${wonFmt(gap)} 남음` : gap != null ? ' · 목표가 이하예요' : ''}</span>}
              {enabled && watch.latestTotal == null && <span>아직 가격을 확인하지 못했어요</span>}
              {enabled && watch.observedAt && <small>{fullDate(watch.observedAt)} 확인</small>}
            </div>
            <form className="pl-pricewatch-form" onSubmit={event => void apply(event, true)} noValidate>
              <label>목표 금액(원)
                <input inputMode="numeric" value={amount} disabled={busy} onChange={event => { setAmount(event.target.value); setError(''); setSaved('') }} placeholder="예: 1500000" />
              </label>
              <button type="submit" className="pl-btn" disabled={busy}>{busy ? '저장하는 중…' : enabled ? '목표 금액 바꾸기' : '알림 켜기'}</button>
              {enabled && <button type="button" className="pl-btn ghost" disabled={busy} onClick={() => void apply(null, false)}>알림 끄기</button>}
            </form>
            {error && <div className="pl-alert bad" role="alert">{error}</div>}
            {saved && !error && <div className="pl-note" role="status">{saved}</div>}
          </>
        )}
      </div>
    </section>
  )
}
