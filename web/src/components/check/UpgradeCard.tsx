import { useEffect, useRef, useState, type FormEvent } from 'react'

const BUDGET_CHIPS = [500_000, 800_000, 1_000_000, 1_500_000]

/** 대화창 안에서 업그레이드 추천에 쓸 예산과 질문을 받는 카드. */
export default function UpgradeCard({ initialBudget, initialQuestion, busy, onSubmit, onCancel }: {
  initialBudget: number | null
  initialQuestion: string
  busy: boolean
  onSubmit: (budget: number, question: string) => void
  onCancel: () => void
}) {
  const [budget, setBudget] = useState(initialBudget ? String(initialBudget) : '')
  const [question, setQuestion] = useState(initialQuestion)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { input.current?.focus() }, [])

  function submit(event: FormEvent) {
    event.preventDefault()
    const won = Number(budget.replace(/[^0-9]/g, ''))
    if (!Number.isSafeInteger(won) || won <= 0) { setError('업그레이드에 쓸 예산을 원 단위 숫자로 입력해주세요. 예: 800000'); return }
    if (!question.trim()) { setError('바꾸고 싶은 부품이나 궁금한 점을 적어주세요.'); return }
    setError('')
    onSubmit(won, question.trim())
  }

  return (
    <form className="ck-upgrade-card" onSubmit={submit} aria-label="업그레이드 추천 받기">
      <b>업그레이드 추천 받기</b>
      <p>지금 견적의 부품을 그대로 두고, 예산 안에서 바꾸면 좋은 부품을 추천받아요.</p>
      <label>업그레이드 예산(원)
        <input ref={input} inputMode="numeric" value={budget} placeholder="예: 800000" disabled={busy} onChange={event => setBudget(event.target.value)} />
      </label>
      <div className="ck-upgrade-chips">
        {BUDGET_CHIPS.map(amount => (
          <button type="button" key={amount} disabled={busy} className={Number(budget.replace(/[^0-9]/g, '')) === amount ? 'on' : ''} onClick={() => setBudget(String(amount))}>{amount / 10_000}만 원</button>
        ))}
      </div>
      <label>바꾸고 싶은 부품이나 질문
        <input value={question} maxLength={200} disabled={busy} onChange={event => setQuestion(event.target.value)} />
      </label>
      <small>입력하지 않은 유지 부품 정보는 확인하지 못한 채 추천하니, 구매 전에 호환성을 다시 확인해 주세요.</small>
      {error && <div className="ck-form-error" role="alert">{error}</div>}
      <div className="ck-upgrade-actions">
        <button type="button" className="ck-text-button" onClick={onCancel} disabled={busy}>취소</button>
        <button type="submit" className="ck-primary" disabled={busy}>{busy ? '추천 받는 중…' : '추천 받기'}</button>
      </div>
    </form>
  )
}
