import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useSetups } from '../state/SetupsContext'
import { useOpenConversation } from '../pages/mypage/useOpenConversation'

/** Resolve the conversation in the destination tab before opening its planner. */
export default function ConversationPage() {
  const { id } = useParams()
  const { conversations, conversationsError } = useSetups()
  const openConversation = useOpenConversation()
  const started = useRef<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!id || !conversations || started.current === id) return
    started.current = id
    const item = conversations.find(entry => entry.listId === id)
    if (!item) { setError('대화를 찾을 수 없어요. 로그인 상태를 확인해 주세요.'); return }
    void openConversation(item).catch(() => setError('대화를 불러오지 못했어요. 다시 시도해 주세요.'))
  }, [id, conversations, openConversation])
  return <main className="pl-page"><p role="status">{error || conversationsError || '대화를 불러오는 중이에요…'}</p><Link to="/mypage?tab=consults">상담 기록으로</Link></main>
}
