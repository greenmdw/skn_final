import { usePlan } from '../../state/PlanContext'
import type { CompatCheck } from '../../state/types'

const MARK: Record<CompatCheck['state'], { icon: string; text: string }> = {
  ok: { icon: '✓', text: '통과' },
  unknown: { icon: '△', text: '확인 못 함' },
  fail: { icon: '✕', text: '문제' },
  skipped: { icon: '–', text: '건너뜀' },
}

// 세트 전체 호환 점검 결과. 서버가 확정한 문제(소켓·전력·크기·예산)는 눈에 띄게, 스펙을 몰라 정밀 검사를 못 한 항목은 접어서 보여 준다.
// 아래 "검사 상세"는 서버가 어떤 검사를 무엇과 비교해 어떻게 판정했는지 전부 보여 준다.
export function CompatNotice() {
  const { state } = usePlan()
  const compat = state.currentPlan?.compat
  const checks = state.currentPlan?.compatChecks ?? []
  if (!compat && !checks.length) return null
  const count = (s: CompatCheck['state']) => checks.filter(c => c.state === s).length
  const problems = compat?.problems ?? []
  const unchecked = compat?.unchecked ?? []
  const clean = !problems.length && !unchecked.length
  return <section className={'compat-notice' + (problems.length ? ' problem' : clean ? ' ok' : '')} aria-label="호환성 점검">
    <h2>호환성 점검</h2>
    {clean && <p className="compat-ok">확인한 범위에서 부품 간 충돌은 없습니다.</p>}
    {problems.length > 0 && <ul className="compat-problems">{problems.map(text => <li key={text}>{text}</li>)}</ul>}
    {unchecked.length > 0 && <details>
      <summary>스펙 데이터가 부족해 정확히 확인하지 못한 항목 {unchecked.length}개</summary>
      <ul>{unchecked.map(text => <li key={text}>{text}</li>)}</ul>
    </details>}
    {checks.length > 0 && <details className="compat-detail">
      <summary>검사 상세 보기 · {checks.length}개 검사 (통과 {count('ok')} · 확인 못 함 {count('unknown')} · 문제 {count('fail')} · 건너뜀 {count('skipped')})</summary>
      <ul className="compat-rows">{checks.map(c => <li key={c.axis} className={'compat-row ' + c.state}>
        <span className="compat-mark" aria-label={MARK[c.state].text} title={MARK[c.state].text}>{MARK[c.state].icon}</span>
        <span className="compat-body"><strong>{c.label}</strong><small>{c.detail}</small></span>
      </li>)}</ul>
      <p className="setup-hint">각 검사는 지금 선택된 부품의 스펙으로 서버가 계산한 값입니다. 스펙에 없는 정보는 통과로 보지 않고 "확인 못 함"으로 남깁니다.</p>
    </details>}
  </section>
}
