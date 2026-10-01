import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import AlternativesDialog from '../components/AlternativesDialog'
import BudgetDonut from '../components/BudgetDonut'
import PlannerShell from '../components/PlannerShell'
import QuantityWarnings from '../components/QuantityWarnings'
import ProductThumb from '../components/ProductThumb'
import { usePlan } from '../state/PlanContext'
import { multiQtyItems } from '../state/planModel'
import { useToast } from '../state/ToastContext'
import type { CompatCheck, PartKey, PlanItem } from '../state/types'
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

// 빼면 완성된 PC가 되지 않는 부품 — 뺄 때 한 번 더 확인한다. 쿨러·GPU 같은 나머지는 바로 뺀다.
const REQUIRED_PARTS: PartKey[] = ['cpu', 'board', 'ram', 'ssd', 'psu', 'case']

/** 목적격 조사: 받침이 있으면 "을", 없으면 "를" (RAM·SSD처럼 영문은 읽는 소리 기준) */
function eulReul(word: string): string {
  const last = word.charAt(word.length - 1)
  const code = last.charCodeAt(0)
  const batchim = code >= 0xac00 && code <= 0xd7a3 ? (code - 0xac00) % 28 !== 0 : 'LMNRlmnr013678'.includes(last)
  return word + (batchim ? '을' : '를')
}

function PartRow({ item, open, busy, excluded, confirming, lastOne, onToggle, onCompare, onQty, onRemove, onRestore, onConfirmRemove, onCancelRemove }: {
  item: PlanItem; open: boolean; busy: boolean; excluded: boolean
  /** 꼭 필요한 부품을 빼려 해서 확인 문구를 보이는 중 */
  confirming: boolean
  /** 남은 부품이 이것 하나뿐이라 뺄 수 없다 */
  lastOne: boolean
  onToggle: () => void; onCompare: () => void; onQty: (qty: number) => void
  onRemove: () => void; onRestore: () => void; onConfirmRemove: () => void; onCancelRemove: () => void
}) {
  return (
    <div className={'pl-part' + (excluded ? ' out' : '')}>
      <button type="button" className="pl-part-row" onClick={onToggle} aria-expanded={open} disabled={excluded}>
        <ProductThumb imageUrl={item.imageUrl} partKey={item.key} name={item.name} />
        <span className="pl-part-cat">{item.type}</span>
        <span className="pl-part-name">
          {item.name}
          {item.qty != null && item.qty > 1 && <span className="pl-qty" aria-label={`수량 ${item.qty}개`}>×{item.qty}</span>}
          {excluded && <span className="pl-out-badge">제외됨</span>}
        </span>
        <span className="pl-price">
          <span className="pl-mono">{wonFmt(item.price)}</span>
          {item.qty != null && item.qty > 1 && item.unitPrice != null && <span className="pl-unit">개당 {wonFmt(item.unitPrice)} × {item.qty}</span>}
        </span>
        <span className="chev" style={{ color: '#92a4b2', fontSize: 12 }}>{excluded ? '' : open ? '▲' : '▼'}</span>
      </button>
      {excluded && (
        <div className="pl-out-foot">
          <button type="button" className="pl-restore" disabled={busy} onClick={onRestore}>다시 넣기</button>
        </div>
      )}
      {open && !excluded && (
        <div className="pl-part-detail">
          <div className="pl-box"><h4>AI 추천 이유</h4><p>{item.fit || '추천 이유를 준비하지 못했어요.'}</p></div>
          <div className="pl-box"><h4>주요 스펙</h4><p>{item.meta}</p><p style={{ color: '#92a4b2' }}>{item.source}{item.score ? ' · ' + item.score : ''}</p></div>
          <div className="pl-box">
            <h4>구매 전 확인</h4>
            {item.checks && item.checks.length > 0
              ? <ul>{item.checks.map(text => <li key={text}>{text}</li>)}</ul>
              : <p style={{ color: '#92a4b2' }}>서버가 준 확인 항목이 없어요.</p>}
          </div>
          <div className="pl-box pl-controls">
            <h4>수량 {busy && <span className="pl-busy" role="status">반영 중…</span>}</h4>
            <div className="pl-ctrl-row">
              {item.qty != null && (
                <div className="pl-stepper">
                  <button type="button" aria-label="수량 줄이기" disabled={busy || item.qty <= 1} onClick={() => onQty(item.qty! - 1)}>−</button>
                  <b className="pl-mono" aria-live="polite">{item.qty}</b>
                  <button type="button" aria-label="수량 늘리기" disabled={busy || item.qty >= 99} onClick={() => onQty(item.qty! + 1)}>+</button>
                  <span className="pl-note">개</span>
                </div>
              )}
              <button type="button" className="pl-remove" disabled={busy} onClick={onRemove}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" /></svg>
                이 부품 빼기
              </button>
            </div>
            {confirming && (
              <div className="pl-confirm" role="alert">
                {lastOne
                  ? <>마지막 부품은 뺄 수 없어요. 최소 한 개는 있어야 확정할 수 있어요.<div className="btns"><button type="button" onClick={onCancelRemove}>알겠어요</button></div></>
                  : <>{eulReul(item.type)} 빼면 완성된 PC가 되지 않아요. 그래도 뺄까요?<div className="btns"><button type="button" className="go" onClick={onConfirmRemove}>그래도 빼기</button><button type="button" onClick={onCancelRemove}>취소</button></div></>}
              </div>
            )}
          </div>
          <div className="pl-box">
            <h4>리뷰</h4>
            {item.rating !== '-' || item.reviews !== '없음'
              ? <p><b style={{ fontSize: 20 }}>★ {item.rating}</b> <span style={{ marginLeft: 8 }}>리뷰 {item.reviews}</span></p>
              : <p style={{ color: '#92a4b2' }}>이 제품의 리뷰 관측이 아직 없어요.</p>}
          </div>
          <div className="pl-compare-bar">
            <div>
              <div style={{ fontSize: 13, fontWeight: 700 }}>다른 {item.type} 제품과 비교</div>
              <div className="pl-note" style={{ marginTop: 4 }}>가격·사양·리뷰를 나란히 보고 바꿀 수 있어요.</div>
            </div>
            <button type="button" className="pl-btn ghost" style={{ padding: '9px 14px', fontSize: 13 }} disabled={busy} onClick={onCompare}>제품 비교하기 →</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function PlanPage() {
  const { state, retryWithPerformance, refreshPlan, checkSession, selectPart, updateItem } = usePlan()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const plan = state.currentPlan
  const [openId, setOpenId] = useState<string | null>(null)
  const [checksOpen, setChecksOpen] = useState(false)
  const [comparing, setComparing] = useState<PlanItem | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  // 꼭 필요한 부품(또는 마지막 하나)을 빼려 해서 확인 문구를 보이는 부품
  const [removeFor, setRemoveFor] = useState<string | null>(null)

  // 수량 정보가 없는 옛 구성(예전에 저장된 것)이면 서버의 최신 결과로 한 번 다시 읽는다.
  const stale = !!plan && plan.items.some(item => item.qty == null)
  useEffect(() => { checkSession() }, [checkSession])
  useEffect(() => { if (stale) refreshPlan() }, [stale, refreshPlan])
  useEffect(() => { if (!plan && state.stage !== 3) navigate('/start', { replace: true }) }, [plan, state.stage, navigate])
  if (!plan) return <PlannerShell chatTitle="결과 대화" placeholder="예: CPU를 더 싼 걸로 바꿔줘"><div className="pl-page"><div className="pl-note">추천 결과를 불러오는 중이에요…</div></div></PlannerShell>

  const budget = plan.budget
  const summary = [state.intent, budget !== null ? Math.round(budget / 10000).toLocaleString('ko-KR') + '만 원' : '', state.quiet].filter(Boolean).join(' · ')
  const checks = plan.compatChecks ?? []
  async function change(item: PlanItem, patch: { qty?: number; selected?: boolean }) {
    setBusyId(item.id)
    const ok = await updateItem(item.id, patch)
    setBusyId(null)
    return ok
  }
  async function removePart(item: PlanItem) {
    setRemoveFor(null)
    if (await change(item, { selected: false })) showToast(`${eulReul(item.type)} 뺐어요. 아래 "제외됨"에서 다시 넣을 수 있어요.`)
  }
  function askRemove(item: PlanItem) {
    const lastOne = plan!.items.length === 1
    if (lastOne || (item.key && REQUIRED_PARTS.includes(item.key))) setRemoveFor(item.id)
    else void removePart(item)
  }
  const excludedIds = new Set((plan.excluded ?? []).map(item => item.id))
  // 뺀 부품은 서버 결과의 제자리에 흐리게 남긴다.
  const rows = [...plan.items, ...(plan.excluded ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

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
        <QuantityWarnings items={multiQtyItems(plan)} />

        <div className="pl-card">
          {excludedIds.size > 0 && <div className="pl-out-note">{excludedIds.size}개 부품을 뺐어요 · 뺀 부품은 합계와 확정에서 빠져요</div>}
          {rows.map(item => (
            <PartRow key={item.id} item={item} open={openId === item.id} busy={busyId === item.id} excluded={excludedIds.has(item.id)}
              confirming={removeFor === item.id} lastOne={plan.items.length === 1}
              onToggle={() => { setOpenId(openId === item.id ? null : item.id); setRemoveFor(null); if (item.key) selectPart(item.key) }}
              onCompare={() => setComparing(item)}
              onQty={qty => void change(item, { qty })}
              onRemove={() => askRemove(item)} onConfirmRemove={() => void removePart(item)} onCancelRemove={() => setRemoveFor(null)}
              onRestore={() => void change(item, { selected: true })} />
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
          <Link to="/peripherals">주변기기 이어서 짜기</Link>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <Link className="pl-btn" style={{ textDecoration: 'none' }} to="/cart">장바구니에 담기</Link>
          <Link className="pl-btn ghost" style={{ textDecoration: 'none' }} to="/start">조건 바꾸기</Link>
        </div>
      </div>
      {comparing && <AlternativesDialog item={comparing} onClose={() => setComparing(null)} />}
    </PlannerShell>
  )
}
