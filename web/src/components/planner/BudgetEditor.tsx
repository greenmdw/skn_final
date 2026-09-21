import { useState, type FormEvent } from 'react'
import { usePlan } from '../../state/PlanContext'
import { parseBudget } from '../../state/planModel'
import { isMockApi } from '../../api'

export function BudgetEditor() {
  const { state, setBudget } = usePlan()
  const [value, setValue] = useState(state.budget === null ? '' : String(state.budget))
  const [syncedBudget, setSyncedBudget] = useState(state.budget)
  const [error, setError] = useState('')
  const [applied, setApplied] = useState(false)
  // 예산이 적용되어 바뀌면 입력칸을 정규화된 숫자로 맞춥니다(리마운트하지 않으므로 안내 문구가 유지됩니다).
  if (syncedBudget !== state.budget) {
    setSyncedBudget(state.budget)
    setValue(state.budget === null ? '' : String(state.budget))
  }
  function submit(e: FormEvent) {
    e.preventDefault()
    const amount = parseBudget(value)
    if (amount === undefined) { setApplied(false); setError('1~100,000,000원 사이의 원 단위 숫자를 입력해주세요.'); return }
    setBudget(amount)
    setError('')
    setApplied(true)
  }
  return <form className="budget-editor" onSubmit={submit}>
    <label htmlFor="planBudget">최대 예산 (원, 비우면 미설정)</label>
    <div><input id="planBudget" className="check-input" inputMode="numeric" value={value} onChange={e => setValue(e.target.value)} /><button className="ghost-btn" type="submit">예산 적용</button></div>
    <p role="status" className="setup-hint">{error || (applied ? '예산을 적용했습니다.' : isMockApi ? '초기 예산은 샘플 값입니다. 변경 후 예산 적용을 눌러주세요.' : '초기 예산은 기본값입니다. 변경 후 예산 적용을 눌러주세요.')}</p>
  </form>
}
