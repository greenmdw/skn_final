import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, errorMessage, type QuoteSavedComparison } from '../../api'
import { checkV2 } from '../../api/checkV2'
import CheckLayout, { CHECK2 } from './CheckLayout'
import { useDraft } from './useDraft'

/** 서로 다른 두 견적을 기준별로 비교한다(종합 우열은 내지 않는다). 판정이 틀렸으면 "한 견적으로 분석하기"로 되돌린다. */
export default function ComparePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { draft, setDraft } = useDraft(id)
  const [result, setResult] = useState<QuoteSavedComparison | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id || !draft || result) return
    const [a, b] = draft.groups
    if (!a || !b) { setError('비교하려면 서로 다른 견적이 두 개 있어야 해요.'); return }
    api.quoteDrafts.compareQuotes(id, a.source_ids, b.source_ids).then(setResult).catch(caught => setError(errorMessage(caught, '두 견적을 비교하지 못했습니다.')))
  }, [id, draft, result])

  async function backToSingle() {
    if (!id || !draft) return
    try {
      setDraft(await checkV2.setSourceRelation(id, draft.version, 'single'))
      navigate(`${CHECK2}/${id}/parts`)
    } catch (caught) { setError(errorMessage(caught, '저장하지 못했습니다.')) }
  }

  return (
    <CheckLayout current="parts" draftId={id} reachable={['parts']} chat>
      <header className="c2-head">
        <h1>서로 다른 두 견적을 비교하고 있어요</h1>
        <p><button type="button" className="c2-link" onClick={() => void backToSingle()}>한 견적으로 분석하기</button> · <Link to={`${CHECK2}/${id}/parts`}>인식 확인으로</Link></p>
      </header>
      {error && <p className="c2-error" role="alert">{error}</p>}
      {!result && !error && <p className="c2-note">비교하는 중…</p>}
      {result && (
        <section className="c2-card">
          <table className="c2-table">
            <thead><tr><th>기준</th><th>{result.labels.received}</th><th>{result.labels.saved}</th></tr></thead>
            <tbody>
              {result.criteria.map(row => (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td className={row.better === 'a' ? 'better' : ''}>{row.aText}</td>
                  <td className={row.better === 'b' ? 'better' : ''}>{row.bText}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="c2-sub">기준별로만 비교해요. 어느 쪽이 더 낫다고 종합해서 말하지 않아요.</p>
        </section>
      )}
    </CheckLayout>
  )
}
