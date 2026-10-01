import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import QuantityWarnings from '../components/QuantityWarnings'
import DateInput from '../components/DateInput'
import ProductThumb from '../components/ProductThumb'
import { api } from '../api'
import { usePlan } from '../state/PlanContext'
import { useToast } from '../state/ToastContext'
import { localDate, multiQtyItems, planTotal } from '../state/planModel'
import { useSetups } from '../state/SetupsContext'
import { useAuthUser } from '../state/authStore'
import type { SavedSetup } from '../state/types'
import { wonFmt } from '../utils/format'

// 추천 결과를 장바구니에 담아 확인하고, 이름·구매 예정일·목표 금액·메모를 정해 확정한다(서버가 리포트를 만든다).
// 확정은 로그인이 필요하다 — 로그인하면 이 구성을 그대로 이어서 확정할 수 있다.
export default function CartPage() {
  const { state, checkDraft, clearEditingSheet } = usePlan()
  const { addSetup, storageError, reload: reloadSetups } = useSetups()
  const { showToast } = useToast()
  const user = useAuthUser()
  const navigate = useNavigate()
  const plan = state.currentPlan

  const total = plan ? planTotal(plan) : 0
  const defaultName = [state.intent, plan?.budget ? Math.round(plan.budget / 10000).toLocaleString('ko-KR') + '만 원' : '', state.quiet].filter(Boolean).join(' · ')
  // "견적 수정하기"로 들어왔으면 원본 견적서의 이름·날짜·목표 금액·메모를 처음 값으로 쓰고, 덮어쓸지 새로 저장할지 묻는다.
  const editing = state.editingSheet && state.editingSheet.listId === plan?.id ? state.editingSheet : null
  const [saveMode, setSaveMode] = useState<'overwrite' | 'new' | null>(null)
  const [name, setName] = useState(editing?.name ?? (defaultName || '내 PC 견적'))
  const [date, setDate] = useState(editing?.date ?? '')   // ISO(yyyy-mm-dd). 칸이 비면 오늘로 확정한다
  const [dateOk, setDateOk] = useState(true)
  const [target, setTarget] = useState(editing ? String(editing.target) : total ? String(total) : '')
  const [memo, setMemo] = useState(editing?.memo ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!plan) {
    return (
      <PlannerShell>
        <div className="pl-page narrow">
          <h2 className="pl-h2">장바구니</h2>
          <div className="pl-empty">담은 구성이 없어요. 조건을 말하고 추천을 받은 뒤 “장바구니에 담기”를 눌러 주세요.</div>
          <div><Link className="pl-btn" style={{ textDecoration: 'none', display: 'inline-block' }} to="/start">추천 받으러 가기</Link></div>
        </div>
      </PlannerShell>
    )
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!plan) return
    const cleanName = name.trim()
    if (!cleanName) { setError('견적 이름을 입력해 주세요.'); return }
    if (editing && !saveMode) { setError('원본 견적서를 덮어쓸지, 새 견적서로 저장할지 먼저 골라 주세요.'); return }
    if (!dateOk) { setError('구매 예정일을 YY/MM/DD 형식으로 입력해 주세요. 예: 26/10/05'); return }
    const targetWon = target.trim() === '' ? total : Number(target.replace(/[^0-9]/g, ''))
    if (!Number.isSafeInteger(targetWon) || targetWon < 0) { setError('목표 금액은 숫자로 입력해 주세요.'); return }
    setError('')
    setBusy(true)
    const setup: SavedSetup = {
      id: plan.id, title: cleanName, date: date || localDate(), target: targetWon, memo: memo.trim(),
      savedAt: new Date().toISOString(), plan,
      desk: { deskUnlocked: state.deskUnlocked, deskWidth: state.deskWidth, deskDepth: state.deskDepth, deskHeight: state.deskHeight },
      checkDraft,
    }
    const ok = await addSetup(setup)
    if (ok && editing && saveMode === 'overwrite') {
      // 새 견적서로 확정한 뒤 원본을 지운다 — 덮어쓴 것과 같은 결과다(서버에 "덮어쓰기" API가 없어 두 단계로 한다).
      try {
        await api.lists.removeReport(editing.listId, editing.revisionNo)
        reloadSetups()   // addSetup 이 먼저 읽은 목록에는 아직 원본이 있어서 한 번 더 읽는다
      } catch {
        showToast('새 견적서는 저장했지만 원본을 지우지 못했어요. 저장한 견적에서 원본을 직접 지워 주세요.')
      }
    }
    setBusy(false)
    if (ok) { clearEditingSheet(); navigate('/report/' + plan.id) }
  }

  const budget = plan.budget
  // 서버는 예산을 넘는 구성의 확정을 거절한다. 미리 알려 주고 버튼을 막는다.
  const overBudget = budget !== null && total > budget
  return (
    <PlannerShell>
      <div className="pl-page" style={{ maxWidth: 1080 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="pl-eyebrow pl-mono">3 장바구니 · 확인하고 확정하면 리포트가 만들어져요</div>
          <h2 className="pl-h2" style={{ fontSize: 26 }}>장바구니</h2>
        </div>
        <div className="pl-cols">
          <div className="pl-card">
            <div className="pl-card-head" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontWeight: 700 }}>본체</span>
              <span className="pl-note">{plan.items.length}개</span>
              <span className="pl-mono" style={{ marginLeft: 'auto' }}>{wonFmt(total)}</span>
            </div>
            {plan.items.map(item => (
              <div className="pl-cart-row" key={item.id}>
                <ProductThumb imageUrl={item.imageUrl} partKey={item.key} name={item.name} />
                <span className="pl-part-cat cat">{item.type}</span>
                <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <b>{item.name}</b>
                    {item.qty != null && <span className="pl-qty">×{item.qty}</span>}
                  </div>
                  {item.fit && <span className="pl-note">이유 · {item.fit}</span>}
                </div>
                <span className="pl-mono" style={{ fontSize: 13 }}>{wonFmt(item.price)}</span>
              </div>
            ))}
          </div>

          <form className="pl-side" onSubmit={submit} noValidate>
            <div className="pl-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="pl-sum-row"><span style={{ color: '#92a4b2' }}>본체</span><span className="pl-mono">{wonFmt(total)}</span></div>
              <div style={{ height: 1, background: '#233744' }} />
              <div className="pl-sum-row"><b>합계</b><b className="pl-mono" style={{ fontSize: 22 }}>{wonFmt(total)}</b></div>
              {budget !== null && (
                <div className="pl-note">{total <= budget ? `예산 ${wonFmt(budget)} 중 ${wonFmt(budget - total)} 남아요` : `예산 ${wonFmt(budget)}을 ${wonFmt(total - budget)} 넘었어요`}</div>
              )}
            </div>
            <div className="pl-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {editing && (
                <fieldset className="pl-savemode">
                  <legend>이 견적서를 어떻게 저장할까요?</legend>
                  <label className={saveMode === 'overwrite' ? 'on' : ''}>
                    <input type="radio" name="savemode" checked={saveMode === 'overwrite'} onChange={() => setSaveMode('overwrite')} />
                    <span><b>원본 덮어쓰기</b><small>“{editing.name}”이 지금 구성으로 바뀌고, 원래 구성은 사라져요.</small></span>
                  </label>
                  <label className={saveMode === 'new' ? 'on' : ''}>
                    <input type="radio" name="savemode" checked={saveMode === 'new'} onChange={() => setSaveMode('new')} />
                    <span><b>새 견적서로 저장</b><small>원본은 그대로 남고, 새 견적서가 하나 더 생겨요.</small></span>
                  </label>
                </fieldset>
              )}
              <label className="pl-field">견적 이름
                <input value={name} maxLength={60} onChange={e => setName(e.target.value)} />
              </label>
              <div className="pl-two">
                <div className="pl-field">구매 예정일
                  <DateInput value={date} ariaLabel="구매 예정일" onChange={(iso, ok) => { setDate(iso); setDateOk(ok) }} />
                </div>
                <label className="pl-field">목표 금액(원)
                  <input inputMode="numeric" value={target} onChange={e => setTarget(e.target.value)} className="pl-mono" />
                </label>
              </div>
              <label className="pl-field">메모
                <textarea value={memo} maxLength={1000} placeholder="예: 세일 때 GPU 가격 다시 보기" onChange={e => setMemo(e.target.value)} />
              </label>
              {!user && (
                <div className="pl-alert warn" role="status">
                  확정하려면 로그인이 필요해요. 지금 구성은 그대로 남아 있어요.{' '}
                  <Link to="/login?next=/cart" style={{ color: 'inherit', fontWeight: 700 }}>로그인하기 →</Link>
                </div>
              )}
              <QuantityWarnings items={multiQtyItems(plan)} />
              {overBudget && (
                <div className="pl-alert bad" role="alert">
                  예산을 넘는 구성은 확정할 수 없어요. 부품이나 수량을 바꿔 예산 안으로 맞춰 주세요.{' '}
                  <Link to="/plan" style={{ color: 'inherit', fontWeight: 700 }}>결과에서 고치기 →</Link>
                </div>
              )}
              {(error || storageError) && <div className="pl-alert bad" role="alert">{error || storageError}</div>}
              <button type="submit" className="pl-btn" style={{ fontSize: 15 }} disabled={busy || !user || overBudget || (!!editing && !saveMode)}>{busy ? '확정하는 중…' : '확정하고 리포트 만들기'}</button>
            </div>
          </form>
        </div>
      </div>
    </PlannerShell>
  )
}
