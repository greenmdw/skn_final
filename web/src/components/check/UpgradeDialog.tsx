import { useEffect, useRef, useState, type FormEvent } from 'react'

/** 지금 견적에서 일부 부품만 바꾸는 업그레이드 추천을 시작하기 전에 예산과 질문을 받는다. */
export default function UpgradeDialog({ initialBudget, initialQuestion, busy, onConfirm, onClose }: {
  initialBudget: number | null
  initialQuestion: string
  busy: boolean
  onConfirm: (budget: number, question: string) => void
  onClose: () => void
}) {
  const [budget, setBudget] = useState(initialBudget ? String(initialBudget) : '')
  const [question, setQuestion] = useState(initialQuestion)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    input.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  function submit(event: FormEvent) {
    event.preventDefault()
    const won = Number(budget.replace(/[^0-9]/g, ''))
    if (!Number.isSafeInteger(won) || won <= 0) { setError('업그레이드에 쓸 예산을 원 단위 숫자로 입력해주세요. 예: 800000'); return }
    if (!question.trim()) { setError('바꾸고 싶은 부품이나 궁금한 점을 적어주세요.'); return }
    setError('')
    onConfirm(won, question.trim())
  }

  return (
    <div className="ck-dialog-back" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose() }}>
      <form className="ck-dialog ck-edit-dialog" role="dialog" aria-modal="true" aria-label="업그레이드 추천 받기" onSubmit={submit}>
        <div className="ck-modal-head">
          <div><h2>업그레이드 추천 받기</h2><p className="ck-modal-intro">지금 견적의 부품을 그대로 두고, 예산 안에서 바꾸면 좋은 부품을 추천받아요.</p></div>
          <button type="button" className="ck-close" onClick={onClose} disabled={busy} aria-label="닫기">×</button>
        </div>
        <div className="ck-edit-body">
          <label>업그레이드 예산(원)<input ref={input} inputMode="numeric" value={budget} placeholder="예: 800000" onChange={event => setBudget(event.target.value)} /></label>
          <label>바꾸고 싶은 부품이나 질문<input value={question} maxLength={200} onChange={event => setQuestion(event.target.value)} /></label>
          <small>입력하지 않은 유지 부품 정보는 확인하지 못한 채 추천하니, 구매 전에 호환성을 다시 확인해 주세요.</small>
          {error && <div className="ck-form-error" role="alert">{error}</div>}
        </div>
        <div className="ck-modal-foot">
          <span className="ck-spacer" />
          <button type="button" className="ck-text-button" onClick={onClose} disabled={busy}>취소</button>
          <button type="submit" className="ck-primary" disabled={busy}>{busy ? '추천 받는 중…' : '추천 받기'}</button>
        </div>
      </form>
    </div>
  )
}
