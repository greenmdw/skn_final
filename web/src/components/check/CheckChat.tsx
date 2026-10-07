import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Linkified } from '../../utils/linkify'
import UpgradeCard from './UpgradeCard'

export type ChatEntry =
  | { id: string; kind: 'bot' | 'user'; text: string }
  | { id: string; kind: 'request'; question: string; tags: string[] }
  | { id: string; kind: 'notice'; text: string }
  | { id: string; kind: 'reply'; answerId: string; summary: string; reused: boolean }

export default function CheckChat({ entries, busy, analyzed, comparing, hasAnswer, onSend, onShowAnswer, upgrade, onOpenUpgrade }: {
  entries: ChatEntry[]
  busy: boolean
  analyzed: boolean
  comparing: boolean
  hasAnswer: (answerId: string) => boolean
  onSend: (text: string) => void
  onShowAnswer: (answerId: string) => void
  /** 분석이 끝난 뒤 입력칸 위에 "업그레이드 추천 받기" 버튼을 보여 준다 */
  onOpenUpgrade?: () => void
  /** 있으면 대화 맨 아래에 업그레이드 추천 입력 카드를 보여 준다 */
  upgrade?: { initialBudget: number | null; initialQuestion: string; busy: boolean; onSubmit: (budget: number, question: string) => void; onCancel: () => void } | null
}) {
  const [draft, setDraft] = useState('')
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [entries, busy, upgrade])

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    onSend(text)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  const hint = !analyzed
    ? '추가 질문을 남기면 분석 기준에 함께 반영돼요.'
    : comparing ? '저장 견적 비교에 대한 질문은 "두 견적 차이 해설"에 쌓여요.' : '분석 결과를 보면서 궁금한 점을 물어보세요.'

  return (
    <aside className="pl-chat ck-chat" aria-label="견적 점검 대화">
      <div className="pl-chat-head"><span className="pl-dot" />견적 점검 대화</div>
      <div className="pl-chat-log ck-chat-log" ref={logRef}>
        {entries.map(entry => {
          if (entry.kind === 'request') {
            return (
              <div className="ck-bubble user" key={entry.id}>
                <span className="ck-chat-context-label">내 평가 요청</span>
                <b className="ck-chat-context-question">{entry.question}</b>
                <span className="ck-chat-context-tags">{entry.tags.map(tag => <span key={tag}>{tag}</span>)}</span>
              </div>
            )
          }
          if (entry.kind === 'notice') return <div className="ck-bubble notice" key={entry.id}><Linkified text={entry.text} /></div>
          if (entry.kind === 'reply') {
            return (
              <div className="ck-bubble reply" key={entry.id}>
                <b>{entry.reused ? '이전에 답변한 해설을 다시 보여드릴게요.' : '두 견적 차이 해설에 답변을 추가했어요.'}</b>
                <span>{entry.summary.length > 64 ? `${entry.summary.slice(0, 64)}…` : entry.summary}</span><br />
                {hasAnswer(entry.answerId) && <button type="button" className="ck-chat-answer-link" onClick={() => onShowAnswer(entry.answerId)}>차이 해설 보기</button>}
              </div>
            )
          }
          return <div className={`ck-bubble${entry.kind === 'user' ? ' user' : ''}`} key={entry.id}><Linkified text={entry.text} /></div>
        })}
        {upgrade && <UpgradeCard initialBudget={upgrade.initialBudget} initialQuestion={upgrade.initialQuestion} busy={upgrade.busy} onSubmit={upgrade.onSubmit} onCancel={upgrade.onCancel} />}
        {busy && <div className="pl-typing pl-mono">···</div>}
      </div>
      <div className="pl-chat-foot ck-chat-foot">
        <div className="ck-chat-hint-row">
          <p className="ck-chat-hint">{hint}</p>
          {analyzed && onOpenUpgrade && (
            <button type="button" className="ck-chat-upgrade" onClick={onOpenUpgrade} disabled={Boolean(upgrade)} title="이 견적의 부품을 유지하고, 예산 안에서 바꾸면 좋은 부품을 추천받아요">업그레이드 추천 받기</button>
          )}
        </div>
        <form className="ck-chat-input" onSubmit={submit}>
          <textarea value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} aria-label="추가 질문" placeholder="예: 파워 용량이 충분한지도 봐줘" />
          <button type="submit" disabled={busy || !draft.trim()}>보내기</button>
        </form>
      </div>
    </aside>
  )
}
