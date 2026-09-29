import { useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import { usePlan } from '../state/PlanContext'
import type { ConditionField } from '../state/types'
import { wonFmt } from '../utils/format'

// 서버가 필수로 물어보는 세 가지(config/categories/computer.yaml 의 purpose · budget_max · priority).
const REQUIRED = ['purpose', 'budget_max', 'priority'] as const
// 화면에 보여 줄 필요가 없는 내부 필드(구성 방식은 "새 컴퓨터"로 고정, 업그레이드 전용 필드는 이 화면에 없다).
const HIDDEN = new Set(['mode', 'spec_file_name', 'current_specs', 'upgrade_parts', 'owned_platform', 'owned_ram_type', 'owned_psu_w'])

function valueText(field: ConditionField): string {
  if (field.display) return field.display
  if (field.key === 'budget_max' && typeof field.value === 'number') return wonFmt(field.value)
  if (Array.isArray(field.value)) return field.value.join(', ')
  return field.value == null || field.value === '' ? '' : String(field.value)
}

export default function ConditionsPage() {
  const { state, startAnalysis } = usePlan()
  const navigate = useNavigate()
  const running = state.stage === 3
  const previousStage = useRef(state.stage)

  // 추천 계산(3)이 끝나 결과(4)가 생기면 결과 화면으로 간다. 결과를 이미 가진 채 이 화면을 다시 열었을 때는 머문다.
  useEffect(() => {
    if (previousStage.current === 3 && state.stage === 4 && state.currentPlan) navigate('/plan')
    previousStage.current = state.stage
  }, [state.stage, state.currentPlan, navigate])

  const byKey = new Map(state.fields.map(field => [field.key, field]))
  const label = (key: string, fallback: string) => byKey.get(key)?.label ?? fallback
  const extras = state.fields.filter(field => !REQUIRED.includes(field.key as typeof REQUIRED[number]) && !HIDDEN.has(field.key) && valueText(field))
  const applied = extras.filter(field => field.status === 'confirmed')
  const assumed = extras.filter(field => field.status !== 'confirmed')

  return (
    <PlannerShell chatTitle="조건 대화" placeholder="예: 150만원으로 엘든링 돌릴 조용한 PC">
      <div className="pl-page narrow" style={{ opacity: running ? 0.3 : 1 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="pl-eyebrow pl-mono">새 컴퓨터 본체 · 1 조건 → 2 추천 → 3 장바구니</div>
          <h2 className="pl-h2">조건</h2>
          <div className="pl-sub">왼쪽 채팅에 적은 말이 조건으로 바뀌어 여기에 쌓여요. 필수 항목 3개가 다 차면 추천을 받을 수 있어요.</div>
        </div>

        {state.budgetWarning && (
          <div className={'pl-alert' + (state.budgetWarning.level === 'infeasible' ? ' bad' : ' warn')} role="status">{state.budgetWarning.message}</div>
        )}

        <div className="pl-card">
          <div className="pl-card-head">필수 항목</div>
          {REQUIRED.map(key => {
            const field = byKey.get(key)
            const text = field ? valueText(field) : ''
            const fallback = key === 'purpose' ? '주요 용도' : key === 'budget_max' ? '예산' : '우선순위'
            return (
              <div className="pl-req" key={key}>
                <div className="k">{label(key, fallback)}</div>
                <div className="v" style={{ color: text ? undefined : '#92a4b2' }}>{text || '아직 말씀하지 않았어요'}</div>
                {text ? <span className="pl-badge ok">채워짐</span> : <span className="pl-badge need">답변 필요</span>}
              </div>
            )
          })}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>추가 조건 <span style={{ fontWeight: 400, color: '#92a4b2' }}>· 채팅에서 말한 것만 쌓여요</span></div>
          {applied.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="pl-group-title on">추천에 반영됨</div>
              <div className="pl-chips">{applied.map(field => <span className="pl-chip" key={field.key}><span className="k">{field.label}</span>{valueText(field)}</span>)}</div>
            </div>
          )}
          {assumed.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="pl-group-title">기본값으로 가정함 · 말씀해 주시면 바꿀게요</div>
              <div className="pl-chips">{assumed.map(field => <span className="pl-chip dash" key={field.key}><span className="k">{field.label}</span>{valueText(field)}</span>)}</div>
            </div>
          )}
          {extras.length === 0 && <div className="pl-note">아직 쌓인 추가 조건이 없어요.</div>}
        </div>

        <div className="pl-cta">
          <button type="button" className="pl-btn" disabled={!state.canRecommend || running} onClick={startAnalysis}>추천 받기</button>
          {!state.canRecommend && !running && <span className="pl-note">남은 필수 항목을 채팅으로 알려 주세요.</span>}
          {state.currentPlan && !running && <Link className="pl-btn ghost" style={{ textDecoration: 'none' }} to="/plan">지난 추천 결과 보기</Link>}
        </div>
      </div>
      {running && (
        <div className="pl-running" role="status">
          <div className="pl-spin" />
          <div style={{ fontSize: 17, fontWeight: 600 }}>서로 맞는 한 벌을 계산하고 있어요</div>
          <div className="pl-note">부품 후보와 가격, 호환성을 확인하는 중이에요. 잠시만 기다려 주세요.</div>
        </div>
      )}
    </PlannerShell>
  )
}
