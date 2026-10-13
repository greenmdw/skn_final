import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import { api, errorMessage, type PeripheralItem, type PeripheralKind, type PeripheralRecommendRequest, type PeripheralsResult } from '../api'
import { usePlan } from '../state/PlanContext'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import { COMMUNITY_REVIEW_BOARD, findCommunitySource, type CommunitySource } from '../utils/communitySource'
import { Linkified } from '../utils/linkify'
import { PERIPHERAL_KINDS as KINDS, aspectLabel, parsePeripheralCondition, reviewEvidence, type ParsedPeripheralConditions, type ReviewEvidence } from '../utils/peripherals'
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
        {messages.map(message => <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}><Linkified text={message.text} /></div>)}
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

// 평가 기준별 후기 집계 줄: 점(긍정 초록·부정 빨강·애매함 회색) + "후기 N건 중 긍정 M건". 관측이 없으면 안내만 보인다.
function ReviewRows({ evidence, withQuotes = false }: { evidence: ReviewEvidence[]; withQuotes?: boolean }) {
  if (evidence.length === 0) return <div className="pf-weak-note">이 제품의 사용기는 아직 없습니다. 스펙과 가격 기준으로 추천했습니다.</div>
  return <>{evidence.map(review => <div className="pf-evidence-item" key={review.aspectCode}>
    <div className="pf-evidence-row">
      <b>{aspectLabel(review.aspectCode)}</b>
      <span className="pf-dots" aria-label={`긍정 ${review.positive}건, 부정 ${review.negative}건`}>{Array.from({ length: Math.min(review.total, 8) }, (_, index) => <i className={index < review.positive ? 'positive' : index < review.positive + review.negative ? 'negative' : ''} key={index} />)}</span>
      <span>후기 {review.total}건 중 긍정 {review.positive}건{review.total < 3 && <em>근거 적음</em>}</span>
    </div>
    {withQuotes && review.quote && <p className="pf-evidence-quote">{review.quote}</p>}
  </div>)}</>
}

// 추천 제품의 대표 후기 카드. 커뮤니티에 이 제품의 사용기 글이 있으면 그 글(사진·내용)을 보여 주고 "원문 보기"로 글을 연다.
// 없으면 서버가 준 후기 문장(quote)을 보여 주고, 링크는 사용기 게시판으로 간다. 글도 후기 문장도 없으면 "아직 없어요" 빈 카드를 보여 준다.
function CommunityCitation({ productName, kindLabel, quote }: { productName: string; kindLabel: string; quote: string | null }) {
  const [source, setSource] = useState<CommunitySource | null>(null)
  const [searched, setSearched] = useState(false)
  useEffect(() => {
    let alive = true
    setSource(null)
    setSearched(false)
    void findCommunitySource(productName, kindLabel).then(found => { if (alive) { setSource(found); setSearched(true) } })
    return () => { alive = false }
  }, [productName, kindLabel])
  const text = source?.excerpt || quote
  if (!text) {
    if (!searched) return null   // 찾는 중에는 빈 카드가 깜빡이지 않게 비워 둔다
    return <div className="pf-citation empty">
      <span className="pf-citation-thumb" aria-hidden="true">글의 사진</span>
      <p>이 제품의 사용기가 아직 없어요. 첫 사용기를 남겨 보세요.</p>
      <Link to={COMMUNITY_REVIEW_BOARD}>사용기 게시판 보기 →</Link>
    </div>
  }
  return <div className="pf-citation">
    <span className="pf-citation-thumb" aria-hidden="true">
      {source?.coverUrl ? <img src={source.coverUrl} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} /> : '글의 사진'}
    </span>
    <p>“{text}”</p>
    <Link to={source?.path ?? COMMUNITY_REVIEW_BOARD}>원문 보기 →</Link>
  </div>
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
  const [pickedKinds, setPickedKinds] = useState<Set<PeripheralKind>>(() => new Set())
  const sessionId = useRef<string | null>(null)

  const showResults = result !== null
  const selectedLabels = useMemo(() => KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.label), [selected])
  const pickedItems = useMemo(() => (result?.items ?? []).filter(item => pickedKinds.has(item.kind)), [pickedKinds, result])
  const total = useMemo(() => pickedItems.reduce((sum, item) => sum + item.price, 0), [pickedItems])
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
      setPickedKinds(new Set(next.items.map(item => item.kind)))
    } catch (caught) {
      setError(errorMessage(caught, '주변기기를 추천받지 못했습니다. 잠시 후 다시 시도해주세요.'))
    } finally { setLoading(false) }
  }

  function toCart() {
    if (!result) return
    // 본체 견적이 없어도 담을 수 있다 — 이 추천을 받은 목록(세션)으로 주변기기만 확정한다.
    if (!plan && !result.sessionId) {
      setNotice('장바구니에 담을 수 없어요. 주변기기 추천을 다시 받아 주세요.')
      return
    }
    const items = result.items.filter(item => pickedKinds.has(item.kind) && item.variantId).map(item => ({
      kind: item.kind, name: item.name, brand: item.brand, price: item.price, qty: 1,
      variantId: item.variantId, imageUrl: item.imageUrl, productUrl: item.productUrl,
    }))
    if (!items.length) { setNotice('장바구니에 담을 수 있는 품목이 없어요.'); return }
    setPeripherals(items, plan ? undefined : result.sessionId)
    showToast(`주변기기 ${items.length}개를 ${plan ? '통합 ' : ''}장바구니에 담았어요.`)
    navigate('/cart')
  }

  function togglePicked(kind: PeripheralKind) {
    setPickedKinds(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind); else next.add(kind)
      return next
    })
  }

  function recommendationCard(item: PeripheralItem) {
    const evidence = reviewEvidence(item.reviewAspects)
    const picked = pickedKinds.has(item.kind)
    const cautions = item.checks.filter(check => check.state !== 'ok')
    return <section className="pf-kind-result" key={item.kind}>
      <div className="pf-kind-heading"><h2>{item.kindLabel}</h2><span>조건과 리뷰 근거에 가장 잘 맞는 제품</span></div>
      <p className="pf-kind-pref">{[...specConditions, ...feelConditions].join(' · ') || '선택한 품목과 현재 조건을 기준으로 추천'}</p>
      <article className="pf-hero-card">
        <div className="pf-hero-side">
          <span className="pf-best">가장 잘 맞아요</span>
          <div className="pf-hero-image">{item.imageUrl ? <img src={item.imageUrl} alt={item.name} loading="lazy" referrerPolicy="no-referrer" onError={event => { event.currentTarget.style.display = 'none' }} /> : <span>제품 이미지</span>}</div>
          <strong className="pf-hero-price pl-mono">{wonFmt(item.price)}</strong>
          <button type="button" className={'pf-pick' + (picked ? ' on' : '')} onClick={() => togglePicked(item.kind)}>{picked ? '담았습니다' : '견적에 담기'}</button>
        </div>
        <div className="pf-hero-body">
          <h3>{item.name}</h3>
          <div className="pf-fit-tags">{item.requirement.map(row => <span key={row.key}>✓ {row.value}</span>)}{item.checks.filter(check => check.state === 'fail').map(check => <span className="no" key={check.axis}>✕ {check.label}</span>)}</div>
          {item.reason.text && <p className="pf-main-reason">{item.reason.text}</p>}
          <div className="pf-review-evidence">
            <ReviewRows evidence={evidence} />
          </div>
          <CommunityCitation productName={item.name} kindLabel={item.kindLabel} quote={evidence.find(review => review.quote)?.quote ?? null} />
          {(cautions.length > 0 || item.guide.text) && <div className="pf-caution"><b>구매 전 확인</b><span>{[...cautions.map(check => check.detail), item.guide.text].filter(Boolean).join(' · ')}</span></div>}
          <div className="pf-card-foot">{item.reviewNote && <span>{item.reviewNote}</span>}{item.priceNote && <span>{item.priceNote}</span>}{item.productUrl && <a href={item.productUrl} target="_blank" rel="noreferrer">상품 보기 →</a>}</div>
        </div>
      </article>
      {item.alternatives.length > 0 && <details className="pf-more">
        <summary><span>다른 선택지 {item.alternatives.length}개 · {item.alternatives.map(alternative => alternative.name).join(' · ')}</span></summary>
        <div className="pf-alt-grid">{item.alternatives.map((alternative, index) => <article className="pf-alt-card" key={alternative.name}>
          <header className="pf-alt-head"><i>{index + 2}</i><h3>{alternative.name}</h3><strong className="pl-mono">{wonFmt(alternative.price)}</strong></header>
          <p className="pf-alt-diff">1위보다 <b>{wonFmt(Math.abs(alternative.diff))} {alternative.diff < 0 ? '저렴' : alternative.diff > 0 ? '비쌈' : '같은 가격'}</b></p>
          <div className="pf-review-evidence pf-alt-evidence"><ReviewRows evidence={reviewEvidence(alternative.reviewAspects, 3)} withQuotes /></div>
          {alternative.reviewNote && <small className="pf-alt-note">{alternative.reviewNote}</small>}
        </article>)}</div>
      </details>}
    </section>
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
          <section className="pf-understood">
            <b>이해한 내용</b>
            <div className="pf-understood-chips">
              {selectedLabels.map(label => <span key={label}><i>종류</i>{label}</span>)}
              {specConditions.map(condition => <span key={condition}><i>스펙</i>{condition}</span>)}
              {feelConditions.map(condition => <span key={condition}><i>사용감</i>{condition}</span>)}
              {plan && <span className="pc"><i>PC 견적</i>본체 조건 연결됨</span>}
            </div>
            {extraConditions.length > 0 && <p>아직 추천 순서에 직접 반영하지 못한 조건: {extraConditions.join(' · ')}</p>}
          </section>
          {result.status === 'skipped' && <div className="pl-alert warn" role="status">서버가 이번 요청은 추천하지 않았어요. 조건을 바꿔 다시 시도해 주세요.</div>}
          {result.empty.length > 0 && <div className="pl-alert warn" role="status">{result.empty.map(row => `${KINDS.find(kind => kind.id === row.kind)?.label ?? row.kind}: ${row.reason}`).join(' · ')}</div>}
          <div className="pf-results-list">{result.items.map(recommendationCard)}</div>
          <button type="button" className="pf-secondary pf-edit-conditions" onClick={() => setResult(null)}>조건 다시 보기</button>
          {!plan && <div className="pl-alert warn" role="status">본체 견적 없이 주변기기만 담아 확정할 수 있어요. 본체와 함께 확정하려면 <Link to="/start" style={{ color: 'inherit', fontWeight: 700 }}>본체 추천 받으러 가기 →</Link></div>}
          {notice && <div className="pl-alert warn" role="status">{notice}</div>}
          <div className="pf-pick-bar">
            <div>{pickedItems.length ? pickedItems.map(item => <span key={item.kind}><i>{item.kindLabel}</i>{item.name}</span>) : <span>담은 제품이 없습니다 · 종류마다 하나씩 담을 수 있어요</span>}</div>
            <strong>{pickedItems.length}개 · {wonFmt(total)}</strong>
            <button type="button" onClick={toCart} disabled={pickedItems.length === 0}>{plan ? '통합 장바구니로' : '견적 확정하기'}</button>
          </div>
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
