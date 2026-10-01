import { useMemo, useRef, useState, type FormEvent } from 'react'
import PlannerShell from '../components/PlannerShell'
import '../styles/peripherals.css'

type PeripheralKind = 'monitor' | 'keyboard' | 'mouse' | 'speaker'
type ChatMessage = { id: number; role: 'user' | 'assistant'; text: string }

const KINDS: { id: PeripheralKind; label: string; description: string }[] = [
  { id: 'monitor', label: '모니터', description: '해상도·주사율·화면 크기' },
  { id: 'keyboard', label: '키보드', description: '타건감·소음·배열' },
  { id: 'mouse', label: '마우스', description: '크기·무게·연결 방식' },
  { id: 'speaker', label: '스피커', description: '크기·출력·연결 방식' },
]

const QUICK = ['FHD 144Hz', 'QHD 165Hz', '4K', '잘 모르겠어요']

function parseCondition(text: string): { spec: string[]; feel: string[] } {
  const spec: string[] = []
  const feel: string[] = []
  const budget = text.match(/(\d+(?:[.,]\d+)?)\s*만\s*원/)
  if (budget) spec.push(`예산 ${budget[1]}만 원`)
  if (/QHD|1440/i.test(text)) spec.push(/165\s*Hz/i.test(text) ? 'QHD 165Hz' : 'QHD')
  else if (/FHD|1080/i.test(text)) spec.push(/144\s*Hz/i.test(text) ? 'FHD 144Hz' : 'FHD')
  else if (/4K|UHD|2160/i.test(text)) spec.push('4K')
  if (/조용|저소음|소음/.test(text)) feel.push('조용한 사용감')
  if (/쫀득|타건/.test(text)) feel.push('쫀득한 타건감')
  if (/가벼|경량/.test(text)) feel.push('가벼운 무게')
  if (/손이?\s*작|작은\s*손/.test(text)) feel.push('작은 손')
  if (/눈.*편|눈부심|피로/.test(text)) feel.push('눈이 편한 화면')
  return { spec, feel }
}

function PeripheralChat({ selected, spec, feel, onMessage }: {
  selected: Set<PeripheralKind>
  spec: string[]
  feel: string[]
  onMessage: (text: string, parsed: { spec: string[]; feel: string[] }) => void
}) {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 1, role: 'assistant', text: '필요한 품목을 고르고 원하는 느낌을 말해 주세요. 예를 들면 “조용하고 쫀득한 키보드”, “손이 작아서 가벼운 마우스”처럼요.' },
  ])
  const nextId = useRef(2)

  function send(text: string) {
    const clean = text.trim()
    if (!clean) return
    const parsed = parseCondition(clean)
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
  const [selected, setSelected] = useState<Set<PeripheralKind>>(
    () => new Set(KINDS.map(kind => kind.id)),
  )
  const [specConditions, setSpecConditions] = useState<string[]>([])
  const [feelConditions, setFeelConditions] = useState<string[]>([])
  const [extraConditions, setExtraConditions] = useState<string[]>([])
  const [notice, setNotice] = useState('')

  const selectedLabels = useMemo(() => KINDS.filter(kind => selected.has(kind.id)).map(kind => kind.label), [selected])

  function toggle(kind: PeripheralKind) {
    setSelected(previous => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind); else next.add(kind)
      return next
    })
    setNotice('')
  }

  function addConditions(text: string, parsed: { spec: string[]; feel: string[] }) {
    setSpecConditions(previous => [...new Set([...previous, ...parsed.spec])])
    setFeelConditions(previous => [...new Set([...previous, ...parsed.feel])])
    if (!parsed.spec.length && !parsed.feel.length) setExtraConditions(previous => [...new Set([...previous, text])])
    setNotice('')
  }

  function requestRecommendation() {
    if (!selected.size) {
      setNotice('추천받을 주변기기를 한 개 이상 선택해주세요.')
      return
    }
    setNotice('주변기기 추천 화면은 준비됐지만, 실제 제품 추천을 받으려면 전용 백엔드 API 연결이 필요합니다.')
  }

  return (
    <PlannerShell sidebar={<PeripheralChat selected={selected} spec={specConditions} feel={feelConditions} onMessage={addConditions} />}>
      <div className="pf-page">
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
          </section>
        </div>

        <section className="pf-extra">
          <b>추가 조건</b><span>대화에서 말한 나머지 조건을 그대로 쌓아요.</span>
          <div className="pf-chips">{extraConditions.map(condition => <span key={condition}>{condition}</span>)}{extraConditions.length === 0 && <p>아직 쌓인 추가 조건이 없어요.</p>}</div>
        </section>

        <div className="pf-action">
          <div><b>{selectedLabels.length ? `${selectedLabels.join(' · ')} 선택됨` : '품목을 선택해주세요'}</b><span>실제 상품 데이터는 서버 추천 응답이 연결된 뒤 표시합니다.</span></div>
          <button type="button" className="pl-btn" onClick={requestRecommendation}>추천 받기</button>
        </div>
        {notice && <div className="pl-alert warn" role="status">{notice}</div>}
      </div>
    </PlannerShell>
  )
}
