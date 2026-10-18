import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, errorMessage, type QuoteSavedComparison } from '../../api'
import { checkV2, type Analysis } from '../../api/checkV2'
import SavedComparisonPanel from '../../components/check/SavedComparisonPanel'
import SavedQuotePicker from '../../components/check/SavedQuotePicker'
import { useSetups } from '../../state/SetupsContext'
import { rememberCheckComparison } from '../../utils/checkSessions'
import { PRIORITY_LABEL, PURPOSE_LABEL, RESOLUTION_LABEL, wonText } from '../../utils/checkReview'
import CheckLayout, { CHECK2 } from './CheckLayout'
import { useDraft } from './useDraft'

interface Finding { key: string; tone: 'fail' | 'warn' | 'info'; title: string; detail: string; slot?: string; action?: 'replace' | 'lookup' }

/** 진단 결과를 우선순위(확정 비호환 → 용도 부족 → 확인 못 함 → 과한 부품) 순의 "짚어 볼 점"으로 바꾼다. 교체 후보는 여기 없고 ④에서 본다. */
function findings(analysis: Analysis): Finding[] {
  const out: Finding[] = []
  for (const check of analysis.compat.checks) {
    if (check.state === 'fail') out.push({ key: `c-${check.axis}`, tone: 'fail', title: `${check.label} — 호환 문제`, detail: check.detail, action: 'replace' })
  }
  for (const row of analysis.balance?.rows ?? []) {
    if (row.state === 'short') out.push({ key: `s-${row.part}-${row.aspect}`, tone: 'fail', title: `${row.part} — 용도 기준보다 부족`, detail: row.detail, slot: row.part, action: 'replace' })
  }
  for (const check of analysis.compat.checks) {
    if (check.state === 'unknown') out.push({ key: `u-${check.axis}`, tone: 'warn', title: `${check.label} — 확인 못 함`, detail: check.detail, action: 'lookup' })
  }
  for (const row of analysis.balance?.rows ?? []) {
    if (row.state === 'excess') out.push({ key: `e-${row.part}-${row.aspect}`, tone: 'info', title: `${row.part} — 기준보다 높아요`, detail: `${row.detail} 바꾸지 않아도 문제없어요.`, slot: row.part })
  }
  return out
}

const PURPOSES = Object.entries(PURPOSE_LABEL)
const RESOLUTIONS = Object.entries(RESOLUTION_LABEL)
const PRIORITIES = Object.entries(PRIORITY_LABEL)

/** ③ 종합 평가 — 현재 견적의 진단만 보인다. 교체 후보는 ④ 교체 구성에서 본다. */
export default function ReviewPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { draft, setDraft, reload } = useDraft(id)
  const [analysis, setAnalysis] = useState<Analysis | null>((location.state as { analysis?: Analysis } | null)?.analysis ?? null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)          // 이미 확정한 견적 — 저장된 결과만 보여 주고 고치지 못한다
  const [form, setForm] = useState<Record<string, unknown>>({})
  // 저장한 견적과 비교(재기획 6.9) — 사진 2장 "견적 비교"와는 다른 기능이다
  const { savedSetups, loading: setupsLoading, storageError } = useSetups()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickedId, setPickedId] = useState<string | null>(null)
  const [comparison, setComparison] = useState<QuoteSavedComparison | null>(null)
  const [differenceOnly, setDifferenceOnly] = useState(false)
  const [compareBusy, setCompareBusy] = useState(false)
  const [compareError, setCompareError] = useState('')

  async function analyze() {
    if (!id) return
    setBusy(true); setError('')
    try { setAnalysis(await checkV2.analyze(id)); await reload() } catch (caught) { setError(errorMessage(caught, '분석하지 못했습니다.')) } finally { setBusy(false) }
  }

  useEffect(() => {
    if (!id || analysis) return
    void (async () => {
      setBusy(true)
      try { setAnalysis(await checkV2.analyze(id)) } catch (caught) {
        // 이미 확정한 견적(리포트에서 들어온 경우)은 다시 분석하지 못한다 — 저장된 결과를 그대로 보여 준다.
        if (caught instanceof ApiError && caught.code === 'quote_already_confirmed') setConfirmed(true)
        try { setAnalysis(await checkV2.getReview(id)) } catch { setError(errorMessage(caught, '분석 결과를 불러오지 못했습니다.')) }
      } finally { setBusy(false) }
    })()
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function compareSaved() {
    const setup = savedSetups.find(item => item.id === pickedId)
    if (!id || !setup) return
    setCompareBusy(true); setCompareError('')
    try {
      const result = await api.quoteDrafts.compareSaved(id, setup.id, setup.revisionNo ?? undefined)
      rememberCheckComparison(id, result.comparisonId)
      setComparison(result); setPickerOpen(false)
    } catch (caught) { setCompareError(errorMessage(caught, '저장한 견적과 비교하지 못했습니다.')) } finally { setCompareBusy(false) }
  }

  async function saveConditions() {
    if (!id || !draft) return
    if (!form.purpose) { setError('용도를 골라 주세요.'); return }
    if (form.purpose === 'game' && !form.resolution) { setError('게임 용도는 해상도도 골라 주세요.'); return }
    setBusy(true); setError('')
    try {
      setDraft(await checkV2.patchConditions(id, draft.version, form))
      setEditing(false)
    } catch (caught) { setError(errorMessage(caught, '조건을 저장하지 못했습니다.')) } finally { setBusy(false) }
  }

  const items = analysis ? findings(analysis) : []
  const compat = analysis?.compat.summary ?? {}
  const balance = analysis?.balance
  const short = balance?.rows.filter(row => row.state === 'short').length ?? 0
  const conditions = (draft?.conditions ?? analysis?.input.conditions ?? {}) as Record<string, unknown>
  const tags = [PURPOSE_LABEL[String(conditions.purpose)], RESOLUTION_LABEL[String(conditions.resolution)], PRIORITY_LABEL[String(conditions.priority)]].filter(Boolean)
  const replaceCount = items.filter(item => item.action === 'replace').length
  const view = analysis?.price_view

  return (
    <CheckLayout current="review" draftId={id} analyzed={Boolean(analysis)} reachable={['parts', 'review', 'replace', 'confirm']} chat onChatAction={action => void (action === null || action.kind === 'reanalyze' ? analyze() : reload())}>
      <header className="c2-head">
        <h1>지금 견적은 이래요</h1>
        <p>
          평가 기준: {tags.length ? tags.join(' · ') : '용도를 정하지 않았어요'}{' '}
          {!confirmed && <button type="button" className="c2-link" onClick={() => { setForm({ ...conditions }); setEditing(!editing) }}>조건 바꾸기</button>}
        </p>
      </header>
      {error && <p className="c2-error" role="alert">{error}</p>}

      {editing && (
        <section className="c2-card">
          <div className="c2-form">
            <label>용도<select value={String(form.purpose ?? '')} onChange={e => setForm({ ...form, purpose: e.target.value || undefined })}>{PURPOSES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>해상도<select value={String(form.resolution ?? '')} onChange={e => setForm({ ...form, resolution: e.target.value || undefined })}><option value="">선택 안 함</option>{RESOLUTIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>우선순위<select value={String(form.priority ?? '')} onChange={e => setForm({ ...form, priority: e.target.value || undefined })}><option value="">선택 안 함</option>{PRIORITIES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          </div>
          <div className="c2-actions"><button type="button" className="c2-btn primary" disabled={busy} onClick={() => void saveConditions()}>저장</button></div>
        </section>
      )}

      {confirmed && (
        <section className="c2-card" role="status">
          <strong>이미 확정한 견적이에요.</strong> 저장된 점검 결과만 볼 수 있어요. 고치려면 <Link to={`/report/${id}`}>리포트</Link>에서 "이 구성으로 새 점검 시작"을 눌러 주세요.
        </section>
      )}

      {draft?.analysis_stale && !confirmed && (
        <section className="c2-card warn" role="status">
          <strong>조건이 바뀌어 이 결과는 오래됐어요.</strong>{' '}
          <button type="button" className="c2-btn primary" disabled={busy} onClick={() => void analyze()}>다시 분석하기</button>
        </section>
      )}

      {!analysis ? <p className="c2-note">{busy ? '분석하는 중…' : '분석 결과가 없어요.'}</p> : (
        <>
          <div className="c2-summary">
            <div className="c2-card"><small>호환</small><strong>통과 {compat.ok ?? 0} · 문제 {compat.fail ?? 0}</strong><span className="c2-sub">확인 못 함 {compat.unknown ?? 0}</span></div>
            <div className="c2-card"><small>용도 대비 균형</small>{balance?.available ? <strong>부족 {short}개</strong> : <strong>판단하지 않음</strong>}<span className="c2-sub">{balance?.available ? `기준보다 높은 부품 ${balance.rows.filter(r => r.state === 'excess').length}개` : (balance?.reason ?? '용도를 정하면 볼 수 있어요')}</span></div>
            <div className="c2-card"><small>{view?.label ?? '가격'}</small><strong>{!view ? '다시 분석하면 보여요' : view.mode === 'none' ? '가격 정보 없음' : wonText(view.quote_total ?? view.line_total)}</strong>{view?.note && <span className="c2-sub">{view.note}</span>}</div>
          </div>

          <section className="c2-card">
            <h2>짚어 볼 점</h2>
            {items.length === 0 ? <p className="c2-note">확인한 항목에서 문제는 없었어요.</p> : (
              <ul className="c2-findings">
                {items.map(item => (
                  <li key={item.key} className={`c2-finding ${item.tone}`}>
                    <div><strong>{item.title}</strong><div className="c2-sub">{item.detail}</div></div>
                    {item.action === 'replace' && <Link className="c2-btn" to={`${CHECK2}/${id}/replace${item.slot ? `?slot=${encodeURIComponent(item.slot)}` : ''}`}>이 부품 바꿔보기 →</Link>}
                    {item.action === 'lookup' && <Link className="c2-btn" to={`${CHECK2}/${id}/parts`}>정보 찾아보기</Link>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="c2-card">
            <details><summary>호환 검사 {analysis.compat.checks.length}개</summary>
              <ul>{analysis.compat.checks.map(check => <li key={check.axis} className="c2-sub">{check.label}: {check.state === 'ok' ? '통과' : check.state === 'fail' ? '문제' : '확인 못 함'} — {check.detail}</li>)}</ul>
            </details>
          </section>

          {comparison && (
            <SavedComparisonPanel comparison={comparison} differenceOnly={differenceOnly} onDifferenceOnly={setDifferenceOnly} onClose={() => setComparison(null)}
              answers={[]} openIds={new Set()} onToggle={() => undefined} onCollapseAll={() => undefined} pulse={0} />
          )}

          <div className="c2-actions end">
            <button type="button" className="c2-btn" onClick={() => { setCompareError(''); setPickerOpen(true) }}>저장한 견적과 비교</button>
            {!confirmed && <button type="button" className="c2-btn" disabled={busy} onClick={() => void analyze()}>다시 분석하기</button>}
            {!confirmed && <button type="button" className="c2-btn primary" onClick={() => navigate(`${CHECK2}/${id}/replace`)}>교체 구성으로{replaceCount ? `(추천 ${replaceCount}개)` : ''}</button>}
          </div>
        </>
      )}
      {pickerOpen && (
        <SavedQuotePicker setups={savedSetups} loading={setupsLoading} error={compareError || storageError || ''} selectedId={pickedId} busy={compareBusy}
          onSelect={setup => setPickedId(setup.id)} onConfirm={() => void compareSaved()} onClose={() => setPickerOpen(false)} />
      )}
    </CheckLayout>
  )
}
