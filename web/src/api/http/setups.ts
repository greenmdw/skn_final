import type { Api, SetupsListResult } from '../types'
import { ApiError } from '../types'
import type { SavedSetup } from '../../state/types'
import { isCheckDraft, isDesk, object } from '../../state/validators'
import { request } from './client'
import { setupFromReport, type SetupExtras } from './mapping'
import type { WireLists, WireReport } from './wire'

// 서버에 저장하는 것: 확정한 목록(이름·구매 예정일·목표 금액·메모)과 부품·가격. 서버에 필드가 없는 화면 전용 값
// (책상 치수 · 점검 초안 · 입력한 조건 문장)은 이 브라우저에만 보관한다 — 다른 기기에서는 기본값으로 보인다.
const EXTRAS_KEY = 'truefit.setup-extras.v1'

const isConditions = (value: unknown) =>
  object(value) && ['intent', 'performance', 'quiet'].every(key => typeof value[key] === 'string')

function isExtras(value: unknown): value is SetupExtras {
  return object(value) && (value.mode === 'new' || value.mode === 'upgrade') &&
    (value.budget === null || typeof value.budget === 'number') && isConditions(value.conditions) &&
    (value.checkSnapshot === null || isCheckDraft(value.checkSnapshot)) && isDesk(value.desk) && isCheckDraft(value.checkDraft)
}

function readExtras(): Record<string, SetupExtras> {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(EXTRAS_KEY) || '{}')
    if (!object(data)) return {}
    return Object.fromEntries(Object.entries(data).filter(([, extras]) => isExtras(extras))) as Record<string, SetupExtras>
  } catch { return {} }
}

// 화면 전용 값의 보관은 실패해도 확정을 막지 않는다(서버 저장이 본체).
function writeExtras(next: Record<string, SetupExtras>) {
  try { localStorage.setItem(EXTRAS_KEY, JSON.stringify(next)) } catch { /* 보관 실패는 무시 */ }
}

function toConfirmError(error: unknown): unknown {
  if (error instanceof ApiError && error.code === 'unauthorized') {
    return new ApiError('로그인이 필요합니다. 로그인하면 지금 구성을 그대로 확정할 수 있어요.', 'AUTH_REQUIRED')
  }
  if (error instanceof ApiError && error.code === 'not_found') {
    return new ApiError('서버에서 이 구성을 찾을 수 없습니다. 추천을 다시 받은 뒤 확정해주세요.', 'NOT_FOUND')
  }
  return error
}

export const setups: Api['setups'] = {
  async list(): Promise<SetupsListResult> {
    const lists = await request<WireLists>('GET', '/lists')
    const confirmed = lists.items.filter(item => item.stage === 'report' && item.category === 'computer')
    const reports = await Promise.allSettled(confirmed.map(item => request<WireReport>('GET', '/lists/' + item.list_id + '/report')))
    const extras = readExtras()
    const data: SavedSetup[] = []
    for (const report of reports) if (report.status === 'fulfilled') data.push(setupFromReport(report.value, extras[report.value.list_id]))
    const failed = reports.length - data.length
    return { data, warning: failed > 0 ? `리포트 ${failed}개를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.` : '' }
  },

  async save(setup) {
    let report: WireReport
    try {
      report = await request<WireReport>('POST', '/lists/' + setup.id + '/confirm', {
        name: setup.title, planned_purchase_at: setup.date, target_amount: setup.target, memo: setup.memo,
      })
    } catch (error) { throw toConfirmError(error) }
    writeExtras({ ...readExtras(), [setup.id]: {
      mode: setup.plan.mode, budget: setup.plan.budget, conditions: setup.plan.conditions,
      checkSnapshot: setup.plan.checkSnapshot, desk: setup.desk, checkDraft: setup.checkDraft,
    } })
    // 사용자가 본 부품·추천 이유는 그대로 두고, 서버가 확정한 값(이름·날짜·목표 금액·메모·시각)을 반영한다.
    const saved = setupFromReport(report, undefined)
    return { ...structuredClone(setup), title: saved.title, date: saved.date, target: saved.target, memo: saved.memo, savedAt: saved.savedAt }
  },

  async remove(id) {
    try {
      await request<void>('DELETE', '/lists/' + id)
    } catch (error) {
      if (!(error instanceof ApiError && error.code === 'not_found')) throw error   // 이미 없으면 지운 것과 같다
    }
    const next = readExtras()
    delete next[id]
    writeExtras(next)
  },
}
