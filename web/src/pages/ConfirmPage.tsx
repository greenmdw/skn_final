import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { localDate, planTotal } from '../state/planModel'
import { MissingPage } from './MissingPage'
import { PageLoading } from '../components/layout/PageLoading'
import { wonFmt } from '../utils/format'
import { useSetups } from '../state/SetupsContext'
import { useToast } from '../state/ToastContext'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { isMockApi } from '../api'



export function ConfirmPage() {
  const { state } = usePlan()
  const { loading } = useSetups()
  if (!state.currentPlan) return <MissingPage title="확정할 구성이 없습니다." description="플래너에서 먼저 구성을 완성해주세요." />
  if (loading) return <PageLoading />
  return <ConfirmForm key={state.currentPlan.id} />
}

function ConfirmForm() {
  useDocumentTitle('리스트 확정')
  const navigate = useNavigate()
  const { addSetup, savedSetups, storageError, authRequired } = useSetups()
  const { state, checkDraft } = usePlan()
  const plan = state.currentPlan!
  const previous = savedSetups.find(setup => setup.id === plan.id)
  const { showToast } = useToast()

  const items = plan.items
  const total = planTotal(plan)
  const remaining = plan.budget === null ? null : plan.budget - total

  const [name, setName] = useState(previous?.title ?? (plan.mode === 'upgrade' ? '업그레이드 계획' : '컴퓨터 장바구니'))
  const [date, setDate] = useState(previous?.date ?? localDate())
  const [target, setTarget] = useState(String(previous?.target ?? total))
  const [memo, setMemo] = useState(previous?.memo ?? '')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const cleanName = name.trim()
    const targetNum = Number(target)
    if (!cleanName) { setError('리스트 이름을 입력해 주세요.'); return }
    if (!date) { setError('구매 예정일을 선택해 주세요.'); return }
    if (date < localDate()) { setError('구매 예정일은 오늘 또는 그 이후 날짜로 선택해 주세요.'); return }
    if (!Number.isSafeInteger(targetNum) || targetNum < 1 || targetNum > 100000000) { setError('목표 총액을 입력해 주세요.'); return }
    if (remaining !== null && remaining < 0) { setError('예산을 초과했습니다. 추천 결과에서 구성을 조정해 주세요.'); return }
    setError('')
    setSaving(true)
    const saved = await addSetup({ id: plan.id, title: cleanName, date, target: targetNum, memo,
      savedAt: new Date().toISOString(), plan,
      desk: { deskUnlocked: state.deskUnlocked, deskWidth: state.deskWidth, deskDepth: state.deskDepth, deskHeight: state.deskHeight }, checkDraft })
    setSaving(false)
    if (!saved) return
    showToast('"' + cleanName + '" 리스트가 확정되었습니다.')
    navigate('/plan/report/' + plan.id)
  }

  return (
    <section className="landing" aria-labelledby="confirmTitle">
      <div className="landing-inner check-inner">
        <p className="eyebrow">04 · SAVE YOUR PLAN</p>
        <h1 className="landing-title" id="confirmTitle">이 장바구니로<br />준비할까요?</h1>
        <p className="landing-desc">이름과 구매 예정일, 목표 가격을 정해 나만의 계획으로 저장해요.</p>
        <div className="check-grid">
          <div className="check-card">
            <form id="confirmForm" onSubmit={handleSubmit}>
              <label className="check-label" htmlFor="confirmName">리스트 이름 *</label>
              <input id="confirmName" className="check-input" maxLength={60} required value={name} onChange={e => setName(e.target.value)} />
              <label className="check-label" htmlFor="confirmDate">구매 예정일 *</label>
              <input id="confirmDate" type="date" className="check-input" required min={localDate()} value={date} onChange={e => setDate(e.target.value)} />
              <label className="check-label" htmlFor="confirmTarget">목표 총액 (원) *</label>
              <input id="confirmTarget" type="number" className="check-input" min={1} max={100000000} required value={target} onChange={e => setTarget(e.target.value)} />
              <label className="check-label" htmlFor="confirmMemo">메모</label>
              <textarea id="confirmMemo" className="check-textarea" maxLength={1000} placeholder="메모를 남겨보세요 (선택)" value={memo} onChange={e => setMemo(e.target.value)} />
              <p className="setup-hint">{isMockApi ? '이 브라우저에 임시 저장합니다. 다른 기기와 동기화되지 않습니다.' : '확정하면 계정에 저장됩니다. 로그인이 필요해요.'}</p>
              <p className="confirm-error" role="alert">{error || storageError}</p>
              {authRequired && !error && <button type="button" className="ghost-btn" onClick={() => navigate('/login?next=' + encodeURIComponent('/plan/confirm'))}>로그인하러 가기 →</button>}
              <div className="check-footrow">
                <button type="button" className="ghost-btn" onClick={() => navigate('/plan')}>← 다시 살펴보기</button>
                <button type="submit" className="analyze-btn check-submit" disabled={saving}>리스트 확정하기 →</button>
              </div>
            </form>
          </div>
          <div className="check-card">
            <div className="check-card-head"><h2>나의 장바구니</h2><span className="demo-badge check-select-badge">{items.length}</span></div>
            <div>
              {items.map((it) => (
                <div key={it.id} className="confirm-basket-row"><span>{it.type} · {it.name}</span><strong>{wonFmt(it.price)}</strong></div>
              ))}
            </div>
            <p className="setup-hint">예상 합계</p>
            <p className="confirm-basket-sum">{wonFmt(total)}</p>
            <p className="setup-hint">
              예산 {plan.budget === null ? '미설정' : wonFmt(plan.budget)}<br />
              {remaining === null ? '예산을 설정하지 않았습니다.' : remaining < 0 ? <span style={{ color: '#ff8a8a' }}>예산을 {wonFmt(-remaining)} 초과했어요.</span> : wonFmt(remaining) + ' 남아요.'}
            </p>
            <button type="submit" form="confirmForm" className="analyze-btn confirm-aside-btn" disabled={saving || (remaining !== null && remaining < 0) || !items.length}>
              이 리스트로 확정하기 →
            </button>
            <p className="setup-hint" style={{ marginTop: 10 }}>결제는 각 판매처에서 진행됩니다.</p>
          </div>
        </div>
      </div>
    </section>
  )
}
