import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../../api'
import type { ChatEntry } from '../../components/check/CheckChat'
import { newClientId } from '../../utils/checkReview'

const INTRO: ChatEntry = { id: 'intro', kind: 'bot', text: '읽은 부품이나 점검 결과에 대해 물어보세요. 분석을 마친 뒤부터 답해 드려요.' }

/** ② 이후 화면의 대화. 같은 서버 세션(초안 id = 대화 id)의 기록을 읽고 보낸다. */
export function useCheckChat(draftId: string | undefined, analyzed: boolean, onReply?: () => void) {
  const [entries, setEntries] = useState<ChatEntry[]>([INTRO])
  const [busy, setBusy] = useState(false)
  const loaded = useRef<string | null>(null)

  useEffect(() => {
    if (!draftId || !analyzed || loaded.current === draftId) return
    loaded.current = draftId
    api.quoteDrafts.chatHistory(draftId).then(messages => {
      const restored: ChatEntry[] = messages.filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ id: m.id, kind: m.role === 'user' ? 'user' : 'bot', text: m.text }) as ChatEntry)
      if (restored.length) setEntries([INTRO, ...restored])
    }).catch(() => { /* 기록을 못 읽어도 새 대화로 시작한다 */ })
  }, [draftId, analyzed])

  async function send(text: string) {
    const clientId = newClientId()
    setEntries(prev => [...prev, { id: `u-${clientId}`, kind: 'user', text }])
    if (!draftId || !analyzed) {
      setEntries(prev => [...prev, { id: `b-${clientId}`, kind: 'bot', text: '먼저 분석을 해 주세요. 분석한 결과를 바탕으로 답해 드려요.' }])
      return
    }
    setBusy(true)
    try {
      const reply = await api.quoteDrafts.sendChat(draftId, text, { clientMessageId: clientId })
      setEntries(prev => [...prev, { id: `b-${clientId}`, kind: 'bot', text: reply.reply }])
      onReply?.()
    } catch (caught) {
      setEntries(prev => [...prev, { id: `e-${clientId}`, kind: 'bot', text: errorMessage(caught, '질문에 답하지 못했어요. 잠시 후 다시 시도해주세요.') }])
    } finally { setBusy(false) }
  }
  return { entries, busy, send }
}
