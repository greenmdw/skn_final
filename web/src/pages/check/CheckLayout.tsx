import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import PlannerShell from '../../components/PlannerShell'
import CheckChat from '../../components/check/CheckChat'
import '../../styles/check2.css'
import { useCheckChat } from './useCheckChat'

export const CHECK2 = '/check2'
const STEPS = [
  { key: 'upload', label: '① 올리기', path: () => CHECK2 },
  { key: 'parts', label: '② 인식 확인', path: (id: string) => `${CHECK2}/${id}/parts` },
  { key: 'review', label: '③ 종합 평가', path: (id: string) => `${CHECK2}/${id}/review` },
  { key: 'replace', label: '④ 교체 구성', path: (id: string) => `${CHECK2}/${id}/replace` },
  { key: 'confirm', label: '⑤ 확정', path: (id: string) => `${CHECK2}/${id}/confirm` },
] as const
export type StepKey = typeof STEPS[number]['key']

function StepBar({ current, draftId, reachable }: { current: StepKey; draftId?: string; reachable: StepKey[] }) {
  return (
    <nav className="c2-steps" aria-label="점검 단계">
      {STEPS.map(step => {
        const enabled = step.key === 'upload' || (draftId && reachable.includes(step.key))
        const cls = `c2-step${step.key === current ? ' on' : ''}`
        return enabled && step.key !== current
          ? <Link key={step.key} className={cls} to={step.path(draftId ?? '')}>{step.label}</Link>
          : <span key={step.key} className={cls + (enabled ? '' : ' off')} aria-current={step.key === current ? 'step' : undefined}>{step.label}</span>
      })}
    </nav>
  )
}

/** 단계 화면의 공통 틀. 채팅은 ② 이후(chat=true)에만 왼쪽에 나온다 — ① 은 채팅 없이 폼만 둔다. */
export default function CheckLayout({ current, draftId, analyzed = false, reachable, chat, onChatReply, children }: {
  current: StepKey; draftId?: string; analyzed?: boolean; reachable: StepKey[]; chat: boolean; onChatReply?: () => void; children: ReactNode
}) {
  const chatState = useCheckChat(chat ? draftId : undefined, analyzed, onChatReply)
  const sidebar = chat ? (
    <CheckChat entries={chatState.entries} busy={chatState.busy} analyzed={analyzed} comparing={false} hasAnswer={() => false}
      onSend={text => void chatState.send(text)} onShowAnswer={() => undefined} />
  ) : undefined
  return (
    <PlannerShell sidebar={sidebar}>
      <div className="c2-page">
        <StepBar current={current} draftId={draftId} reachable={reachable} />
        {children}
      </div>
    </PlannerShell>
  )
}
