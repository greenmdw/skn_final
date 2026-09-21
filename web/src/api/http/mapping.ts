// 화면 모델(CurrentPlan · SavedSetup)과 백엔드 모델 사이의 순수 변환 함수 모음.
// 프레임워크·네트워크에 기대지 않아 Node 로 바로 테스트한다(web/tests/mapping.test.mjs) — 그래서 타입만 import 한다.
import type { CheckDraft, CompatCheck, CompatNotice, CurrentPlan, DeskState, PartKey, PlanItem, PlanMode, ReviewRow, SavedSetup } from '../../state/types'
import type { UpgradeSuggestion } from '../types'
import type { WireCompatCheck, WireItem, WireReport, WireReportItem, WireResult, WireReview, WireText } from './wire'

// ── 슬롯 ────────────────────────────────────────────────────────────────────
// 백엔드 슬롯 이름(config/categories/computer.yaml 의 slot_structure)과 화면의 부품 키.
const SLOT_KEY: Record<string, PartKey> = {
  CPU: 'cpu', GPU: 'gpu', RAM: 'ram', 메인보드: 'board', 저장장치: 'ssd', 파워: 'psu', 케이스: 'case', 쿨러: 'cooler',
}
const SHORT_LABEL: Record<PartKey, string> = {
  cpu: 'CPU', gpu: 'GPU', ram: 'RAM', board: 'MB', ssd: 'SSD', psu: 'PSU', case: 'CASE', cooler: 'COOL', monitor: 'MON',
}
export function slotKey(slot: string): PartKey | null {
  return SLOT_KEY[slot] ?? null
}

// ── 조건: 화면의 자유 문장 → 백엔드 슬롯 값 ───────────────────────────────────
// 백엔드는 이 필드를 검증 없이 저장하므로(session_service.patch_slot) 허용 값으로 정확히 바꿔 보낸다.
export type Purpose = 'game' | 'creation' | 'office' | 'study' | 'other'
export type Priority = 'performance' | 'value' | 'quiet'
export type Resolution = 'FHD_144' | 'QHD_165' | '4K'

export function purposeFromText(text: string): Purpose {
  if (/게임|겜|배그|배틀그라운드|롤|리그|발로란트|오버워치|FPS|gaming|game/i.test(text)) return 'game'
  if (/영상|편집|렌더|프리미어|모델링|3D|디자인|작업|creat|edit|render/i.test(text)) return 'creation'
  if (/사무|문서|오피스|업무|엑셀|office/i.test(text)) return 'office'
  if (/학습|공부|인강|학생|수업|study/i.test(text)) return 'study'
  return 'other'
}

// 문장에서 게임 제목을 찾는다. 백엔드 요구사양 표(config/computer_verification_rules.yaml 의 game_titles)가 알아보는
// 이름으로 바꿔 보낸다 — 두 곳의 이름을 함께 고쳐야 한다. 표에 없는 게임은 여기서도 못 찾는다(서버가 알리는 건 찾은 것 중 모르는 것뿐).
const GAME_TITLES: [string, RegExp][] = [
  ['발로란트', /발로란트|valorant/i],
  ['리그 오브 레전드', /리그\s*오브\s*레전드|(?<![가-힣])롤(?:(?![가-힣])|(?=이랑|이나|이|을|은|도|과|만|로|에|하고|하는|해))|(?<![a-z])lol(?![a-z])/i],
  ['오버워치', /오버워치|overwatch/i],
  ['메이플스토리', /메이플|maplestory/i],
  ['로스트아크', /로스트\s*아크|lost\s*ark/i],
  ['마인크래프트', /마인\s*크래프트|minecraft/i],
  ['배틀그라운드', /배틀\s*그라운드|(?<![가-힣])배그|pubg/i],
  ['엘든링', /엘든\s*링|elden\s*ring/i],
  ['디아블로 4', /디아블로\s*4|diablo\s*(iv|4)/i],
  ['워존', /워존|warzone/i],
  ['발더스 게이트 3', /발더스\s*게이트|baldur/i],
  ['사이버펑크 2077', /사이버\s*펑크|cyberpunk/i],
  ['검은 신화: 오공', /검은\s*신화|black\s*myth/i],
  ['몬스터 헌터 와일즈', /몬스터\s*헌터|몬헌|monster\s*hunter/i],
  ['스타필드', /스타필드|starfield/i],
]

export function gamesFromText(text: string): string[] {
  return GAME_TITLES.filter(([, pattern]) => pattern.test(text)).map(([name]) => name)
}

// 채팅 선택지('저소음 우선' · '균형형' · '성능 우선')와 자유 문장 모두를 받는다.
export function priorityFromText(text: string): Priority {
  if (/저소음|조용|소음/.test(text)) return 'quiet'
  if (/성능/.test(text)) return 'performance'
  return 'value'
}

// 해상도·주사율 목표. 백엔드에는 QHD 144Hz / QHD 60Hz 단계가 없어 초당 처리 화소수가 가까운 단계로 근사한다:
// QHD 144Hz ≈ 5.3억 화소/초 → QHD_165(6.1억), QHD 60Hz ≈ 2.2억 → FHD_144(3.0억). 모르면 null(백엔드 기본값 사용).
export function resolutionFromText(text: string): Resolution | null {
  if (/4K|UHD|2160/i.test(text)) return '4K'
  if (/QHD|1440/i.test(text)) return /60\s*Hz/i.test(text) ? 'FHD_144' : 'QHD_165'
  if (/FHD|1080/i.test(text)) return 'FHD_144'
  return null
}

// 점검 질문에서 바꾸려는 부품(백엔드 슬롯 이름)을 찾는다. 못 찾으면 GPU — 화면의 업그레이드 흐름이 GPU 를 전제로 한다.
export function upgradePartsFromText(text: string): string[] {
  const rules: [string, RegExp][] = [
    ['GPU', /GPU|그래픽|지포스|라데온|RTX|GTX|\bRX\s?\d/i],
    ['CPU', /CPU|프로세서|씨피유|라이젠|인텔/i],
    ['RAM', /RAM|램|메모리/i],
    ['저장장치', /SSD|저장|스토리지|NVMe/i],
    ['파워', /파워|PSU|전원/i],
  ]
  const found = rules.filter(([, pattern]) => pattern.test(text)).map(([slot]) => slot)
  return found.length ? found : ['GPU']
}

// 점검 화면의 부품 행 → 백엔드가 읽는 current_specs(슬롯 → 사용자가 쓴 문자열). 백엔드가 모르는 부품(SSD·DISPLAY)은 뺀다.
const ROW_SLOT: Record<string, string> = { CPU: 'CPU', GPU: 'GPU', RAM: 'RAM', BOARD: '메인보드' }
export function currentSpecsFromRows(rows: ReviewRow[]): Record<string, string> {
  const specs: Record<string, string> = {}
  for (const row of rows) {
    const slot = ROW_SLOT[row.part]
    const text = row.original.trim()
    if (slot && text) specs[slot] = text
  }
  return specs
}

// ── 추천 결과 → 화면 구성 ────────────────────────────────────────────────────
const TIMING: Record<string, { action: string; actionClass: '' | 'track' | 'later' }> = {
  now: { action: '지금 구매', actionClass: '' },
  soon: { action: '곧 구매', actionClass: 'track' },
  later: { action: '나중에 구매', actionClass: 'later' },
}

function reasonText(reason: WireText): string {
  if (reason.status === 'ready' && reason.text) return reason.text
  if (reason.status === 'failed') return '추천 이유를 만들지 못했습니다.'
  return '추천 이유를 정리하고 있습니다.'
}

function ratingText(review: WireReview | null): string {
  return review?.rating_refined != null ? review.rating_refined.toFixed(1) : '-'
}

// 리뷰 관측이 없는 상품은 "없음"이지 0건이 아니다 — 모르는 값을 지어내지 않는다.
function reviewsText(review: WireReview | null): string {
  return review?.total_count != null ? review.total_count.toLocaleString('ko-KR') + '개' : '없음'
}

function priceSourceText(item: WireItem): string {
  if (item.price_source === 'observed') return item.price_observed_at ? '수집 가격 · ' + item.price_observed_at.slice(0, 10) : '수집 가격'
  return '데모 가격'
}

export function itemFromWire(item: WireItem): PlanItem {
  const key = slotKey(item.slot)
  const timing = TIMING[item.timing] ?? TIMING.now
  const tags = [item.price_source === 'observed' ? '수집 가격' : '데모 가격']
  if (item.alternatives_count > 0) tags.push('대안 ' + item.alternatives_count + '개')
  return {
    id: item.item_id, key, type: item.slot_label, name: item.product.name,
    price: item.price * item.qty,
    meta: item.slot_label + ' · ' + (item.product.spec_summary || item.product.brand || item.product.name),
    source: priceSourceText(item),
    action: timing.action, actionClass: timing.actionClass,
    score: item.budget_share != null ? '예산의 ' + Math.round(item.budget_share * 100) + '%' : '',
    fit: reasonText(item.reason),
    reasonTitle: item.slot_label + ' 추천 이유',
    tags, checks: checksFromWire(item.checks),
    rating: ratingText(item.review), reviews: reviewsText(item.review),
    label: key ? SHORT_LABEL[key] : item.slot_label.slice(0, 4),
  }
}

/** 선택한 부품의 추천 근거를 묻는 말인지. 바꾸라는 요청이 섞여 있으면 서버가 처리한다. */
export function wantsPartExplanation(text: string): boolean {
  return /근거|이유|자세|상세|왜|설명/.test(text) && !/바꿔|바꾸|교체|변경|빼|넣|담/.test(text)
}

/** 이미 받아 둔 서버 응답(이름·추천 이유·가격)으로 만든 답 — 서버 호출 없이 바로 답한다. */
export function partExplanation(part: PlanItem): string {
  return [part.name, part.reasonTitle, part.fit, '가격: ' + part.price.toLocaleString('ko-KR') + '원'].filter(Boolean).join('\n')
}

/** 서버가 " · " 로 이어 붙인 구매 전 확인 문장을 항목별로 나눈다. 준비 전(pending)·실패면 빈 목록. */
export function checksFromWire(checks: WireItem['checks']): string[] {
  if (!checks || checks.status !== 'ready' || !checks.text) return []
  return checks.text.split(' · ').map(part => part.trim()).filter(Boolean)
}

/** 세트 검증 쟁점 → 화면 안내. major(확정 문제)와 minor(확인 못 한 항목)로 나눈다. */
export function compatFromWire(verification: WireResult['verification']): CompatNotice | undefined {
  if (!verification || verification.status !== 'ready') return undefined
  const texts = (severity: 'major' | 'minor') => verification.issues.filter(issue => (issue.severity === 'major') === (severity === 'major')).map(issue => issue.text)
  return { problems: texts('major'), unchecked: texts('minor') }
}

/** 서버의 업그레이드 추천 결과 → 점검 화면의 제안 카드. 서버가 계산하지 않는 값(성능 변화 폭·소비전력)은 비워 둔다(화면이 안 보인다). */
export function suggestionFromPlan(plan: CurrentPlan, draft: CheckDraft): UpgradeSuggestion | null {
  const item = plan.items[0]
  if (!item) return null
  const row = draft.rows.find(r => r.part.toLowerCase() === item.key)
  const compat = plan.compat
  const conditions = !compat ? '구매 전 호환성을 확인해주세요'
    : compat.problems.length ? compat.problems.join(' / ')
    : compat.unchecked.length ? `스펙을 몰라 확인하지 못한 항목 ${compat.unchecked.length}개 — 구매 전 확인`
    : '확인한 범위에서 부품 간 충돌 없음'
  return {
    part: item.type,
    currentNote: row ? '현재 입력: ' + row.original : '현재 부품 정보를 입력하지 않았습니다',
    productName: item.name, productNote: item.meta,
    performance: '', power: '',
    extraCost: item.price,
    effectSummary: item.fit || '추천 이유를 준비하지 못했습니다',
    checkConditions: conditions,
    disclaimer: '가격은 수집 데이터 기준입니다. 성능 향상 폭과 소비전력 변화는 계산하지 않았습니다.',
  }
}

/** 서버의 호환 검사 상세 → 화면 목록. 모르는 state 는 unknown 으로 본다(단정하지 않는다). */
export function compatChecksFromWire(checks: WireCompatCheck[] | null | undefined): CompatCheck[] | undefined {
  if (!checks || !checks.length) return undefined
  const known = ['ok', 'unknown', 'fail', 'skipped']
  return checks.map(c => ({ axis: c.axis, label: c.label, detail: c.detail, state: (known.includes(c.state) ? c.state : 'unknown') as CompatCheck['state'] }))
}

export interface PlanContext {
  mode: PlanMode
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  checkSnapshot: CheckDraft | null
}

export function planFromResult(result: WireResult, context: PlanContext): CurrentPlan {
  return {
    id: result.list_id, mode: context.mode,
    items: result.items.filter(item => item.selected).map(itemFromWire),
    compat: compatFromWire(result.verification),
    compatChecks: compatChecksFromWire(result.compat_checks),
    budget: context.budget, conditions: { ...context.conditions },
    checkSnapshot: context.checkSnapshot ? structuredClone(context.checkSnapshot) : null,
  }
}

// ── 확정한 리포트 → 저장한 구성 ───────────────────────────────────────────────
/** 서버에 없는 화면 전용 값(책상 치수 · 점검 초안 · 입력한 조건 문장). 확정할 때 이 브라우저에 따로 보관한다. */
export interface SetupExtras {
  mode: PlanMode
  budget: number | null
  conditions: { intent: string; performance: string; quiet: string }
  checkSnapshot: CheckDraft | null
  desk: DeskState
  checkDraft: CheckDraft
}

export const DEFAULT_DESK: DeskState = { deskUnlocked: false, deskWidth: 1400, deskDepth: 700, deskHeight: 740 }

function reportItem(item: WireReportItem, index: number): PlanItem {
  const key = slotKey(item.slot)
  return {
    id: item.slot + '-' + index, key, type: item.slot_label, name: item.product.name,
    price: item.price * item.qty,
    meta: item.slot_label, source: '확정 시점 가격',
    action: (TIMING[item.timing] ?? TIMING.now).action, actionClass: (TIMING[item.timing] ?? TIMING.now).actionClass,
    score: '', fit: item.evidence_text ?? '', reasonTitle: item.slot_label + ' 추천 이유', tags: [],
    rating: ratingText(item.review), reviews: reviewsText(item.review),
    label: key ? SHORT_LABEL[key] : item.slot_label.slice(0, 4),
  }
}

function dateOnly(value: string | null, fallbackIso: string): string {
  const source = value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value : fallbackIso
  return source.slice(0, 10)
}

export function setupFromReport(report: WireReport, extras: SetupExtras | undefined): SavedSetup {
  const plan: CurrentPlan = {
    id: report.list_id, mode: extras?.mode ?? 'new',
    items: report.items.map(reportItem),
    budget: extras?.budget ?? null,
    conditions: extras?.conditions ?? { intent: '', performance: '', quiet: '' },
    checkSnapshot: extras?.checkSnapshot ?? null,
  }
  return {
    id: report.list_id, title: report.name,
    date: dateOnly(report.planned_purchase_at, report.confirmed_at),
    target: report.target_amount ?? report.total, memo: report.memo,
    savedAt: report.confirmed_at, plan,
    desk: extras?.desk ?? { ...DEFAULT_DESK },
    checkDraft: extras?.checkDraft ?? { question: '', budget: '', rows: [] },
  }
}
