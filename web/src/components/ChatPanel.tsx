import { useEffect, useRef, useState, type FormEvent } from 'react'
import { usePlan } from '../state/PlanContext'

// 왼쪽 채팅. 메시지·선택지·입력은 PlanProvider 가 서버(조건 세션 / 결과 대화)와 주고받은 것을 그대로 보여 준다.
export default function ChatPanel({ title, placeholder }: { title: string; placeholder: string }) {
  const { messages, busy, state, handleInput, handleChoice } = usePlan()
  const [draft, setDraft] = useState('')
  const log = useRef<HTMLDivElement>(null)
  const last = messages[messages.length - 1]
  // 선택지는 마지막 봇 메시지에 붙은 것만 누를 수 있다(지난 질문의 칩은 남기지 않는다).
  const choices = last?.role === 'bot' ? last.choices : undefined
  const disabled = state.stage === 3   // 추천을 계산하는 동안은 입력을 받지 않는다

  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight }, [messages, busy])

  function submit(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || disabled) return
    setDraft('')
    handleInput(text)
  }

  return (
    <aside className="pl-chat" aria-label={title}>
      <div className="pl-chat-head"><span className="pl-dot" />{title}</div>
      <div className="pl-chat-log" ref={log}>
        {messages.map(message => (
          <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}>{message.text}</div>
        ))}
        {busy && <div className="pl-typing pl-mono" aria-label="답변 준비 중">···</div>}
      </div>
      <div className="pl-chat-foot">
        {choices && choices.length > 0 && !busy && (
          <div className="pl-choices" style={{ marginBottom: 10 }}>
            {choices.map(choice => (
              <button key={choice.value} type="button" className="pl-choice" onClick={() => handleChoice(choice)}>{choice.label}</button>
            ))}
          </div>
        )}
        <form className="pl-input" onSubmit={submit}>
          <input value={draft} onChange={e => setDraft(e.target.value)} placeholder={placeholder} disabled={disabled} aria-label="메시지 입력" />
          <button type="submit" className="pl-send" disabled={disabled || !draft.trim()}>보내기</button>
        </form>
      </div>
    </aside>
  )
}
