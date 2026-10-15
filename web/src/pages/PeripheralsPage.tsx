import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PeripheralResultSection from '../components/PeripheralResultSection'
import PlannerShell from '../components/PlannerShell'
import ResizeHandle, { usePanelWidth } from '../components/ResizeHandle'
import {
  api, errorMessage, type PeripheralAdjustChip, type PeripheralItem, type PeripheralKind, type PeripheralsResult,
} from '../api'
import { usePlan } from '../state/PlanContext'
import type { SetupPeripheral } from '../state/types'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import { Linkified } from '../utils/linkify'
import {
  EMPTY_INTERPRETATION, EMPTY_UNDERSTOOD, HAND_SIZE_LABEL, PERIPHERAL_KINDS as KINDS, QUICK_CONDITIONS, SITUATION_LABEL, applyAdjustChip,
  recommendInputs, removeUnderstood, withKinds,
  type UnderstoodRemoval, type UnderstoodState,
} from '../utils/peripherals'
import '../styles/peripherals.css'

type ChatMessage = { id: number; role: 'user' | 'assistant'; text: string }

// 예시는 서버가 실제로 읽는 조건만 쓴다(조용한 곳·손 크기·무선·가벼운 무게·해상도·주사율·예산).
const GREETING = '필요한 품목을 고르고 원하는 조건을 말해 주세요. 예를 들면 “조용한 키보드”, “손이 작아서 가벼운 무선 마우스”, “QHD 165Hz 모니터”처럼요. 예산도 함께 말할 수 있어요(“10만원 이하”, “6만원 이상”).\n궁금한 것은 물어보셔도 돼요. 예: “스피커는 어떤 조건으로 나눌 수 있어?”'
// 서버 설정(chat.chips)과 같은 문장이다. 서버가 같은 종류의 질문으로 읽는다는 것을 서버 시험이 보장한다.
const START_QUESTION_CHIPS = ['모니터는 어떤 조건으로 나눌 수 있어?', '키보드는 어떤 조건으로 나눌 수 있어?', '너가 대답할 수 있는 게 뭐야?']
const RESULT_QUESTION_CHIPS = ['왜 이걸 1위로 골랐어?', '1위랑 2위 차이가 뭐야?', '스펙이 어떻게 돼?', '소리는 어때?']
const NEEDS_KIND_REPLY = '어떤 기기를 찾으세요? 아래에서 골라 주세요.'
// 품목을 여럿 골랐을 때 품목마다 보여 주는 빠른 조건 칩 수(둘 이하를 골랐으면 모두 보인다)
const QUICK_PER_KIND_WHEN_MANY = 2
const PERIPHERAL_CHAT_WIDTH = { key: 'truefit.peripherals.chat.width', initial: 380, min: 280, max: 520 }
const kindLabel = (kind: PeripheralKind) => KINDS.find(entry => entry.id === kind)?.label ?? kind

function restoredResult(items: SetupPeripheral[], sessionId: string): PeripheralsResult {
  return {
    sessionId, status: 'ready', empty: [], ignoredInputs: [], adjustChips: [], notices: [],
    referencePrice: items.reduce((sum, item) => sum + item.price * item.qty, 0),
    priceNote: '확정한 견적에서 불러온 구성입니다.',
    items: items.map(item => ({
      kind: item.kind, kindLabel: kindLabel(item.kind), name: item.name, brand: item.brand ?? '',
      variantId: item.variantId ?? null, productUrl: item.productUrl ?? null, imageUrl: item.imageUrl ?? null,
      price: item.price, priceNote: '확정한 견적에서 불러온 참고가입니다.', requirement: [], checks: [],
      reason: { status: 'restored', text: '저장된 견적에서 불러온 제품입니다.' },
      guide: { status: 'unavailable', text: null }, reviewAspects: [], reviewWeight: 0, reviewNote: '',
      alternatives: [], feel: null, feelNote: null, keySpecs: [], requested: [], pricePosition: null, scoreAxes: [],
    })),
  }
}

interface SendOutcome { reply: string; needsKind: boolean }

function PeripheralChat({ messages, onSay, selectedKinds, selectedLabels, conditionCount, showingResults, questionChips, onSend }: {
  messages: ChatMessage[]
  onSay: (role: ChatMessage['role'], text: string) => void
  selectedKinds: PeripheralKind[]
  selectedLabels: string[]
  conditionCount: number
  showingResults: boolean
  /** 서버가 이번 답 뒤에 권한 질문 문장(결과가 나온 뒤에는 결과에 대한 질문) */
  questionChips: string[]
  /** hintKind: 빠른 조건 칩을 눌렀을 때 그 칩의 품목. 선택한 품목과 함께 서버에 보낸다 */
  onSend: (text: string, kinds?: PeripheralKind[], hintKind?: PeripheralKind) => Promise<SendOutcome>
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const size = usePanelWidth(PERIPHERAL_CHAT_WIDTH.key, PERIPHERAL_CHAT_WIDTH.initial, PERIPHERAL_CHAT_WIDTH.min, PERIPHERAL_CHAT_WIDTH.max)
  // "어떤 기기를 찾으세요?" 카드: 서버가 종류를 알아듣지 못한 문장과, 카드에서 고르는 중인 종류
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [pendingKinds, setPendingKinds] = useState<Set<PeripheralKind>>(() => new Set())
  const logRef = useRef<HTMLDivElement>(null)

  // 새 메시지가 오면 맨 아래로 내려 보여 준다(채팅이 길어져도 직접 스크롤하지 않게).
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [messages, busy, pendingText])

  const quick = useMemo(() => {
    const perKind = selectedKinds.length > 2 ? QUICK_PER_KIND_WHEN_MANY : Number.MAX_SAFE_INTEGER
    return selectedKinds.flatMap(kind => QUICK_CONDITIONS[kind].slice(0, perKind).map(text => ({ kind, text })))
  }, [selectedKinds])

  async function deliver(text: string, kinds?: PeripheralKind[], hintKind?: PeripheralKind) {
    setBusy(true)
    try {
      const outcome = await onSend(text, kinds, hintKind)
      if (outcome.needsKind) {
        setPendingText(text)
        setPendingKinds(new Set())
        onSay('assistant', outcome.reply || NEEDS_KIND_REPLY)
      } else {
        setPendingText(null)
        onSay('assistant', outcome.reply)
      }
    } catch (caught) {
      onSay('assistant', errorMessage(caught, '문장을 읽지 못했어요. 잠시 후 다시 말씀해 주세요.'))
    } finally { setBusy(false) }
  }

  function send(text: string, hintKind?: PeripheralKind) {
    const clean = text.trim()
    if (!clean || busy) return
    onSay('user', clean)
    setDraft('')
    void deliver(clean, undefined, hintKind)
  }

  function chooseKinds() {
    if (!pendingText || pendingKinds.size === 0 || busy) return
    const kinds = KINDS.filter(kind => pendingKinds.has(kind.id)).map(kind => kind.id)
    onSay('user', kinds.map(kindLabel).join(' · '))
    void deliver(pendingText, kinds)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  return (
    <aside className="pl-chat pl-resizable pf-chat" aria-label="주변기기 조건 대화" style={{ width: size.width }}>
      <div className="pl-chat-head"><span className="pl-dot" />주변기기 조건 대화</div>
      <div className="pl-chat-log" ref={logRef}>
        {messages.map(message => <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}><Linkified text={message.text} /></div>)}
        {pendingText !== null && <div className="pf-kind-card" role="group" aria-label="어떤 기기를 찾으세요?">
          <b>어떤 기기를 찾으세요?</b>
          <div>
            {KINDS.map(kind => <button type="button" key={kind.id} className={pendingKinds.has(kind.id) ? 'on' : ''} aria-pressed={pendingKinds.has(kind.id)} disabled={busy}
              onClick={() => setPendingKinds(previous => { const next = new Set(previous); if (next.has(kind.id)) next.delete(kind.id); else next.add(kind.id); return next })}>{kind.label}</button>)}
          </div>
          <button type="button" className="pf-kind-card-go" disabled={busy || pendingKinds.size === 0} onClick={chooseKinds}>이 종류로 찾기</button>
        </div>}
        {busy && <div className="pf-typing" role="status" aria-label="문장을 읽는 중"><i /><i /><i /></div>}
        {selectedLabels.length > 0 && <div className="pf-reflected">✓ 선택 품목: {selectedLabels.join(' · ')}{conditionCount ? ` · 조건 ${conditionCount}개` : ''}</div>}
        {showingResults && <div className="pl-msg-bot">품목마다 하나씩 골랐어요. 스펙 조건과 리뷰 근거를 함께 확인해 주세요.</div>}
      </div>
      <div className="pl-chat-foot">
        {quick.length > 0 && <div className="pl-choices pf-quick" aria-label="빠른 조건">
          {quick.map(chip => <button type="button" className="pl-choice" key={`${chip.kind}:${chip.text}`} disabled={busy}
            title={`${kindLabel(chip.kind)} · ${chip.text}`} onClick={() => send(chip.text, chip.kind)}>{chip.text}</button>)}
        </div>}
        {questionChips.length > 0 && <div className="pl-choices pf-quick" aria-label="물어볼 수 있는 질문">
          {questionChips.map(text => <button type="button" className="pl-choice" key={text} disabled={busy} onClick={() => send(text)}>{text}</button>)}
        </div>}
        <form className="pl-input" onSubmit={submit}>
          <input value={draft} onChange={event => setDraft(event.target.value)} placeholder="원하는 조건을 적거나 궁금한 것을 물어보세요" aria-label="주변기기 조건 입력" />
          <button type="submit" className="pl-send" disabled={!draft.trim() || busy}>보내기</button>
        </form>
      </div>
      <ResizeHandle width={size.width} min={size.min} max={size.max} label="주변기기 대화창 너비" onChange={size.setWidth} onReset={size.reset} />
    </aside>
  )
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
      ...(interpretation.budgetMin[kind] ? [chip(`${kind}:bm`, '최소 가격', `${wonFmt(interpretation.budgetMin[kind] as number)} 이상`, { type: 'budget_min', kind })] : []),
      // 선호 브랜드를 말하면 서버가 "브랜드" 축 강조를 저절로 붙인다 — 브랜드 칩으로 이미 보이므로 강조 칩에서는 뺀다.
      ...(interpretation.emphasis[kind] ?? []).filter(axis => axis !== '브랜드').map(axis => chip(`${kind}:e:${axis}`, '중요', axis, { type: 'emphasis', kind, axis })),
      ...(interpretation.brandLike[kind] ?? []).map(brand => chip(`${kind}:bl:${brand}`, '선호 브랜드', brand, { type: 'brand_like', kind, brand })),
      ...(interpretation.brandAvoid[kind] ?? []).map(brand => chip(`${kind}:ba:${brand}`, '뺄 브랜드', brand, { type: 'brand_avoid', kind, brand })),
    ]
    return { kind, chips }
  })
  const adjustedChips = adjusted.map(item => chip(`a:${item.key}`, '더 맞춤', item.label, { type: 'adjusted', key: item.key }))
  // 품목의 목적 칩으로 이미 보이는 상황은 빼고, 어느 품목에도 안 보이는 상황(예: 마우스의 "조용해야 함")만 공통에 보여 준다.
  const shownCodes = new Set(kinds.flatMap(kind => (resolved[kind]?.purposes ?? []).map(purpose => purpose.code)))
  const situationChips = interpretation.situations
    .filter(code => !shownCodes.has(code) && SITUATION_LABEL[code])
    .map(code => chip(`s:${code}`, '상황', SITUATION_LABEL[code], { type: 'situation', code }))
  const shared = [
    ...situationChips,
    ...(interpretation.budgetTotal ? [chip('total', '예산', `합계 ${wonFmt(interpretation.budgetTotal)}`, { type: 'budget', kind: null })] : []),
    ...(interpretation.handSize ? [chip('hand', '손 크기', HAND_SIZE_LABEL[interpretation.handSize], { type: 'handSize' })] : []),
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
  // 채팅 메시지는 페이지가 들고 있다 — 추천 결과의 유의사항(notices)도 같은 채팅에 말하기 위해서다.
  const [messages, setMessages] = useState<ChatMessage[]>([{ id: 1, role: 'assistant', text: GREETING }])
  const nextMessageId = useRef(2)
  const [questionChips, setQuestionChips] = useState<string[]>(START_QUESTION_CHIPS)
  const resultChips = useRef<string[]>([])
  const spokenNotices = useRef('')
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
  // 결과 화면은 품목이 둘 이상이면 탭으로 나눠 한 번에 한 품목만 보인다.
  const [activeKind, setActiveKind] = useState<PeripheralKind | null>(null)
  const activeItem = result?.items.find(item => item.kind === activeKind) ?? result?.items[0] ?? null
  const conditionCount = useMemo(() => Object.values(understood.resolved).reduce((sum, entry) => sum + (entry ? entry.preferences.length + entry.filters.length : 0), 0), [understood])

  const say = (role: ChatMessage['role'], text: string) => setMessages(previous => [...previous, { id: nextMessageId.current++, role, text }])

  function toggle(kind: PeripheralKind) {
    const next = new Set(selected)
    if (next.has(kind)) next.delete(kind); else next.add(kind)
    setSelected(next)
    // 서버 해석에 남은 종류가 다음 문장에서 되살아나 방금 푼 체크가 다시 선택되지 않게, 해석의 종류도 같이 맞춘다(QA 종합#32).
    setUnderstood(previous => withKinds(previous, KINDS.filter(entry => next.has(entry.id)).map(entry => entry.id)))
    setKindsTouched(true)
    setNotice('')
    setResult(null)
  }

  // 채팅 한 문장을 서버가 한 번에 처리한다: 읽기 + 질문 답변 + 답장 문장. 종류를 못 알아들으면 needsKind 로 알려 카드를 띄우게 한다.
  // 결과 화면에서 조건이 바뀌면 결과 화면에 머문 채 결과만 다시 받는다(첫 화면으로 돌아가지 않는다 — QA 종합#41).
  async function sendTurn(text: string, chosen?: PeripheralKind[], hintKind?: PeripheralKind): Promise<SendOutcome> {
    const previous = understood.interpretation === EMPTY_INTERPRETATION ? null : understood.interpretation
    const base = kindsTouched ? selectedKinds : []
    const kinds = chosen ?? (hintKind ? [...new Set([...base, hintKind])] : (base.length ? base : undefined))
    const out = await api.peripherals.chat({ text, previous, kinds, sessionId: sessionId.current, pcListId: plan?.id })
    sessionId.current = out.sessionId
    if (out.turn.resultChips.length) resultChips.current = out.turn.resultChips
    setQuestionChips(showResults ? resultChips.current : out.turn.chips)
    if (out.needsKind && !chosen && !hintKind) return { reply: out.turn.answer?.text ?? '', needsKind: true }
    const changed = out.turn.newConditions.length > 0
    // 질문만 한 턴(조건을 바꾸지 않은 질문)은 선택한 품목과 이해한 내용을 건드리지 않는다. "모니터는 어떤 조건으로…?"라고
    // 물었다고 선택 품목이 모니터 하나로 줄면 안 된다. 종류 카드로 종류를 골라 보낸 경우만 그 종류를 받아들인다.
    const questionOnly = out.turn.answer !== null && !changed && !chosen && !hintKind
    if (!questionOnly) {
      const next: UnderstoodState = { interpretation: out.interpretation, resolved: out.resolved, adjusted: changed ? [] : understood.adjusted }
      setUnderstood(next)
      if (out.interpretation.kinds.length) { setSelected(new Set(out.interpretation.kinds)); setKindsTouched(true) }
      if (showResults && changed) void requestRecommendation(next)
    }
    setNotice('')
    return { reply: out.turn.reply, needsKind: false }
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
      // 서버가 알리는 유의사항(예: PC 견적 없이 고른 모니터)은 채팅으로도 말한다. 같은 내용을 다시 받아도 되풀이하지 않는다.
      const spoken = out.notices.map(item => item.text).join('\n')
      if (spoken && spoken !== spokenNotices.current) out.notices.forEach(item => say('assistant', item.text))
      spokenNotices.current = spoken
      setQuestionChips(resultChips.current.length ? resultChips.current : RESULT_QUESTION_CHIPS)
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

  // 탭에서 ← → 로 품목을 옮긴다.
  function moveTab(event: KeyboardEvent<HTMLDivElement>) {
    if (!result || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return
    const kinds = result.items.map(item => item.kind)
    const current = kinds.indexOf(activeItem?.kind ?? kinds[0])
    const next = kinds[(current + (event.key === 'ArrowRight' ? 1 : kinds.length - 1)) % kinds.length]
    setActiveKind(next)
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-kind="${next}"]`)?.focus()
    event.preventDefault()
  }

  function recommendationCard(item: PeripheralItem) {
    const chosen = chosenProduct(item, selection)
    return <PeripheralResultSection key={item.kind} item={item} chosenName={chosen.fromAlternative ? chosen.name : null}
      picked={pickedKinds.has(item.kind)} onTogglePicked={() => togglePicked(item.kind)}
      onChoose={name => (name === null ? chooseFirst(item) : chooseAlternative(item, name))} />
  }

  // 접힌 "이해한 내용" 줄: 읽은 조건 이름을 앞에서부터 몇 개만 보인다.
  const understoodLabels = [
    ...selectedKinds.flatMap(kind => {
      const entry = understood.resolved[kind]
      return [...(entry?.purposes ?? []).map(purpose => purpose.label), ...(entry?.filters ?? []).map(condition => condition.label), ...(entry?.preferences ?? []).map(condition => condition.label)]
    }),
    ...understood.interpretation.situations.map(code => SITUATION_LABEL[code]).filter(Boolean),
    ...selectedKinds.flatMap(kind => {
      const { budget, budgetMin } = understood.interpretation
      return [
        ...(budget[kind] ? [`${kindLabel(kind)} ${wonFmt(budget[kind] as number)} 이하`] : []),
        ...(budgetMin[kind] ? [`${kindLabel(kind)} ${wonFmt(budgetMin[kind] as number)} 이상`] : []),
      ]
    }),
  ]
  const understoodUnique = [...new Set(understoodLabels)]
  const understoodSummary = understoodUnique.length > 4
    ? `${understoodUnique.slice(0, 4).join(' · ')} 외 ${understoodUnique.length - 4}개`
    : understoodUnique.join(' · ')

  const understoodPanel = <UnderstoodChips understood={understood} kinds={selectedKinds} hasPlan={Boolean(plan)} onRemove={removal => changeUnderstood(removeUnderstood(understood, removal))} />

  return (
    <PlannerShell sidebar={<PeripheralChat messages={messages} onSay={say} selectedKinds={selectedKinds} selectedLabels={selectedLabels} conditionCount={conditionCount}
      showingResults={showResults} questionChips={questionChips} onSend={sendTurn} />}>
      <div className={'pf-page' + (showResults ? ' results' : '')}>
        {showResults ? <>
          <div className="pf-results-heading">
            <div><span className="pl-eyebrow pl-mono">주변기기 견적 · 추천 결과</span><h1>원하는 느낌에 맞춘 주변기기</h1></div>
            <div className="pf-total">
              <strong className="pl-mono">{wonFmt(total)}</strong>
              <span>{budget != null ? `주변기기 예산 ${wonFmt(budget)} · ${total <= budget ? `잔액 ${wonFmt(budget - total)}` : `${wonFmt(total - budget)} 초과`}` : '예산을 알려 주면 잔액도 보여 드려요'}</span>
            </div>
          </div>
          {/* 이해한 내용·더 맞추기는 접어 두고, 열면 칩 × 제거와 더 맞추기를 쓸 수 있다. 접힌 줄에는 읽은 조건 요약만 보인다. */}
          <details className="pf-understood pr-understood">
            <summary>
              <b>이해한 내용</b>
              <span className="pr-understood-summary">{understoodSummary || '읽은 조건이 아직 없어요'}</span>
              <em>조건 바꾸기</em>
            </summary>
            {understoodPanel}
            {result.adjustChips.length > 0 && <div className="pf-adjust" aria-label="더 맞추기">
              <b>더 맞추기</b>
              <div>{result.adjustChips.map(chip => <button type="button" key={`${chip.kind}:${chip.id}`} disabled={loading} onClick={() => adjust(chip)}>
                <i>{kindLabel(chip.kind)}</i>{chip.label}
              </button>)}</div>
            </div>}
          </details>
          {result.ignoredInputs.length > 0 && <p className="pf-unrecognized">목록에 없어 반영하지 않았어요: {result.ignoredInputs.join(' · ')}</p>}
          {loading && <div className="pl-note" role="status">추천을 다시 고르고 있어요…</div>}
          {error && <div className="pl-alert bad" role="alert">{error}</div>}
          {result.status === 'skipped' && <div className="pl-alert warn" role="status">서버가 이번 요청은 추천하지 않았어요. 조건을 바꿔 다시 시도해 주세요.</div>}
          {result.empty.length > 0 && <div className="pl-alert warn" role="status">{result.empty.map(row => `${KINDS.find(kind => kind.id === row.kind)?.label ?? row.kind}: ${row.reason}`).join(' · ')}</div>}
          {result.items.length > 1 && <div className="pr-tabs" role="tablist" aria-label="품목" onKeyDown={moveTab}>
            {result.items.map(item => <button type="button" role="tab" key={item.kind} aria-selected={item.kind === activeItem?.kind}
              tabIndex={item.kind === activeItem?.kind ? 0 : -1} data-kind={item.kind}
              className={'pr-tab' + (item.kind === activeItem?.kind ? ' on' : '')} onClick={() => setActiveKind(item.kind)}>
              <b>{item.kindLabel}</b>
              {!pickedKinds.has(item.kind) && <span>견적에서 뺌</span>}
            </button>)}
          </div>}
          <div className="pf-results-list">{activeItem && recommendationCard(activeItem)}</div>
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
