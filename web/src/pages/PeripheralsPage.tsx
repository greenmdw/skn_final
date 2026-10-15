import { useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import ResizeHandle, { usePanelWidth } from '../components/ResizeHandle'
import {
  api, errorMessage, type PeripheralAdjustChip, type PeripheralInterpretResult, type PeripheralItem, type PeripheralKind, type PeripheralsResult,
} from '../api'
import { usePlan } from '../state/PlanContext'
import type { SetupPeripheral } from '../state/types'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import { Linkified } from '../utils/linkify'
import {
  EMPTY_INTERPRETATION, EMPTY_UNDERSTOOD, PERIPHERAL_KINDS as KINDS, applyAdjustChip, aspectLabel, recommendInputs, removeUnderstood, reviewEvidence,
  type ReviewEvidence, type UnderstoodRemoval, type UnderstoodState,
} from '../utils/peripherals'
import '../styles/peripherals.css'

type ChatMessage = { id: number; role: 'user' | 'assistant'; text: string }

const QUICK = ['FHD 144Hz', 'QHD 165Hz', '4K', '잘 모르겠어요']
const COMMUNITY_REVIEW_BOARD = '/community?view=board&board=review'
const PERIPHERAL_CHAT_WIDTH = { key: 'truefit.peripherals.chat.width', initial: 380, min: 280, max: 520 }
const kindLabel = (kind: PeripheralKind) => KINDS.find(entry => entry.id === kind)?.label ?? kind

function restoredResult(items: SetupPeripheral[], sessionId: string): PeripheralsResult {
  return {
    sessionId, status: 'ready', empty: [], ignoredInputs: [], adjustChips: [],
    referencePrice: items.reduce((sum, item) => sum + item.price * item.qty, 0),
    priceNote: '확정한 견적에서 불러온 구성입니다.',
    items: items.map(item => ({
      kind: item.kind, kindLabel: kindLabel(item.kind), name: item.name, brand: item.brand ?? '',
      variantId: item.variantId ?? null, productUrl: item.productUrl ?? null, imageUrl: item.imageUrl ?? null,
      price: item.price, priceNote: '확정한 견적에서 불러온 참고가입니다.', requirement: [], checks: [],
      reason: { status: 'restored', text: '저장된 견적에서 불러온 제품입니다.' },
      guide: { status: 'unavailable', text: null }, reviewAspects: [], reviewWeight: 0, reviewNote: '',
      alternatives: [], feel: null, feelNote: null,
    })),
  }
}

interface SendOutcome { reply: string; needsKind: boolean }

/** 서버가 읽은 내용을 대화 답장 한 줄로 */
function interpretReply(result: PeripheralInterpretResult): string {
  const labels: string[] = []
  for (const kind of result.interpretation.kinds) {
    const resolved = result.resolved[kind]
    if (!resolved) continue
    labels.push(...resolved.purposes.map(purpose => purpose.label), ...resolved.filters.map(item => item.label), ...resolved.preferences.map(item => item.label))
  }
  const { budget, budgetTotal, unrecognized } = result.interpretation
  if (budgetTotal) labels.push(`예산 ${wonFmt(budgetTotal)}`)
  for (const [kind, won] of Object.entries(budget) as [PeripheralKind, number][]) labels.push(`${kindLabel(kind)} 예산 ${wonFmt(won)}`)
  const parts: string[] = []
  if (labels.length) parts.push(`말씀한 조건을 반영했어요: ${[...new Set(labels)].join(' · ')}`)
  if (unrecognized.length) parts.push(`이 부분은 아직 반영하지 못했어요: ${unrecognized.join(' · ')}`)
  if (!parts.length) parts.push('아직 읽어 낸 조건이 없어요. 예: “조용한 무선 마우스 5만원 이하”처럼 말씀해 주세요.')
  if (result.truncated) parts.push('문장이 길어 앞부분만 읽었어요.')
  return parts.join('\n')
}

function PeripheralChat({ selectedLabels, conditionCount, showingResults, onSend }: {
  selectedLabels: string[]
  conditionCount: number
  showingResults: boolean
  onSend: (text: string, kinds?: PeripheralKind[]) => Promise<SendOutcome>
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const size = usePanelWidth(PERIPHERAL_CHAT_WIDTH.key, PERIPHERAL_CHAT_WIDTH.initial, PERIPHERAL_CHAT_WIDTH.min, PERIPHERAL_CHAT_WIDTH.max)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 1, role: 'assistant', text: '필요한 품목을 고르고 원하는 느낌을 말해 주세요. 예를 들면 “조용하고 쫀득한 키보드”, “손이 작아서 가벼운 마우스”처럼요.' },
  ])
  // "어떤 기기를 찾으세요?" 카드: 서버가 종류를 알아듣지 못한 문장과, 카드에서 고르는 중인 종류
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [pendingKinds, setPendingKinds] = useState<Set<PeripheralKind>>(() => new Set())
  const nextId = useRef(2)

  const say = (role: ChatMessage['role'], text: string) => setMessages(previous => [...previous, { id: nextId.current++, role, text }])

  async function deliver(text: string, kinds?: PeripheralKind[]) {
    setBusy(true)
    try {
      const outcome = await onSend(text, kinds)
      if (outcome.needsKind) {
        setPendingText(text)
        setPendingKinds(new Set())
        say('assistant', '어떤 기기를 찾으세요? 아래에서 골라 주세요.')
      } else {
        setPendingText(null)
        say('assistant', outcome.reply)
      }
    } catch (caught) {
      say('assistant', errorMessage(caught, '문장을 읽지 못했어요. 잠시 후 다시 말씀해 주세요.'))
    } finally { setBusy(false) }
  }

  function send(text: string) {
    const clean = text.trim()
    if (!clean || busy) return
    say('user', clean)
    setDraft('')
    void deliver(clean)
  }

  function chooseKinds() {
    if (!pendingText || pendingKinds.size === 0 || busy) return
    const kinds = KINDS.filter(kind => pendingKinds.has(kind.id)).map(kind => kind.id)
    say('user', kinds.map(kindLabel).join(' · '))
    void deliver(pendingText, kinds)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  return (
    <aside className="pl-chat pl-resizable pf-chat" aria-label="주변기기 조건 대화" style={{ width: size.width }}>
      <div className="pl-chat-head"><span className="pl-dot" />주변기기 조건 대화</div>
      <div className="pl-chat-log">
        {messages.map(message => <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}><Linkified text={message.text} /></div>)}
        {pendingText !== null && <div className="pf-kind-card" role="group" aria-label="어떤 기기를 찾으세요?">
          <b>어떤 기기를 찾으세요?</b>
          <div>
            {KINDS.map(kind => <button type="button" key={kind.id} className={pendingKinds.has(kind.id) ? 'on' : ''} aria-pressed={pendingKinds.has(kind.id)} disabled={busy}
              onClick={() => setPendingKinds(previous => { const next = new Set(previous); if (next.has(kind.id)) next.delete(kind.id); else next.add(kind.id); return next })}>{kind.label}</button>)}
          </div>
          <button type="button" className="pf-kind-card-go" disabled={busy || pendingKinds.size === 0} onClick={chooseKinds}>이 종류로 찾기</button>
        </div>}
        {busy && <div className="pl-typing pl-mono" aria-label="문장을 읽는 중">···</div>}
        {selectedLabels.length > 0 && <div className="pf-reflected">✓ 선택 품목: {selectedLabels.join(' · ')}{conditionCount ? ` · 조건 ${conditionCount}개` : ''}</div>}
        {showingResults && <div className="pl-msg-bot">품목마다 하나씩 골랐어요. 스펙 조건과 리뷰 근거를 함께 확인해 주세요.</div>}
      </div>
      <div className="pl-chat-foot">
        <div className="pl-choices pf-quick">
          {QUICK.map(text => <button type="button" className="pl-choice" key={text} disabled={busy} onClick={() => send(text)}>{text}</button>)}
        </div>
        <form className="pl-input" onSubmit={submit}>
          <input value={draft} onChange={event => setDraft(event.target.value)} placeholder="원하는 조건을 자유롭게 적어 주세요" aria-label="주변기기 조건 입력" />
          <button type="submit" className="pl-send" disabled={!draft.trim() || busy}>보내기</button>
        </form>
      </div>
      <ResizeHandle width={size.width} min={size.min} max={size.max} label="주변기기 대화창 너비" onChange={size.setWidth} onReset={size.reset} />
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

// 추천 제품의 체감 근거(사용기 분석). 서버가 준 문구를 그대로 보여 주고, 인용 문장은 사진(있을 때만)과 함께 커뮤니티 글로 연결한다.
// 근거가 없으면(feel 이 null) 서버가 준 한 줄(feelNote)과 "사용기가 아직 없어요" 안내만 보인다. 어느 쪽이든 사용기 게시판 링크 카드가 맨 아래에 붙는다.
function FeelBlock({ item }: { item: PeripheralItem }) {
  const { feel } = item
  if (!feel) {
    return <div className="pf-citation empty">
      <p>{item.feelNote ? `${item.feelNote} · ` : ''}이 제품의 사용기가 아직 없어요. 첫 사용기를 남겨 보세요.</p>
      <Link to={COMMUNITY_REVIEW_BOARD}>사용기 게시판 보기 →</Link>
    </div>
  }
  return <div className="pf-feel">
    <div className="pf-feel-head">
      {feel.basisText && <b>{feel.basisText}</b>}
      {feel.recentAuthors !== null && <span>최근 3개월 사용기 {feel.recentAuthors}명</span>}
    </div>
    {feel.attributes.map(attribute => <div className="pf-feel-attr" key={attribute.code}>
      <div className="pf-feel-line"><b>{attribute.label}</b><span>{attribute.text}</span></div>
      {attribute.quotes.slice(0, 2).map(quote => <div className="pf-citation" key={quote.quoteId}>
        {quote.photoUrl && <span className="pf-citation-thumb"><img src={quote.photoUrl} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} /></span>}
        <p>“{quote.sentence}”{quote.isExample && <em className="pf-example-tag">예시 글</em>}</p>
        <Link to={`/community?view=post&post=${encodeURIComponent(quote.postId)}&quote=${encodeURIComponent(quote.quoteId)}`} state={{ quoteSentence: quote.sentence }}>원문 보기 →</Link>
      </div>)}
    </div>)}
    <div className="pf-citation empty">
      <p>이 제품의 사용기를 더 보거나 직접 남겨 보세요.</p>
      <Link to={COMMUNITY_REVIEW_BOARD}>사용기 게시판 보기 →</Link>
    </div>
  </div>
}

// "이해한 내용": 서버가 읽은 목적·선호·직접 말한 조건·예산을 칩으로 보여 준다. 칩의 ×를 누르면 그 값을 입력에서 빼고 추천만 다시 부른다.
function UnderstoodChips({ understood, kinds, hasPlan, onRemove }: {
  understood: UnderstoodState
  kinds: PeripheralKind[]
  hasPlan: boolean
  onRemove: (removal: UnderstoodRemoval) => void
}) {
  const { interpretation, resolved, adjusted } = understood
  const chip = (key: string, group: string, label: string, removal?: UnderstoodRemoval) => (
    <span key={key}><i>{group}</i>{label}{removal && <button type="button" className="pf-chip-x" aria-label={`${label} 빼기`} onClick={() => onRemove(removal)}>×</button>}</span>
  )
  const rows = kinds.map(kind => {
    const entry = resolved[kind]
    const chips = [
      ...(entry?.purposes ?? []).map(purpose => chip(`${kind}:p:${purpose.code}`, '목적', purpose.label, { type: 'purpose', code: purpose.code })),
      ...(entry?.filters ?? []).map(item => chip(`${kind}:f:${item.condition}`, '조건', item.label, { type: 'filter', kind, condition: item.condition })),
      ...(entry?.preferences ?? []).map(item => chip(`${kind}:s:${item.condition}`, '선호', item.label, { type: 'preference', kind, condition: item.condition, sources: item.sources })),
      ...(interpretation.budget[kind] ? [chip(`${kind}:b`, '예산', wonFmt(interpretation.budget[kind] as number), { type: 'budget', kind })] : []),
    ]
    return { kind, chips }
  })
  const adjustedChips = adjusted.map(item => chip(`a:${item.key}`, '더 맞춤', item.label, { type: 'adjusted', key: item.key }))
  const shared = [
    ...(interpretation.budgetTotal ? [chip('total', '예산', `합계 ${wonFmt(interpretation.budgetTotal)}`, { type: 'budget', kind: null })] : []),
    ...(hasPlan ? [<span className="pc" key="pc"><i>PC 견적</i>본체 조건 연결됨</span>] : []),
  ]
  const empty = rows.every(row => row.chips.length === 0) && adjustedChips.length === 0 && shared.length === 0
  return <div className="pf-understood-body">
    {rows.map(row => <div className="pf-understood-row" key={row.kind}>
      <b>{kindLabel(row.kind)}</b>
      <div className="pf-understood-chips">{row.chips.length ? row.chips : <em>아직 읽은 조건이 없어요</em>}</div>
    </div>)}
    {(adjustedChips.length > 0 || shared.length > 0) && <div className="pf-understood-row"><b>공통</b><div className="pf-understood-chips">{shared}{adjustedChips}</div></div>}
    {interpretation.unrecognized.length > 0 && <p className="pf-unrecognized">이 부분은 아직 반영하지 못했어요: {interpretation.unrecognized.join(' · ')}</p>}
    {empty && kinds.length === 0 && <p className="pf-understood-empty">품목을 고르면 이곳에 이해한 내용이 보여요.</p>}
  </div>
}

/** 종류마다 지금 견적에 올릴 제품: 기본은 1위이고, 다른 선택지를 골랐으면 그 제품(제품 식별자가 있을 때만) */
function chosenProduct(item: PeripheralItem, selection: Record<string, string>) {
  const picked = selection[item.kind]
  const alternative = picked ? item.alternatives.find(candidate => candidate.name === picked && candidate.variantId) : undefined
  if (alternative) {
    return {
      name: alternative.name, brand: alternative.brand ?? item.brand, price: alternative.price, variantId: alternative.variantId ?? null,
      imageUrl: alternative.imageUrl ?? null, productUrl: alternative.productUrl ?? null, fromAlternative: true,
    }
  }
  return { name: item.name, brand: item.brand, price: item.price, variantId: item.variantId, imageUrl: item.imageUrl, productUrl: item.productUrl, fromAlternative: false }
}

export default function PeripheralsPage() {
  const { state, setPeripherals } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const restored = state.editingSheet && state.peripheralSessionId && state.peripherals.length
    ? restoredResult(state.peripherals, state.peripheralSessionId) : null
  const [selected, setSelected] = useState<Set<PeripheralKind>>(() => new Set(restored?.items.map(item => item.kind) ?? KINDS.map(kind => kind.id)))
  // 사용자가 종류 카드를 직접 눌렀는지. 눌렀다면 문장을 읽을 때 그 종류를 서버에 함께 보낸다.
  const [kindsTouched, setKindsTouched] = useState(false)
  const [understood, setUnderstood] = useState<UnderstoodState>(EMPTY_UNDERSTOOD)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PeripheralsResult | null>(restored)
  const [pickedKinds, setPickedKinds] = useState<Set<PeripheralKind>>(() => new Set(restored?.items.map(item => item.kind) ?? []))
  // 종류 → 1위 대신 고른 다른 선택지의 이름. 없으면 1위를 올린다.
  const [selection, setSelection] = useState<Record<string, string>>({})
  const sessionId = useRef<string | null>(restored?.sessionId ?? null)

  const showResults = result !== null
  const selectedKinds = useMemo(() => KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.id), [selected])
  const selectedLabels = useMemo(() => selectedKinds.map(kindLabel), [selectedKinds])
  const pickedItems = useMemo(() => (result?.items ?? []).filter(item => pickedKinds.has(item.kind)), [pickedKinds, result])
  const total = useMemo(() => pickedItems.reduce((sum, item) => sum + chosenProduct(item, selection).price, 0), [pickedItems, selection])
  const budget = understood.interpretation.budgetTotal
  const plan = state.currentPlan
  const conditionCount = useMemo(() => Object.values(understood.resolved).reduce((sum, entry) => sum + (entry ? entry.preferences.length + entry.filters.length : 0), 0), [understood])

  function toggle(kind: PeripheralKind) {
    setSelected(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind); else next.add(kind)
      return next
    })
    setKindsTouched(true)
    setNotice('')
    setResult(null)
  }

  // 채팅 한 문장을 서버가 읽게 한다. 종류를 못 알아들으면 needsKind 로 알려 카드를 띄우게 한다(상태는 바꾸지 않는다).
  async function interpretText(text: string, chosen?: PeripheralKind[]): Promise<SendOutcome> {
    const previous = understood.interpretation === EMPTY_INTERPRETATION ? null : understood.interpretation
    const kinds = chosen ?? (kindsTouched && selectedKinds.length ? selectedKinds : undefined)
    const out = await api.peripherals.interpret({ text, previous, kinds })
    if (out.needsKind && !chosen) return { reply: '', needsKind: true }
    setUnderstood({ interpretation: out.interpretation, resolved: out.resolved, adjusted: [] })
    const nextKinds = chosen ?? out.interpretation.kinds
    if (nextKinds.length) { setSelected(new Set(nextKinds)); setKindsTouched(true) }
    setNotice('')
    setResult(null)
    return { reply: interpretReply(out), needsKind: false }
  }

  async function requestRecommendation(next: UnderstoodState = understood) {
    if (!selected.size) {
      setNotice('추천받을 주변기기를 한 개 이상 선택해주세요.')
      return
    }
    setNotice(''); setError(''); setLoading(true)
    try {
      const out = await api.peripherals.recommend({
        kinds: selectedKinds,
        pcListId: plan?.id,
        ...recommendInputs(next.interpretation),
      }, sessionId.current)
      sessionId.current = out.sessionId
      setResult(out)
      setSelection({})
      setPickedKinds(new Set(out.items.map(item => item.kind)))
    } catch (caught) {
      setError(errorMessage(caught, '주변기기를 추천받지 못했습니다. 잠시 후 다시 시도해주세요.'))
    } finally { setLoading(false) }
  }

  // 칩 삭제·"더 맞추기"는 서버의 문장 해석을 부르지 않고 입력만 고쳐 추천만 다시 받는다.
  function changeUnderstood(next: UnderstoodState) {
    setUnderstood(next)
    if (showResults) void requestRecommendation(next)
  }

  function adjust(chip: PeripheralAdjustChip) {
    const next = applyAdjustChip(understood, chip)
    setUnderstood(next)
    void requestRecommendation(next)
  }

  function toCart() {
    if (!result) return
    // 본체 견적이 없어도 담을 수 있다 — 이 추천을 받은 목록(세션)으로 주변기기만 확정한다.
    if (!plan && !result.sessionId) {
      setNotice('장바구니에 담을 수 없어요. 주변기기 추천을 다시 받아 주세요.')
      return
    }
    const items = result.items.filter(item => pickedKinds.has(item.kind) && chosenProduct(item, selection).variantId).map(item => {
      const product = chosenProduct(item, selection)
      return { kind: item.kind, name: product.name, brand: product.brand, price: product.price, qty: 1, variantId: product.variantId, imageUrl: product.imageUrl, productUrl: product.productUrl }
    })
    if (!items.length) { setNotice('장바구니에 담을 수 있는 품목이 없어요.'); return }
    setPeripherals(items, plan ? undefined : result.sessionId)
    showToast(`주변기기 ${items.length}개를 ${plan ? '통합 ' : ''}장바구니에 담았어요.`)
    navigate('/cart', { state: { plannerMode: 'peripherals' } })
  }

  function togglePicked(kind: PeripheralKind) {
    setPickedKinds(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind); else next.add(kind)
      return next
    })
  }

  // 다른 선택지를 고른다(그 종류도 견적에 담는다). 1위를 다시 고르면 선택이 풀린다.
  function chooseAlternative(item: PeripheralItem, name: string) {
    setSelection(previous => ({ ...previous, [item.kind]: name }))
    setPickedKinds(previous => new Set(previous).add(item.kind))
  }
  function chooseFirst(item: PeripheralItem) {
    setSelection(previous => { const { [item.kind]: _dropped, ...rest } = previous; return rest })
    setPickedKinds(previous => new Set(previous).add(item.kind))
  }

  function recommendationCard(item: PeripheralItem) {
    const chosen = chosenProduct(item, selection)
    const evidence = reviewEvidence(item.reviewAspects)
    const picked = pickedKinds.has(item.kind)
    const entry = understood.resolved[item.kind]
    const understoodLabels = [...(entry?.filters ?? []), ...(entry?.preferences ?? [])].map(condition => condition.label)
    return <section className="pf-kind-result" key={item.kind}>
      <div className="pf-kind-heading"><h2>{item.kindLabel}</h2><span>조건과 리뷰 근거에 가장 잘 맞는 제품</span></div>
      <p className="pf-kind-pref">{understoodLabels.join(' · ') || '선택한 품목과 현재 조건을 기준으로 추천'}</p>
      {chosen.fromAlternative && <p className="pf-chosen-note">다른 선택지를 골랐어요: <b>{chosen.name}</b> · {wonFmt(chosen.price)} — 견적에는 이 제품이 담겨요.</p>}
      <article className="pf-hero-card">
        <div className="pf-hero-side">
          <span className="pf-best">가장 잘 맞아요</span>
          <div className="pf-hero-image">{item.imageUrl ? <img src={item.imageUrl} alt={item.name} loading="lazy" referrerPolicy="no-referrer" onError={event => { event.currentTarget.style.display = 'none' }} /> : <span>제품 이미지</span>}</div>
          <strong className="pf-hero-price pl-mono">{wonFmt(item.price)}</strong>
          <button type="button" className={'pf-pick' + (picked && !chosen.fromAlternative ? ' on' : '')} onClick={() => (chosen.fromAlternative ? chooseFirst(item) : togglePicked(item.kind))}>{chosen.fromAlternative ? '이 제품으로 선택' : picked ? '담았습니다' : '견적에 담기'}</button>
        </div>
        <div className="pf-hero-body">
          <h3>{item.name}</h3>
          <div className="pf-fit-tags">{item.requirement.map(row => <span key={row.key}>✓ {row.value}</span>)}{item.checks.filter(check => check.state === 'fail').map(check => <span className="no" key={check.axis}>✕ {check.label}</span>)}</div>
          {item.reason.text && <p className="pf-main-reason">{item.reason.text}</p>}
          {evidence.length > 0 && <div className="pf-review-evidence"><ReviewRows evidence={evidence} /></div>}
          <FeelBlock item={item} />
          <div className="pf-card-foot">{item.reviewNote && <span>{item.reviewNote}</span>}{item.priceNote && <span>{item.priceNote}</span>}{item.productUrl && <a href={item.productUrl} target="_blank" rel="noreferrer">상품 보기 →</a>}</div>
        </div>
      </article>
      {item.alternatives.length > 0 && <details className="pf-more">
        <summary><span>다른 선택지 {item.alternatives.length}개 · {item.alternatives.map(alternative => alternative.name).join(' · ')}</span></summary>
        <div className="pf-alt-grid">{item.alternatives.map((alternative, index) => { const selectedAlternative = chosen.fromAlternative && chosen.name === alternative.name; return <article className={'pf-alt-card' + (selectedAlternative ? ' on' : '')} key={alternative.name}>
          <header className="pf-alt-head"><i>{index + 2}</i><h3>{alternative.name}</h3><strong className="pl-mono">{wonFmt(alternative.price)}</strong></header>
          <p className="pf-alt-diff">1위보다 <b>{wonFmt(Math.abs(alternative.diff))} {alternative.diff < 0 ? '저렴' : alternative.diff > 0 ? '비쌈' : '같은 가격'}</b></p>
          <div className="pf-review-evidence pf-alt-evidence"><ReviewRows evidence={reviewEvidence(alternative.reviewAspects, 3)} withQuotes /></div>
          {alternative.reviewNote && <small className="pf-alt-note">{alternative.reviewNote}</small>}
          {alternative.variantId
            ? <button type="button" className={'pf-alt-pick' + (selectedAlternative ? ' on' : '')} aria-pressed={selectedAlternative} onClick={() => (selectedAlternative ? chooseFirst(item) : chooseAlternative(item, alternative.name))}>{selectedAlternative ? '✓ 선택됨 (누르면 1위로 되돌려요)' : '이 제품으로 선택'}</button>
            : <button type="button" className="pf-alt-pick" disabled title="서버가 이 제품의 식별 정보를 아직 주지 않아 견적에 담을 수 없어요.">선택 준비 중</button>}
        </article> })}</div>
      </details>}
    </section>
  }

  const understoodPanel = <UnderstoodChips understood={understood} kinds={selectedKinds} hasPlan={Boolean(plan)} onRemove={removal => changeUnderstood(removeUnderstood(understood, removal))} />

  return (
    <PlannerShell sidebar={<PeripheralChat selectedLabels={selectedLabels} conditionCount={conditionCount} showingResults={showResults} onSend={interpretText} />}>
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
            {understoodPanel}
            {result.ignoredInputs.length > 0 && <p className="pf-unrecognized">목록에 없어 반영하지 않았어요: {result.ignoredInputs.join(' · ')}</p>}
          </section>
          {result.adjustChips.length > 0 && <section className="pf-adjust" aria-label="더 맞추기">
            <b>더 맞추기</b>
            <div>{result.adjustChips.map(chip => <button type="button" key={`${chip.kind}:${chip.id}`} disabled={loading} onClick={() => adjust(chip)}>
              <i>{kindLabel(chip.kind)}</i>{chip.label}
            </button>)}</div>
          </section>}
          {loading && <div className="pl-note" role="status">추천을 다시 고르고 있어요…</div>}
          {error && <div className="pl-alert bad" role="alert">{error}</div>}
          {result.status === 'skipped' && <div className="pl-alert warn" role="status">서버가 이번 요청은 추천하지 않았어요. 조건을 바꿔 다시 시도해 주세요.</div>}
          {result.empty.length > 0 && <div className="pl-alert warn" role="status">{result.empty.map(row => `${KINDS.find(kind => kind.id === row.kind)?.label ?? row.kind}: ${row.reason}`).join(' · ')}</div>}
          <div className="pf-results-list">{result.items.map(recommendationCard)}</div>
          <button type="button" className="pf-secondary pf-edit-conditions" onClick={() => setResult(null)}>조건 다시 보기</button>
          {!plan && <div className="pl-alert warn" role="status">본체 견적 없이 주변기기만 담아 확정할 수 있어요. 본체와 함께 확정하려면 <Link to="/start" style={{ color: 'inherit', fontWeight: 700 }}>본체 추천 받으러 가기 →</Link></div>}
          {notice && <div className="pl-alert warn" role="status">{notice}</div>}
          <div className="pf-pick-bar">
            <div>{pickedItems.length ? pickedItems.map(item => <span key={item.kind}><i>{item.kindLabel}</i>{chosenProduct(item, selection).name}</span>) : <span>담은 제품이 없습니다 · 종류마다 하나씩 담을 수 있어요</span>}</div>
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

        <section className="pf-understood">
          <b>이해한 내용</b>
          <span className="pf-understood-hint">왼쪽 대화에서 말한 조건을 서버가 읽은 대로 보여 드려요. ×를 누르면 그 조건을 뺄 수 있어요.</span>
          {understoodPanel}
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
