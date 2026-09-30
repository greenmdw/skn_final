import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import ListHistory from '../components/ListHistory'
import PlannerShell from '../components/PlannerShell'
import ProductThumb from '../components/ProductThumb'
import { planTotal } from '../state/planModel'
import { usePlan } from '../state/PlanContext'
import { useSetups } from '../state/SetupsContext'
import type { SavedSetup } from '../state/types'
import { wonFmt } from '../utils/format'

// 확정한 견적 리포트. 서버가 확정 시점에 저장한 부품·가격·이름·구매 예정일·목표 금액·메모를 보여 준다.
// 한 견적(목록)에 견적서가 여러 개면 ?v=번호 로 예전 견적서를 연다 — 저장 목록에는 최근 견적서만 있어 서버에서 따로 읽는다.
// 견적 수정하기는 서버가 확정본의 부품 구성을 새 견적서로 복사해 줄 때까지 숨긴다(docs/개발요청_백엔드_및_타팀.md 8번).
// 지금 서버는 조건만 복사해 다시 추천을 받게 되어, "저장 전 상태로 되돌아가 수정"이 되지 않는다.
const SHOW_REVISE = false

export default function ReportPage() {
  const { id } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const { savedSetups, loading, storageError } = useSetups()
  const { reviseSetup } = usePlan()
  const latest = savedSetups.find(item => item.id === id)
  const wanted = Number(search.get('v')) || null
  const [older, setOlder] = useState<SavedSetup | null>(null)
  const [olderError, setOlderError] = useState('')
  const needsOlder = Boolean(id && wanted && latest && wanted !== latest.revisionNo)

  useEffect(() => {
    setOlder(null)
    setOlderError('')
    if (!needsOlder || !id || !wanted) return
    let alive = true
    api.setups.report(id, wanted)
      .then(found => { if (alive) setOlder(found) })
      .catch(() => { if (alive) setOlderError('이 견적서를 불러오지 못했어요.') })
    return () => { alive = false }
  }, [id, wanted, needsOlder])

  const setup = needsOlder ? older : latest
  const reports = latest?.reports ?? []
  async function revise() {
    const screen = id ? await reviseSetup(id) : null
    if (screen) navigate(screen === 'plan' ? '/plan' : '/start')
  }

  if (!setup) {
    return (
      <PlannerShell>
        <div className="pl-page narrow">
          <h2 className="pl-h2">리포트</h2>
          {loading || (needsOlder && !olderError)
            ? <div className="pl-note">리포트를 불러오는 중이에요…</div>
            : <div className="pl-empty">{olderError || storageError || '이 리포트를 찾을 수 없어요. 로그인 상태를 확인하거나 저장한 견적에서 다시 열어 주세요.'}</div>}
        </div>
      </PlannerShell>
    )
  }

  const total = planTotal(setup.plan)
  const confirmed = setup.savedAt ? new Date(setup.savedAt).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : ''
  return (
    <PlannerShell>
      <div className="pl-page pl-report">
        <div className="pl-noprint" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, flexWrap: 'wrap' }}>
          {reports.length > 1 && reports.map(report => (
            <button type="button" key={report.revisionNo} onClick={() => navigate(`/report/${id}?v=${report.revisionNo}`)}
              className={'pl-pill' + (report.revisionNo === setup.revisionNo ? ' on' : '')} aria-pressed={report.revisionNo === setup.revisionNo}>
              견적서 {report.revisionNo}
            </button>
          ))}
          {SHOW_REVISE && setup.revisionNo === latest?.revisionNo && (
            <button type="button" className="pl-pill mint" onClick={() => void revise()} title="이 견적서의 조건으로 추천 결과 화면을 열어 수정해요. 확정하면 새 견적서로 저장돼요.">견적 수정하기</button>
          )}
          <button type="button" className="pl-pill" onClick={() => window.print()}>인쇄</button>
        </div>
        <article className="pl-paper">
          <div className="pl-paper-head">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="pl-mono" style={{ fontSize: 11, color: '#92a4b2' }}>TRUEFIT 견적 리포트</div>
              <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em' }}>{setup.title}</div>
              <div className="pl-note">
                {[confirmed && `${confirmed} 확정`, setup.date && `구매 예정 ${setup.date}`, `목표 금액 ${wonFmt(setup.target)}`].filter(Boolean).join(' · ')}
              </div>
              {setup.memo && <div style={{ fontSize: 13, lineHeight: 1.6 }}>메모 · {setup.memo}</div>}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="pl-note">합계</div>
              <div className="pl-mono" style={{ fontSize: 26, fontWeight: 600 }}>{wonFmt(total)}</div>
            </div>
          </div>

          <section>
            <div style={{ fontSize: 13, fontWeight: 700, paddingBottom: 8 }}>본체</div>
            {setup.plan.items.map(item => (
              <div className="pl-report-row" key={item.id}>
                <ProductThumb imageUrl={item.imageUrl} partKey={item.key} name={item.name} />
                <span className="cat" style={{ color: '#92a4b2' }}>{item.type}</span>
                <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <b>{item.name}</b>
                    {item.qty != null && <span className="pl-qty">×{item.qty}</span>}
                  </div>
                  {item.fit && <span className="pl-note">{item.fit}</span>}
                </div>
                <span className="pl-mono" style={{ textAlign: 'right' }}>{wonFmt(item.price)}</span>
                {item.purchaseUrl
                  ? <a href={item.purchaseUrl} target="_blank" rel="noopener noreferrer">판매처 보기 ↗</a>
                  : <span />}
              </div>
            ))}
          </section>

          <ListHistory listId={setup.id} revisionNo={setup.revisionNo} />
        </article>
      </div>
    </PlannerShell>
  )
}
