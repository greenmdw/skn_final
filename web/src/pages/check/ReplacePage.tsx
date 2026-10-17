import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { errorMessage } from '../../api'
import { checkV2, type Candidate, type ReplacementState, type Target, type Targets } from '../../api/checkV2'
import { signedWon, wonText } from '../../utils/checkReview'
import CheckLayout, { CHECK2 } from './CheckLayout'

const WARNING_TEXT: Record<string, string> = {
  grade_lower: '현재 부품보다 성능이 낮아요', new_incompatible: '새 호환 문제가 생겨요', over_budget: '교체 예산을 넘어요',
}

function CandidateRow({ cand, picked, busy, onPick }: { cand: Candidate; picked: boolean; busy: boolean; onPick: () => void }) {
  return (
    <li className="c2-cand">
      <div>
        <strong>{cand.name}</strong>
        <div className="c2-sub">
          {cand.price != null ? wonText(cand.price) : '가격 정보 없음'}
          {cand.price_delta != null && ` (${signedWon(cand.price_delta)})`}
          {cand.grade_label && cand.grade_change != null && ` · ${cand.grade_label} ${cand.grade_change > 0 ? '+' : ''}${cand.grade_change}`}
        </div>
        {cand.resolves.map(text => <div key={text} className="c2-sub">✓ {text}</div>)}
        {!cand.resolves_all && <div className="c2-sub">일부 문제만 풀어 줘요.</div>}
      </div>
      <button type="button" className={`c2-btn${picked ? '' : ' primary'}`} disabled={busy || picked || !cand.product_id} onClick={onPick}>{picked ? '담았어요' : '교체 목록에 담기'}</button>
    </li>
  )
}

/** ④ 교체 구성 — 먼저 바꿀 부품과 후보, 담은 교체 목록, 교체 후 점검 변화. */
export default function ReplacePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const focus = search.get('slot')
  const [targets, setTargets] = useState<Targets | null>(null)
  const [state, setState] = useState<ReplacementState | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    try {
      const [nextTargets, nextState] = await Promise.all([checkV2.targets(id), checkV2.replacements(id)])
      setTargets(nextTargets); setState(nextState); setError('')
    } catch (caught) { setError(errorMessage(caught, '교체 추천을 불러오지 못했습니다.')) }
  }, [id])
  useEffect(() => { void load() }, [load])

  async function change(run: (version: number) => Promise<ReplacementState>) {
    if (!state) return
    setBusy(true); setError('')
    try { setState(await run(state.draft_version)) } catch (caught) {
      setError(errorMessage(caught, '교체 목록을 바꾸지 못했습니다.'))
      void load()
    } finally { setBusy(false) }
  }

  const picked = new Map((state?.replacements ?? []).map(row => [row.slot, row.candidate.product_id]))
  const ordered: Target[] = [...(targets?.targets ?? [])].sort((a, b) => {
    if (focus) { if (a.slot === focus) return -1; if (b.slot === focus) return 1 }
    const order = { replace: 0, verify: 1, keep: 2 } as const
    return order[a.kind] - order[b.kind] || (a.rank ?? 99) - (b.rank ?? 99)
  })
  const stale = targets?.analysis_stale || state?.analysis_stale

  return (
    <CheckLayout current="replace" draftId={id} analyzed reachable={['parts', 'review', 'replace', 'confirm']} chat onChatReply={() => void load()}>
      <header className="c2-head">
        <h1>먼저 바꿀 부품</h1>
        <p>종합 평가의 근거로 순서를 정했어요. 담지 않은 부품은 견적 그대로 확정돼요. <Link to={`${CHECK2}/${id}/review`}>종합 평가 보기</Link></p>
      </header>
      {error && <p className="c2-error" role="alert">{error}</p>}
      {stale && <section className="c2-card warn" role="status"><strong>조건이 바뀌어 추천이 오래됐어요.</strong> 종합 평가에서 다시 분석해 주세요. <Link to={`${CHECK2}/${id}/review`}>종합 평가로</Link></section>}
      {!targets && !error && <p className="c2-note">불러오는 중…</p>}

      {ordered.map(target => (
        <section key={target.slot} className={`c2-card target ${target.kind}`} id={`slot-${target.slot}`}>
          <div className="c2-target-head">
            <h2>{target.kind === 'replace' && target.rank ? `${target.rank}. ` : ''}{target.slot}</h2>
            <span className={`c2-badge ${target.kind === 'replace' ? 'warn' : target.kind === 'verify' ? 'warn' : 'ok'}`}>{target.kind === 'replace' ? '바꾸기 추천' : target.kind === 'verify' ? '먼저 확인' : '유지'}</span>
          </div>
          <div className="c2-sub">현재: {target.current_name ?? '알 수 없음'}</div>
          {target.reasons.map(reason => <div key={reason.text} className="c2-sub">· {reason.text}</div>)}
          {target.note && <div className="c2-sub">{target.note}</div>}
          {target.kind === 'verify' && <Link className="c2-btn" to={`${CHECK2}/${id}/parts`}>인식 확인으로 돌아가기</Link>}
          {target.kind === 'replace' && (target.candidates.length === 0
            ? <p className="c2-note">조건에 맞는 후보가 없어요.</p>
            : <ul className="c2-cands">{target.candidates.map(cand => (
              <CandidateRow key={cand.product_id ?? cand.name} cand={cand} busy={busy} picked={picked.get(target.slot) === cand.product_id}
                onPick={() => cand.product_id && void change(version => checkV2.putReplacement(id!, version, target.slot, cand.product_id!))} />
            ))}</ul>)}
          {picked.has(target.slot) && (
            <button type="button" className="c2-link" disabled={busy} onClick={() => void change(version => checkV2.removeReplacement(id!, version, target.slot))}>되돌리기</button>
          )}
        </section>
      ))}

      {state && (
        <section className="c2-card" aria-label="교체 목록">
          <h2>교체 목록 {state.replacements.length}개</h2>
          {state.replacements.length === 0 ? <p className="c2-note">교체 목록이 비어 있어요. 이대로 확정하면 견적 그대로 저장돼요.</p> : (
            <ul>
              {state.replacements.map(row => (
                <li key={row.slot} className="c2-sub">
                  {row.slot}: {row.from.name ?? '현재 부품'} → <strong>{row.candidate.name}</strong>{' '}
                  ({row.price_delta != null ? signedWon(row.price_delta) : '가격 차이를 알 수 없어요'})
                  {row.warnings.map(w => <span key={w} className="c2-chip warn">{WARNING_TEXT[w] ?? w}</span>)}
                </li>
              ))}
            </ul>
          )}
          <p className="c2-sub">
            호환 문제 {state.compat.before.fail ?? 0} → {state.compat.after.fail ?? 0}개
            {state.compat.new_issues.length > 0 && ` · 새로 생기는 문제 ${state.compat.new_issues.length}개`}
          </p>
          <p className="c2-sub">
            가격 차이 합계: {state.price.unpriced_slots.length > 0 ? `확인된 부품 기준 ${signedWon(state.price.delta_total)} (가격 정보 없는 ${state.price.unpriced_slots.join('·')} 제외)` : signedWon(state.price.delta_total)}
            {state.price.over_budget && ' · 교체 예산을 넘었어요(확정은 할 수 있어요)'}
          </p>
        </section>
      )}

      <div className="c2-actions end">
        <button type="button" className="c2-btn" onClick={() => navigate(`${CHECK2}/${id}/review`)}>종합 평가로</button>
        <button type="button" className="c2-btn primary" disabled={!state} onClick={() => navigate(`${CHECK2}/${id}/confirm`)}>{state && state.replacements.length === 0 ? '그대로 확정하기' : '확정으로 가기'}</button>
      </div>
    </CheckLayout>
  )
}
