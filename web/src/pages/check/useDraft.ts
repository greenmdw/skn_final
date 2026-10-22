import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from '../../api'
import { checkV2, type Draft } from '../../api/checkV2'

/** 서버 초안이 기준이다 — 새로고침·재진입해도 이 훅이 서버에서 다시 읽는다. */
export function useDraft(draftId: string | undefined) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(Boolean(draftId))

  const reload = useCallback(async () => {
    if (!draftId) return null
    try {
      const next = await checkV2.getDraft(draftId)
      setDraft(next); setError('')
      return next
    } catch (caught) {
      setError(errorMessage(caught, '견적을 불러오지 못했습니다.'))
      return null
    } finally { setLoading(false) }
  }, [draftId])

  useEffect(() => { void reload() }, [reload])
  return { draft, setDraft, error, loading, reload }
}
