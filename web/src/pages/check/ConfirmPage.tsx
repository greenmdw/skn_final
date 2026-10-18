import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, errorMessage } from '../../api'
import { checkV2, type ReplacementState } from '../../api/checkV2'
import { useSetups } from '../../state/SetupsContext'
import { signedWon } from '../../utils/checkReview'
import CheckLayout, { CHECK2 } from './CheckLayout'
import { useDraft } from './useDraft'

/** ⑤ 확정 — 이름·구매 예정일·목표 금액·메모. 로그인한 사용자만 확정할 수 있다(401 이면 안내). */
export default function ConfirmPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { draft, reload } = useDraft(id)
  const { reload: reloadSetups } = useSetups()
  const [state, setState] = useState<ReplacementState | null>(null)
  const [name, setName] = useState(() => { const now = new Date(); return `받은 견적 점검 (${now.getMonth() + 1}/${now.getDate()})` })      // 날짜를 붙여 여러 번 확정해도 구분되게
  const [plannedAt, setPlannedAt] = useState('')
  const [target, setTarget] = useState('')
  const [memo, setMemo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [needLogin, setNeedLogin] = useState(false)

  useEffect(() => {
    if (!id) return
    checkV2.replacements(id).then(setState).catch(caught => setError(errorMessage(caught, '교체 목록을 불러오지 못했습니다.')))
  }, [id])

  // 교체하지 않고 견적 그대로 두는 부품 중 카탈로그 제품으로 확인되지 않은 것 — 확정 전에 알린다
  const replacedSlots = new Set((state?.replacements ?? []).map(row => row.slot))
  const unconfirmedKept = (draft?.items ?? []).filter(item => item.selected_for_analysis && item.match_status !== 'confirmed' && !replacedSlots.has(item.category)).length

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!id || !draft || !name.trim()) return
    if (unconfirmedKept > 0 && !window.confirm(`확인하지 못한 부품 ${unconfirmedKept}개가 있어요. 그 부품은 견적에 적힌 대로만 저장돼요. 그대로 확정할까요?`)) return
    setBusy(true); setError(''); setNeedLogin(false)
    try {
      const body = {
        expected_version: draft.version, name: name.trim(), memo,
        planned_purchase_at: plannedAt || null, target_amount: target ? Math.round(Number(target) * 10_000) : null,
      }
      let report
      try {
        report = await checkV2.confirm(id, body)
      } catch (caught) {
        // 교체 예산을 넘은 채로 확정하려면 한 번 더 확인받는다(담을 때는 경고만 했다)
        if (!(caught instanceof ApiError && caught.code === 'over_budget_unconfirmed') || !window.confirm('교체 목록이 교체 예산을 넘었어요. 그래도 확정할까요?')) throw caught
        report = await checkV2.confirm(id, { ...body, over_budget_ack: true })
      }
      reloadSetups()   // 저장 목록에 새 견적서를 넣어야 리포트 화면이 찾는다
      navigate(`/report/${report.list_id}`,{ state: { plannerMode: 'check' } })
    } catch (caught) {
      const code = (caught as { code?: string }).code
      if (code === 'AUTH_REQUIRED') setNeedLogin(true)
      else setError(errorMessage(caught, '확정하지 못했습니다.'))
      void reload()
    } finally { setBusy(false) }
  }

  return (
    <CheckLayout current="confirm" draftId={id} analyzed reachable={['parts', 'review', 'replace', 'confirm']} chat>
      <header className="c2-head"><h1>이 구성으로 확정할까요?</h1><p>교체한 부품은 바꾼 제품으로, 나머지는 견적에 적힌 그대로 리포트에 저장돼요.</p></header>
      {error && <p className="c2-error" role="alert">{error}</p>}
      {needLogin && <p className="c2-error" role="alert">확정하려면 로그인이 필요해요. 로그인한 뒤 이 화면에서 다시 눌러 주세요.</p>}
      {draft?.analysis_stale && <section className="c2-card warn" role="status">조건이 바뀌어 분석이 오래됐어요. <Link to={`${CHECK2}/${id}/review`}>다시 분석</Link>한 뒤 확정해 주세요.</section>}
      {unconfirmedKept > 0 && <section className="c2-card warn" role="status">확인하지 못한 부품 {unconfirmedKept}개는 견적에 적힌 대로만 저장돼요. 확정 전에 <Link to={`${CHECK2}/${id}/parts`}>인식 확인</Link>에서 정보를 찾을 수 있어요.</section>}
      <section className="c2-card">
        <h2>교체 {state?.replacements.length ?? 0}개</h2>
        {state && state.replacements.length > 0 ? (
          <ul>{state.replacements.map(row => <li key={row.slot} className="c2-sub">{row.slot}: {row.from.name ?? '현재 부품'} → <strong>{row.candidate.name}</strong>{row.price_delta != null && ` (${signedWon(row.price_delta)})`}</li>)}</ul>
        ) : <p className="c2-note">교체 없이 견적 그대로 저장돼요.</p>}
      </section>
      <form className="c2-card c2-form" onSubmit={e => void submit(e)}>
        <label>견적서 이름<input value={name} maxLength={60} onChange={e => setName(e.target.value)} required /></label>
        <label>구매 예정일<input type="date" value={plannedAt} onChange={e => setPlannedAt(e.target.value)} /></label>
        <label>목표 금액(만 원)<input type="number" min={0} step={5} value={target} onChange={e => setTarget(e.target.value)} /></label>
        <label>메모<textarea value={memo} maxLength={1000} onChange={e => setMemo(e.target.value)} /></label>
        <div className="c2-actions end">
          <Link className="c2-btn" to={`${CHECK2}/${id}/replace`}>교체 구성으로</Link>
          <button type="submit" className="c2-btn primary" disabled={busy || !draft || draft.analysis_stale}>확정하고 리포트 만들기</button>
        </div>
      </form>
    </CheckLayout>
  )
}
