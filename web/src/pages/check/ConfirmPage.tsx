import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { errorMessage } from '../../api'
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
  const [name, setName] = useState('받은 견적 점검')
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

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!id || !draft || !name.trim()) return
    setBusy(true); setError(''); setNeedLogin(false)
    try {
      const report = await checkV2.confirm(id, {
        expected_version: draft.version, name: name.trim(), memo,
        planned_purchase_at: plannedAt || null, target_amount: target ? Math.round(Number(target) * 10_000) : null,
      })
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
