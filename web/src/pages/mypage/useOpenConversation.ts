import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ConversationSummary } from '../../api'
import { usePlan } from '../../state/PlanContext'
import { isCheckSession } from '../../utils/checkSessions'

/** 지난 대화를 연다 — 좌측 패널의 대화 내역과 같은 규칙(점검 대화는 점검 화면, 확정된 대화는 리포트). */
export function useOpenConversation() {
  const { openConversation } = usePlan()
  const navigate = useNavigate()
  return useCallback(async (item: ConversationSummary) => {
    if (isCheckSession(item.listId)) { navigate('/check?draft=' + item.listId); return }
    const confirmed = item.stage === 'report'
    const opened = await openConversation(item.listId, item.stage === 'results' || confirmed, confirmed)
    if (opened === 'plan') navigate('/plan')
    else if (opened) navigate(confirmed ? '/report/' + item.listId : '/start')
  }, [navigate, openConversation])
}

export const conversationTitle = (item: ConversationSummary) => item.firstMessage?.trim() || item.name
