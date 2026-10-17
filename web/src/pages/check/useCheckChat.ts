import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../../api'
import { sendChat, undoChatAction, type ChatAction } from '../../api/checkV2'
import type { ChatEntry } from '../../components/check/CheckChat'
import { newClientId } from '../../utils/checkReview'

const INTRO: ChatEntry = {
  id: 'intro', kind: 'bot',
  text: '질문에 답하고, 말로도 바꿀 수 있어요. 예: "GPU 교체 목록에 담아줘", "교체 예산 30만원으로 해줘", "다시 분석해줘".',
}
export const CHAT_HINT = '"~해줘"처럼 요청하면 바로 바꿔요. 물어보기만 하면 바꾸지 않아요.'

/** ② 이후 화면의 대화. 같은 서버 세션(초안 id = 대화 id)의 기록을 읽고 보낸다. 동작을 하면 onAction 으로 화면이 서버 상태를 다시 읽는다. */
export function useCheckChat(draftId: string | undefined, onAction?: (action: ChatAction | null) => void) {
  const [entries, setEntries] = useState<ChatEntry[]>([INTRO])
  const [busy, setBusy] = useState(false)
  const loaded = useRef<string | null>(null)
  const onActionRef = useRef(onAction)
  onActionRef.current = onAction

  useEffect(() => {
    if (!draftId || loaded.current === draftId) return
    loaded.current = draftId
    api.quoteDrafts.chatHistory(draftId).then(messages => {
      const restored: ChatEntry[] = messages.filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ id: m.id, kind: m.role === 'user' ? 'user' : 'bot', text: m.text }) as ChatEntry)
      if (restored.length) setEntries([INTRO, ...restored])
    }).catch(() => { /* 기록을 못 읽어도 새 대화로 시작한다 */ })
  }, [draftId])

  const undo = useCallback(async (entryId: string, action: ChatAction) => {
    if (!draftId || !action.undo) return
    try {
      await undoChatAction(draftId, action.undo)
      setEntries(prev => prev.map(e => (e.id === entryId && e.kind === 'action' ? { ...e, undone: true } : e)))
      onActionRef.current?.(null)
    } catch (caught) {
      setEntries(prev => [...prev, { id: `ue-${entryId}`, kind: 'bot', text: errorMessage(caught, '되돌리지 못했어요. 화면을 새로고침한 뒤 다시 시도해 주세요.') }])
    }
  }, [draftId])

  async function send(text: string) {
    const clientId = newClientId()
    setEntries(prev => [...prev, { id: `u-${clientId}`, kind: 'user', text }])
    if (!draftId) {
      setEntries(prev => [...prev, { id: `b-${clientId}`, kind: 'bot', text: '먼저 견적을 올려 주세요.' }])
      return
    }
    setBusy(true)
    try {
      const reply = await sendChat(draftId, text, clientId)
      if (reply.action) {
        const action = reply.action
        const id = `a-${clientId}`
        setEntries(prev => [...prev, { id, kind: 'action', text: reply.reply, label: action.label, onUndo: action.undo ? () => void undo(id, action) : undefined }])
      } else {
        setEntries(prev => [...prev, { id: `b-${clientId}`, kind: 'bot', text: reply.reply }])
      }
      onActionRef.current?.(reply.action)
    } catch (caught) {
      setEntries(prev => [...prev, { id: `e-${clientId}`, kind: 'bot', text: errorMessage(caught, '질문에 답하지 못했어요. 잠시 후 다시 시도해주세요.') }])
    } finally { setBusy(false) }
  }
  return { entries, busy, send }
}
