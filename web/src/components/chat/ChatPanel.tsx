import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react'
import { usePlan } from '../../state/PlanContext'
import type { ChatChoice, ChatMessage } from '../../state/types'

function BotFace() {
  return (
    <div className="bot-face" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none"><rect x="4" y="7" width="16" height="12" rx="5" stroke="currentColor" /><circle cx="9" cy="13" r="1.4" fill="currentColor" /><circle cx="15" cy="13" r="1.4" fill="currentColor" /><path d="M12 7V4m-2 0h4M2 12h2m16 0h2" stroke="currentColor" strokeLinecap="round" /></svg>
    </div>
  )
}

function MessageBubble({ message, onChoice }: { message: ChatMessage; onChoice: (choice: ChatChoice) => void }) {
  return (
    <div className={'message ' + message.role}>
      {message.role === 'bot' && <BotFace />}
      <div className="bubble" style={{ whiteSpace: 'pre-line' }}>
        {message.text}
        {message.choices && <div className="choice-row">
          {message.choices.map(choice => (
            <button key={choice.value} type="button" onClick={() => onChoice(choice)}>{choice.label}</button>
          ))}
        </div>}
      </div>
    </div>
  )
}

const STARTER_PROMPTS = [
  { text: '150만원으로 QHD 게임용 PC를 맞춰줘', label: '"150만원으로 게임용 PC 맞춰줘"' },
  { text: '배틀그라운드를 QHD 165Hz로 하고 싶어', label: '"배틀그라운드 QHD 165Hz로 하고 싶어"' },
  { text: '영상편집용인데 최대한 조용했으면 좋겠어', label: '"영상편집용인데 최대한 조용했으면 좋겠어"' },
]

const QUICK_CARDS = [
  { text: '게임용 PC를 추천해줘', icon: '🎮', label: <>게임용<br />PC</> },
  { text: '영상편집용 PC를 추천해줘', icon: '🎬', label: <>영상편집<br />PC</> },
  { text: '개발과 AI 작업용 PC를 추천해줘', icon: '⌁', label: <>개발/AI<br />PC</> },
  { text: '잘 모르겠어. 질문하면서 추천해줘', icon: '•••', label: <>잘 모르겠어요<br />추천받기</> },
]

export function ChatPanel({ mobileActive }: { mobileActive: boolean }) {
  const { messages, starterHidden, handleInput, handleChoice } = usePlan()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const chatRef = useRef<HTMLDivElement>(null)
  const composing = useRef(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
    })
    return () => cancelAnimationFrame(frame)
  }, [messages, mobileActive])

  function submit() {
    if (composing.current) return
    const value = textareaRef.current?.value ?? ''
    handleInput(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    submit()
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229 || composing.current) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <section className={'pane interview-pane' + (mobileActive ? ' mobile-active' : '')} data-pane="interview" aria-labelledby="interviewTitle">
      <div className="interview-head pane-heading">
        <p className="eyebrow" id="interviewTitle">AI PC INTERVIEW</p>
        <span className="live-hint"><i className="live-dot" />AI와 대화하며 설계해요</span>
      </div>
      <div ref={chatRef} className="chat-area">
        <div className="chat-scroll" aria-live="polite">
          {messages.map(m => <MessageBubble key={m.id} message={m} onChoice={handleChoice} />)}
        </div>
        {!starterHidden && (
          <div className="starter-content">
            <p className="micro-title">◉ 이렇게 말해보세요</p>
            <div className="prompt-list">
              {STARTER_PROMPTS.map(p => (
                <button key={p.text} type="button" onClick={() => handleInput(p.text)}>
                  <span>{p.label}</span><span className="arr">→</span>
                </button>
              ))}
            </div>
            <p className="micro-title">⌘ 빠른 시작</p>
            <div className="quick-grid">
              {QUICK_CARDS.map(c => (
                <button key={c.text} className="quick-card" type="button" onClick={() => handleInput(c.text)}>
                  <span className="qicon">{c.icon}</span><span>{c.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="composer-wrap">
        <form className="composer" onSubmit={onSubmit}>
          <textarea ref={textareaRef} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }} aria-label="원하는 PC 조건 입력" placeholder="원하는 PC에 대해 자유롭게 말씀해주세요..." onKeyDown={onKeyDown} />
          <div className="composer-actions">
            <button className="mini-icon" type="button" aria-label="조건 추가">＋</button>
            <button className="mini-icon" type="button" aria-label="링크 첨부">⌕</button>
            <button className="mini-icon" type="button" aria-label="이미지 첨부">▧</button>
            <button className="send-btn" type="submit" aria-label="메시지 보내기">
              <svg viewBox="0 0 24 24" fill="none"><path d="m5 4 15 8-15 8 3-8-3-8Z" fill="currentColor" /><path d="M8 12h12" stroke="#062019" strokeWidth={1.5} /></svg>
            </button>
          </div>
        </form>
        <div className="keyboard-tip">Shift + Enter 로 줄바꿈</div>
      </div>
    </section>
  )
}
