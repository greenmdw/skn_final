import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import BudgetDonut from '../components/BudgetDonut'
import PlannerShell from '../components/PlannerShell'
import ProductThumb from '../components/ProductThumb'
import { usePlan } from '../state/PlanContext'
import type { CompatCheck, PlanItem } from '../state/types'
import { wonFmt } from '../utils/format'

const CHECK_LABEL: Record<CompatCheck['state'], string> = { ok: '통과', unknown: '확인 못 함', fail: '문제', skipped: '해당 없음' }

// 상태별 개수 표시. 0건인 상태는 숨기고, 서버가 준 모든 상태(통과·문제·확인 못 함·해당 없음)를 빠짐없이 보여 준다.
const SUMMARY_ORDER: { state: CompatCheck['state']; cls: string }[] = [
  { state: 'ok', cls: '' }, { state: 'fail', cls: ' fail' }, { state: 'unknown', cls: ' unk' }, { state: 'skipped', cls: ' skip' },
]
function CheckSummary({ checks }: { checks: CompatCheck[] }) {
  return (
    <>
      {SUMMARY_ORDER.map(({ state, cls }) => {
        const n = checks.filter(check => check.state === state).length
        return n > 0 ? <span key={state} className={'pl-legend' + cls}><i />{CHECK_LABEL[state]} {n}</span> : null
      })}
    </>
  )
}

function PartRow({ item, open, onToggle }: { item: PlanItem; open: boolean; onToggle: () => void }) {
  return (
    <div className="pl-part">
      <button type="button" className="pl-part-row" onClick={onToggle} aria-expanded={open}>
        <ProductThumb imageUrl={item.imageUrl} partKey={item.key} name={item.name} />
        <span className="pl-part-cat">{item.type}</span>
        <span className="pl-part-name">
          {item.name}
          {item.qty != null && <span className="pl-qty" aria-label={`수량 ${item.qty}개`}>×{item.qty}</span>}
          {item.actionClass !== '' && <span className="pl-tag">{item.action}</span>}
        </span>
        <span className="pl-price">
          <span className="pl-mono">{wonFmt(item.price)}</span>
          {item.qty != null && item.qty > 1 && item.unitPrice != null && <span className="pl-unit">개당 {wonFmt(item.unitPrice)} × {item.qty}</span>}
        </span>
        <span className="chev" style={{ color: '#92a4b2', fontSize: 12 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="pl-part-detail">
          <div className="pl-box"><h4>AI 추천 이유</h4><p>{item.fit || '추천 이유를 준비하지 못했어요.'}</p></div>
          <div className="pl-box"><h4>주요 스펙</h4><p>{item.meta}</p><p style={{ color: '#92a4b2' }}>{item.source}{item.score ? ' · ' + item.score : ''}</p></div>
          <div className="pl-box">
            <h4>구매 전 확인</h4>
            {item.checks && item.checks.length > 0
              ? <ul>{item.checks.map(text => <li key={text}>{text}</li>)}</ul>
              : <p style={{ color: '#92a4b2' }}>서버가 준 확인 항목이 없어요.</p>}
          </div>
          <div className="pl-box">
            <h4>리뷰</h4>
            {item.rating !== '-' || item.reviews !== '없음'
              ? <p><b style={{ fontSize: 20 }}>★ {item.rating}</b> <span style={{ marginLeft: 8 }}>리뷰 {item.reviews}</span></p>
              : <p style={{ color: '#92a4b2' }}>이 제품의 리뷰 관측이 아직 없어요.</p>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function PlanPage() {
  const { state, retryWithPerformance, refreshPlan } = usePlan()
  const navigate = useNavigate()
  const plan = state.currentPlan
  const [openId, setOpenId] = useState<string | null>(null)
  const [checksOpen, setChecksOpen] = useState(false)

  // 수량 정보가 없는 옛 구성(예전에 저장된 것)이면 서버의 최신 결과로 한 번 다시 읽는다.
  const stale = !!plan && plan.items.some(item => item.qty == null)
  useEffect(() => { if (stale) refreshPlan() }, [stale, refreshPlan])
  useEffect(() => { if (!plan && state.stage !== 3) navigate('/start', { replace: true }) }, [plan, state.stage, navigate])
  if (!plan) return <PlannerShell chatTitle="결과 대화" placeholder="예: CPU를 더 싼 걸로 바꿔줘"><div className="pl-page"><div className="pl-note">추천 결과를 불러오는 중이에요…</div></div></PlannerShell>

  const budget = plan.budget
  const summary = [state.intent, budget !== null ? Math.round(budget / 10000).toLocaleString('ko-KR') + '만 원' : '', state.quiet].filter(Boolean).join(' · ')
  const checks = plan.compatChecks ?? []

  return (
    <PlannerShell chatTitle="결과 대화" placeholder="예: CPU를 더 싼 걸로 바꿔줘">
      <div className="pl-page">
        <div className="pl-hero">
          <div className="pl-hero-text">
            <div className="pl-eyebrow pl-mono">새 컴퓨터 본체 · 2 추천 결과</div>
            <h2 className="pl-h2" style={{ fontSize: 26 }}>{summary || '추천 결과'}</h2>
            {plan.contribution && (
              <div className="pl-contrib">
                {plan.contribution.map(share => <span className="pl-chip" key={share.axis}><span className="k">{share.axis}</span>{share.percent}%</span>)}
              </div>
            )}
          </div>
          <BudgetDonut parts={plan.items} budget={budget} />
        </div>

        {plan.budgetNotice && (
          <div className="pl-alert" role="status">
            {plan.budgetNotice.message}
            <div style={{ marginTop: 8 }}><button type="button" className="pl-btn ghost" style={{ padding: '8px 14px', fontSize: 13 }} onClick={retryWithPerformance}>성능 우선으로 다시 추천받기</button></div>
          </div>
        )}
        {plan.compat && plan.compat.problems.length > 0 && (
          <div className="pl-alert bad" role="alert"><b>확정된 호환 문제</b><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{plan.compat.problems.map(text => <li key={text}>{text}</li>)}</ul></div>
        )}

        <div className="pl-card">
          {plan.items.map(item => (
            <PartRow key={item.id} item={item} open={openId === item.id} onToggle={() => setOpenId(openId === item.id ? null : item.id)} />
          ))}
          {checks.length > 0 && (
            <div className="pl-checks">
              <button type="button" className="pl-checks-toggle" aria-expanded={checksOpen} aria-controls="pl-checks-body" onClick={() => setChecksOpen(open => !open)}>
                <span style={{ fontWeight: 600 }}>호환 검사 결과 <span className="pl-mono" style={{ color: '#92a4b2', fontWeight: 400 }}>{checks.length}개</span></span>
                <span className="pl-checks-sum">
                  <CheckSummary checks={checks} />
                </span>
                <span className="chev" aria-hidden="true">{checksOpen ? '▲' : '▼'}</span>
              </button>
              {checksOpen && (
                <div className="pl-checks-grid" id="pl-checks-body">
                  {checks.map(check => (
                    <div className="pl-check" key={check.axis}>
                      <div className="pl-check-head">
                        <span className={'st ' + check.state}>{CHECK_LABEL[check.state]}</span>
                        <b>{check.label}</b>
                      </div>
                      <div className="pl-check-detail">{check.detail}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="pl-bridge">
          <div className="txt">
            <div className="t">주변기기도 맞출까요?</div>
            <div style={{ fontSize: 13, marginTop: 4 }}>모니터·키보드·마우스·스피커를 이어서 고를 수 있어요.</div>
          </div>
          <Link to="/screen/peri">주변기기 이어서 짜기</Link>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <Link className="pl-btn ghost" style={{ textDecoration: 'none' }} to="/start">조건 바꾸기</Link>
        </div>
      </div>
    </PlannerShell>
  )
}
