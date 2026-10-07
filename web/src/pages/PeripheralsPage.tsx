import { useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import { api, errorMessage, type PeripheralItem, type PeripheralKind, type PeripheralRecommendRequest, type PeripheralsResult } from '../api'
import { usePlan } from '../state/PlanContext'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import { CHECK_STATE_LABEL, PERIPHERAL_KINDS as KINDS, aspectLabel, parsePeripheralCondition, reviewEvidence, type ParsedPeripheralConditions } from '../utils/peripherals'
import '../styles/peripherals.css'

type ChatMessage = { id: number; role: 'user' | 'assistant'; text: string }

const QUICK = ['FHD 144Hz', 'QHD 165Hz', '4K', '잘 모르겠어요']

function PeripheralChat({ selected, spec, feel, showingResults, onMessage }: {
  selected: Set<PeripheralKind>
  spec: string[]
  feel: string[]
  showingResults: boolean
  onMessage: (text: string, parsed: ParsedPeripheralConditions) => void
}) {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 1, role: 'assistant', text: '필요한 품목을 고르고 원하는 느낌을 말해 주세요. 예를 들면 “조용하고 쫀득한 키보드”, “손이 작아서 가벼운 마우스”처럼요.' },
  ])
  const nextId = useRef(2)

  function send(text: string) {
    const clean = text.trim()
    if (!clean) return
    const parsed = parsePeripheralCondition(clean)
    const reflected = [...parsed.spec, ...parsed.feel]
    setMessages(previous => [...previous,
      { id: nextId.current++, role: 'user', text: clean },
      { id: nextId.current++, role: 'assistant', text: reflected.length ? `말씀한 조건을 반영했어요: ${reflected.join(' · ')}` : '말씀하신 내용을 추가 조건으로 기록했어요.' },
    ])
    onMessage(clean, parsed)
    setDraft('')
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  const selectedLabels = KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.label)
  return (
    <aside className="pl-chat pf-chat" aria-label="주변기기 조건 대화">
      <div className="pl-chat-head"><span className="pl-dot" />주변기기 조건 대화</div>
      <div className="pl-chat-log">
        {messages.map(message => <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}>{message.text}</div>)}
        {selectedLabels.length > 0 && <div className="pf-reflected">✓ 선택 품목: {selectedLabels.join(' · ')}{spec.length || feel.length ? ` · 조건 ${spec.length + feel.length}개` : ''}</div>}
        {showingResults && <div className="pl-msg-bot">품목마다 하나씩 골랐어요. 스펙 조건과 리뷰 근거를 함께 확인해 주세요.</div>}
      </div>
      <div className="pl-chat-foot">
        <div className="pl-choices pf-quick">
          {QUICK.map(text => <button type="button" className="pl-choice" key={text} onClick={() => send(text)}>{text}</button>)}
        </div>
        <form className="pl-input" onSubmit={submit}>
          <input value={draft} onChange={event => setDraft(event.target.value)} placeholder="원하는 조건을 자유롭게 적어 주세요" aria-label="주변기기 조건 입력" />
          <button type="submit" className="pl-send" disabled={!draft.trim()}>보내기</button>
        </form>
      </div>
    </aside>
  )
}

export default function PeripheralsPage() {
  const { state, setPeripherals } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<Set<PeripheralKind>>(() => new Set(KINDS.map(kind => kind.id)))
  const [specConditions, setSpecConditions] = useState<string[]>([])
  const [feelConditions, setFeelConditions] = useState<string[]>([])
  const [extraConditions, setExtraConditions] = useState<string[]>([])
  // 서버 추천 요청에 실리는 값. 대화에서 뽑힌 마지막 값이 이긴다.
  const [params, setParams] = useState<Pick<PeripheralRecommendRequest, 'budgetMax' | 'resolution' | 'noiseSensitive'>>({})
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PeripheralsResult | null>(null)
  const sessionId = useRef<string | null>(null)

  const showResults = result !== null
  const selectedLabels = useMemo(() => KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.label), [selected])
  const total = useMemo(() => (result?.items ?? []).reduce((sum, item) => sum + item.price, 0), [result])
  const budget = params.budgetMax ?? null
  const plan = state.currentPlan
  const hasUnreflectedFeel = feelConditions.some(condition => condition !== '조용한 사용감')

  function toggle(kind: PeripheralKind) {
    setSelected(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind); else next.add(kind)
      return next
    })
    setNotice('')
    setResult(null)
  }

  function addConditions(text: string, parsed: ParsedPeripheralConditions) {
    setSpecConditions(previous => [...new Set([...previous, ...parsed.spec])])
    setFeelConditions(previous => [...new Set([...previous, ...parsed.feel])])
    if (!parsed.spec.length && !parsed.feel.length) setExtraConditions(previous => [...new Set([...previous, text])])
    setParams(previous => ({
      budgetMax: parsed.budgetMax ?? previous.budgetMax,
      resolution: parsed.resolution ?? previous.resolution,
      noiseSensitive: parsed.noiseSensitive ?? previous.noiseSensitive,
    }))
    setNotice('')
    setResult(null)
  }

  async function requestRecommendation() {
    if (!selected.size) {
      setNotice('추천받을 주변기기를 한 개 이상 선택해주세요.')
      return
    }
    setNotice(''); setError(''); setLoading(true)
    try {
      const next = await api.peripherals.recommend({
        kinds: KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.id),
        budgetMax: params.budgetMax,
        resolution: params.resolution,
        noiseSensitive: params.noiseSensitive,
        pcListId: plan?.id,
      }, sessionId.current)
      sessionId.current = next.sessionId
      setResult(next)
    } catch (caught) {
      setError(errorMessage(caught, '주변기기를 추천받지 못했습니다. 잠시 후 다시 시도해주세요.'))
    } finally { setLoading(false) }
  }

  function toCart() {
    if (!result) return
    if (!plan) {
      setNotice('통합 장바구니에는 본체 견적이 필요해요. 먼저 본체 추천을 받은 뒤 다시 담아 주세요.')
      return
    }
    const items = result.items.filter(item => item.variantId).map(item => ({
      kind: item.kind, name: item.name, brand: item.brand, price: item.price, qty: 1,
      variantId: item.variantId, imageUrl: item.imageUrl, productUrl: item.productUrl,
    }))
    if (!items.length) { setNotice('장바구니에 담을 수 있는 품목이 없어요.'); return }
    setPeripherals(items)
    showToast(`주변기기 ${items.length}개를 통합 장바구니에 담았어요.`)
    navigate('/cart')
  }

  function recommendationCard(item: PeripheralItem) {
    const evidence = reviewEvidence(item.reviewAspects)
    const specLine = item.requirement.length ? item.requirement.map(row => `${row.label} ${row.value}`).join(' · ') : item.brand
    return <article className="pf-result-card" key={item.kind}>
      <div className="pf-product-head">
        <div className="pf-product-image" aria-hidden="true">{item.imageUrl ? <img src={item.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={event => { event.currentTarget.style.display = 'none' }} /> : <span>사진</span>}</div>
        <div className="pf-product-title">
          <span>{item.kindLabel}</span>
          <h2>{item.name}</h2>
          <p>{specLine}</p>
        </div>
        <strong className="pf-product-price pl-mono">{wonFmt(item.price)}</strong>
      </div>
      {item.priceNote && <p className="pf-price-note">ⓘ {item.priceNote}</p>}

      {item.reason.text && <section className="pf-evidence">
        <h3>추천 근거</h3>
        <p>{item.reason.text}</p>
      </section>}

      <section className="pf-evidence">
        <h3>리뷰 근거</h3>
        {evidence.length === 0 && <div className="pf-weak-note">아직 모인 리뷰 근거가 없어요. 스펙 근거만 참고해 주세요.</div>}
        {evidence.map(review => {
          const ratio = review.total ? Math.round(review.positive / review.total * 100) : 0
          const weak = review.total < 3
          return <div className={'pf-review' + (weak ? ' weak' : '')} key={review.aspectCode}>
            <p><b>{aspectLabel(review.aspectCode)}</b> · 후기 언급 {review.total}건 중 긍정 <b>{review.positive}건</b> · 부정 {review.negative}건{review.mixed > 0 ? ` · 엇갈림 ${review.mixed}건` : ''}</p>
            <div className="pf-review-track"><i style={{ width: `${ratio}%` }} /></div>
            {review.quote && <blockquote>“{review.quote}”</blockquote>}
            {weak && <div className="pf-weak-note">리뷰가 적어 판단 근거가 약해요. 비율보다 건수를 먼저 봐 주세요.</div>}
          </div>
        })}
        {item.reviewNote && <p className="pf-review-note">{item.reviewNote}</p>}
      </section>

      {item.checks.length > 0 && <section className="pf-device-checks">
        <h3>스펙·본체 검사</h3>
        {item.checks.map(check => <div key={check.axis}><span className={check.state}>{CHECK_STATE_LABEL[check.state]}</span><b>{check.label}</b><p>{check.detail}</p></div>)}
      </section>}
      {item.guide.status === 'ready' && item.guide.text && <p className="pf-buying-note"><b>구매 전 확인</b> · {item.guide.text}</p>}

      {item.alternatives.length > 0 && <details className="pf-alternatives">
        <summary>다른 후보 {item.alternatives.length}개 보기</summary>
        <ul>{item.alternatives.map(alternative => <li key={alternative.name}><span>{alternative.name}</span><b className="pl-mono">{wonFmt(alternative.price)}</b><em className={alternative.diff > 0 ? 'up' : 'down'}>{alternative.diff > 0 ? '+' : ''}{wonFmt(alternative.diff)}</em></li>)}</ul>
      </details>}
    </article>
  }

  return (
    <PlannerShell sidebar={<PeripheralChat selected={selected} spec={specConditions} feel={feelConditions} showingResults={showResults} onMessage={addConditions} />}>
      <div className={'pf-page' + (showResults ? ' results' : '')}>
        {showResults ? <>
          <div className="pf-results-heading">
            <div><span className="pl-eyebrow pl-mono">주변기기 견적 · 추천 결과</span><h1>원하는 느낌에 맞춘 주변기기</h1></div>
            <div className="pf-total">
              <strong className="pl-mono">{wonFmt(total)}</strong>
              <span>{budget != null ? `주변기기 예산 ${wonFmt(budget)} · ${total <= budget ? `잔액 ${wonFmt(budget - total)}` : `${wonFmt(total - budget)} 초과`}` : '예산을 알려 주면 잔액도 보여 드려요'}</span>
            </div>
          </div>
          {result.status === 'skipped' && <div className="pl-alert warn" role="status">서버가 이번 요청은 추천하지 않았어요. 조건을 바꿔 다시 시도해 주세요.</div>}
          {result.empty.length > 0 && <div className="pl-alert warn" role="status">{result.empty.map(row => `${KINDS.find(kind => kind.id === row.kind)?.label ?? row.kind}: ${row.reason}`).join(' · ')}</div>}
          <div className="pf-results-grid">{result.items.map(recommendationCard)}</div>
          <div className="pf-results-actions">
            <button type="button" className="pf-secondary" onClick={() => setResult(null)}>조건 다시 보기</button>
            <button type="button" className="pl-btn" onClick={toCart} disabled={result.items.length === 0}>통합 장바구니로</button>
          </div>
          {!plan && <div className="pl-alert warn" role="status">본체 견적이 없어서 통합 장바구니에 담을 수 없어요. <Link to="/start" style={{ color: 'inherit', fontWeight: 700 }}>본체 추천 받으러 가기 →</Link></div>}
          {notice && <div className="pl-alert warn" role="status">{notice}</div>}
        </> : <>
        <div className="pf-heading">
          <h1>필요한 품목과 원하는 느낌</h1>
          <p>필요한 주변기기를 고르고, 왼쪽 대화에서 예산과 사용감을 알려주세요.</p>
        </div>

        <div className="pf-kind-grid" aria-label="주변기기 품목 선택">
          {KINDS.map(kind => {
            const on = selected.has(kind.id)
            return <button type="button" key={kind.id} className={'pf-kind' + (on ? ' on' : '')} onClick={() => toggle(kind.id)} aria-pressed={on}>
              <span><b>{kind.label}</b><i aria-hidden="true">{on ? '✓' : '+'}</i></span>
              <small>{kind.description}</small>
            </button>
          })}
        </div>

        <div className="pf-condition-grid">
          <section className="pf-condition-card">
            <div className="pf-card-title"><b>스펙 조건</b><span>예산·해상도·주사율처럼 수치로 확인할 조건</span></div>
            <div className="pf-chips">
              {specConditions.map(condition => <span key={condition}>{condition}</span>)}
              {specConditions.length === 0 && <p>아직 입력한 스펙 조건이 없어요.</p>}
            </div>
          </section>
          <section className="pf-condition-card">
            <div className="pf-card-title"><b>체감 조건</b><span>사용감과 선호는 리뷰 근거로 확인할 조건</span></div>
            <div className="pf-chips">
              {feelConditions.map(condition => <span key={condition}>{condition}</span>)}
              {feelConditions.length === 0 && <p>아직 입력한 체감 조건이 없어요.</p>}
            </div>
            {hasUnreflectedFeel && <p className="pf-feel-note">지금은 ‘조용한 사용감’만 추천에 반영돼요. 나머지 체감 조건은 기록만 해 두고, 추천 결과의 리뷰 근거에서 직접 확인해 주세요.</p>}
          </section>
        </div>

        <section className="pf-extra">
          <b>추가 조건</b><span>대화에서 말한 나머지 조건을 그대로 쌓아요.</span>
          <div className="pf-chips">{extraConditions.map(condition => <span key={condition}>{condition}</span>)}{extraConditions.length === 0 && <p>아직 쌓인 추가 조건이 없어요.</p>}</div>
        </section>

        <div className="pf-action">
          <div><b>{selectedLabels.length ? `${selectedLabels.join(' · ')} 선택됨` : '품목을 선택해주세요'}</b><span>{plan ? '지금 작성한 본체 견적의 해상도로 모니터를 함께 검사해요.' : '본체 견적이 없어도 추천받을 수 있어요.'}</span></div>
          <button type="button" className="pl-btn" onClick={() => void requestRecommendation()} disabled={loading}>{loading ? '추천 찾는 중…' : '추천 받기'}</button>
        </div>
        {loading && <div className="pl-note" role="status">주변기기 후보를 고르고 있어요. 품목이 많으면 조금 걸릴 수 있어요.</div>}
        {error && <div className="pl-alert bad" role="alert">{error}</div>}
        {notice && <div className="pl-alert warn" role="status">{notice}</div>}
        </>}
      </div>
    </PlannerShell>
  )
}
