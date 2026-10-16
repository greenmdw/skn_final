import type {
  PeripheralAdjustChip, PeripheralInterpretation, PeripheralKind, PeripheralResolvedKind, PeripheralReviewAspect,
} from '../api/types'

export const PERIPHERAL_KINDS: { id: PeripheralKind; label: string; description: string }[] = [
  { id: 'monitor', label: '모니터', description: '해상도·주사율·화면 크기' },
  { id: 'keyboard', label: '키보드', description: '타건감·소음·배열' },
  { id: 'mouse', label: '마우스', description: '크기·무게·연결 방식' },
  { id: 'speaker', label: '스피커', description: '크기·출력·연결 방식' },
]

/**
 * 채팅 입력창 위의 빠른 조건 칩(품목별). 눌러서 보내는 문장은 모두 서버가 그 품목의 조건으로 읽는 것을 확인한 말이다
 * (모니터 해상도 칩은 모니터를 골랐을 때만 나온다).
 */
export const QUICK_CONDITIONS: Record<PeripheralKind, string[]> = {
  monitor: ['4K', 'QHD 165Hz', '게임용', '문서·코딩용', '맥북 연결'],
  keyboard: ['조용한 키보드', '텐키리스', '묵직한 키압', '래피드 트리거'],
  mouse: ['가벼운 무선', '손목 편한', '유선', 'fps용'],
  speaker: ['작은 스피커', '음악 감상', '블루투스', '영화·게임용'],
}

/** 서버 평가 기준 코드 → 화면 문구. 모르는 코드는 코드 그대로 보인다. */
const ASPECT_LABEL: Record<string, string> = {
  connection_stability: '연결 안정성',
  connection_controls: '연결·조작',
  controls_usability: '조작 편의',
  controls_ergonomics: '조작 인체공학',
  physical_usability: '사용 편의',
  typing_feel: '타건감',
  typing_noise: '타건 소음',
  functional_reliability: '기능 신뢰성',
  image_quality: '화질',
  motion_response: '화면 반응',
  battery_runtime: '배터리',
  ergonomics: '인체공학·그립',
  tracking_input: '추적·입력',
  output_level: '출력',
  sound_quality: '음질',
  unwanted_noise: '잡음',
}
export const aspectLabel = (code: string) => ASPECT_LABEL[code] ?? code

export const CHECK_STATE_LABEL = { ok: '통과', fail: '문제', unknown: '확인 못 함' } as const

export interface ReviewEvidence extends PeripheralReviewAspect {
  total: number
}

/** 관측이 있는 평가 기준만, 언급이 많은 순으로 */
export function reviewEvidence(aspects: PeripheralReviewAspect[], limit = 3): ReviewEvidence[] {
  return aspects
    .map(aspect => ({ ...aspect, total: aspect.positive + aspect.negative + aspect.mixed }))
    .filter(aspect => aspect.total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, limit)
}

// ---- 문장 해석(서버 /peripherals/interpret) 결과를 화면 상태로 다루는 도구 ----

export const EMPTY_INTERPRETATION: PeripheralInterpretation = {
  kinds: [], purposes: [], situations: [], stated: {}, handSize: null, budget: {}, budgetMin: {}, budgetTotal: null,
  emphasis: {}, brandLike: {}, brandAvoid: {}, exclude: {}, unrecognized: [],
}

export const HAND_SIZE_LABEL = { small: '작은 편', medium: '보통', large: '큰 편' } as const

/**
 * 공통 상황 코드 → 화면 문구(서버 설정 situations 의 라벨과 같다). 어떤 품목의 목적 칩으로도 안 보이는 상황(예: 마우스의 "조용해야 함")도
 * 이해한 내용에 보여 주려고 쓴다. 표에 없는 코드는 보이지 않는다(모르는 이름을 코드 그대로 내지 않는다).
 */
export const SITUATION_LABEL: Record<string, string> = {
  quiet_place: '조용해야 함', mic: '마이크 사용', small_desk: '좁은 책상', portable: '들고 다님', trending: '요즘 많이 쓰는 것', design: '디자인이 중요',
}

/** 화면이 들고 있는 "이해한 내용". 칩을 지우거나 "더 맞추기"를 누르면 이 값만 바뀌고, 추천만 다시 부른다. */
export interface UnderstoodState {
  interpretation: PeripheralInterpretation
  resolved: Partial<Record<PeripheralKind, PeripheralResolvedKind>>
  /** "더 맞추기" 칩으로 더한 것 — 칩을 다시 지우면 add 를 입력에서 뺀다 */
  adjusted: { key: string; label: string; kind: PeripheralKind; add: PeripheralAdjustChip['add'] }[]
}

export const EMPTY_UNDERSTOOD: UnderstoodState = { interpretation: EMPTY_INTERPRETATION, resolved: {}, adjusted: [] }

const without = (list: string[], values: string[]) => list.filter(value => !values.includes(value))
const union = (a: string[], b: string[]) => [...new Set([...a, ...b])]

function mergeStated(a: PeripheralInterpretation['stated'], b: PeripheralInterpretation['stated'] | undefined) {
  const next: PeripheralInterpretation['stated'] = { ...a }
  for (const [kind, conditions] of Object.entries(b ?? {}) as [PeripheralKind, string[]][]) next[kind] = union(next[kind] ?? [], conditions)
  return next
}

/** 아직 입력에 남아 있는 근거(목적·상황 코드, 또는 직접 말한 조건)가 하나라도 있는 선호만 남긴다 */
function pruneResolved(state: UnderstoodState): UnderstoodState {
  const { interpretation } = state
  const alive = (kind: PeripheralKind, condition: string, source: string) => (
    source === 'stated' ? (interpretation.stated[kind] ?? []).includes(condition)
      : interpretation.purposes.includes(source) || interpretation.situations.includes(source)
  )
  const resolved: UnderstoodState['resolved'] = {}
  for (const [key, entry] of Object.entries(state.resolved) as [PeripheralKind, PeripheralResolvedKind][]) {
    resolved[key] = {
      ...entry,
      purposes: entry.purposes.filter(purpose => interpretation.purposes.includes(purpose.code)),
      preferences: entry.preferences.filter(item => item.sources.length === 0 || item.sources.some(source => alive(key, item.condition, source))),
      filters: entry.filters.filter(item => (interpretation.stated[key] ?? []).includes(item.condition)),
    }
  }
  return { ...state, resolved }
}

export type UnderstoodRemoval =
  | { type: 'purpose'; code: string }
  | { type: 'situation'; code: string }
  | { type: 'preference'; kind: PeripheralKind; condition: string; sources: string[] }
  | { type: 'filter'; kind: PeripheralKind; condition: string }
  | { type: 'budget'; kind: PeripheralKind | null }
  | { type: 'budget_min'; kind: PeripheralKind }
  | { type: 'adjusted'; key: string }
  | { type: 'emphasis'; kind: PeripheralKind; axis: string }
  | { type: 'brand_like'; kind: PeripheralKind; brand: string }
  | { type: 'brand_avoid'; kind: PeripheralKind; brand: string }
  | { type: 'exclude'; kind: PeripheralKind; name: string }
  | { type: 'handSize' }

/** 칩 하나를 입력에서 뺀다. 서버를 다시 부르지 않고(문장 해석 비용 없음) 화면이 가진 값만 고친다. */
export function removeUnderstood(state: UnderstoodState, removal: UnderstoodRemoval): UnderstoodState {
  const interp = state.interpretation
  let next: UnderstoodState = state
  if (removal.type === 'purpose') {
    next = { ...state, interpretation: { ...interp, purposes: without(interp.purposes, [removal.code]) } }
  } else if (removal.type === 'situation') {
    next = { ...state, interpretation: { ...interp, situations: without(interp.situations, [removal.code]) } }
  } else if (removal.type === 'filter') {
    next = { ...state, interpretation: { ...interp, stated: { ...interp.stated, [removal.kind]: without(interp.stated[removal.kind] ?? [], [removal.condition]) } } }
  } else if (removal.type === 'preference') {
    const codes = removal.sources.filter(source => source !== 'stated')
    const stated = removal.sources.includes('stated')
      ? { ...interp.stated, [removal.kind]: without(interp.stated[removal.kind] ?? [], [removal.condition]) } : interp.stated
    next = { ...state, interpretation: { ...interp, purposes: without(interp.purposes, codes), situations: without(interp.situations, codes), stated } }
  } else if (removal.type === 'budget') {
    if (removal.kind === null) next = { ...state, interpretation: { ...interp, budgetTotal: null } }
    else {
      const budget = { ...interp.budget }
      delete budget[removal.kind]
      next = { ...state, interpretation: { ...interp, budget } }
    }
  } else if (removal.type === 'budget_min') {
    const budgetMin = { ...interp.budgetMin }
    delete budgetMin[removal.kind]
    next = { ...state, interpretation: { ...interp, budgetMin } }
  } else if (removal.type === 'emphasis') {
    next = { ...state, interpretation: { ...interp, emphasis: { ...interp.emphasis, [removal.kind]: without(interp.emphasis[removal.kind] ?? [], [removal.axis]) } } }
  } else if (removal.type === 'brand_like') {
    const liked = without(interp.brandLike[removal.kind] ?? [], [removal.brand])
    // 선호 브랜드를 말하면 서버가 "브랜드" 축 강조를 저절로 붙인다 — 선호가 없어지면 그것도 함께 뺀다.
    const emphasis = liked.length ? interp.emphasis : { ...interp.emphasis, [removal.kind]: without(interp.emphasis[removal.kind] ?? [], ['브랜드']) }
    next = { ...state, interpretation: { ...interp, brandLike: { ...interp.brandLike, [removal.kind]: liked }, emphasis } }
  } else if (removal.type === 'brand_avoid') {
    next = { ...state, interpretation: { ...interp, brandAvoid: { ...interp.brandAvoid, [removal.kind]: without(interp.brandAvoid[removal.kind] ?? [], [removal.brand]) } } }
  } else if (removal.type === 'exclude') {
    next = { ...state, interpretation: { ...interp, exclude: { ...interp.exclude, [removal.kind]: without(interp.exclude[removal.kind] ?? [], [removal.name]) } } }
  } else if (removal.type === 'handSize') {
    next = { ...state, interpretation: { ...interp, handSize: null } }
  } else {
    const chip = state.adjusted.find(item => item.key === removal.key)
    if (!chip) return state
    const stated = { ...interp.stated }
    for (const [kind, conditions] of Object.entries(chip.add.stated ?? {}) as [PeripheralKind, string[]][]) stated[kind] = without(stated[kind] ?? [], conditions)
    next = {
      ...state,
      interpretation: { ...interp, purposes: without(interp.purposes, chip.add.purposes ?? []), situations: without(interp.situations, chip.add.situations ?? []), stated },
      adjusted: state.adjusted.filter(item => item.key !== removal.key),
    }
  }
  return pruneResolved(next)
}

/** "더 맞추기" 칩의 add 를 입력에 더한다. 이미 더한 칩이면 그대로 둔다. */
export function applyAdjustChip(state: UnderstoodState, chip: PeripheralAdjustChip): UnderstoodState {
  const key = `${chip.kind}:${chip.id}`
  if (state.adjusted.some(item => item.key === key)) return state
  const interp = state.interpretation
  return {
    ...state,
    interpretation: {
      ...interp,
      purposes: union(interp.purposes, chip.add.purposes ?? []),
      situations: union(interp.situations, chip.add.situations ?? []),
      stated: mergeStated(interp.stated, chip.add.stated),
    },
    adjusted: [...state.adjusted, { key, label: chip.label, kind: chip.kind, add: chip.add }],
  }
}

/** 추천 요청에 실을 값(문장 해석 결과를 그대로). 강조·브랜드·손 크기도 빠뜨리지 않는다 — 말했는데 결과에 안 반영되던 문제(QA 종합#33·34)다. */
export function recommendInputs(interp: PeripheralInterpretation) {
  return {
    budgetMax: interp.budgetTotal ?? undefined,
    purposes: interp.purposes, situations: interp.situations, stated: interp.stated, kindBudget: interp.budget,
    kindBudgetMin: interp.budgetMin,
    emphasis: interp.emphasis, brandLike: interp.brandLike, brandAvoid: interp.brandAvoid, exclude: interp.exclude, handSize: interp.handSize,
  }
}

/**
 * 화면의 선택 종류로 해석을 맞춘다. 체크를 푼 종류의 종류 이름뿐 아니라 그 종류의 직접 말한 조건·예산·강조·브랜드도 뺀다 —
 * 서버는 조건이나 예산이 남은 종류를 "찾는 종류"로 다시 넣으므로, 종류만 빼면 다음 문장에서 체크가 되살아난다(QA 종합#32).
 * 체크를 푼 종류의 칩은 화면에도 보이지 않으므로 보이는 것과 보내는 것이 같아진다. 해석이 비어 있으면 그대로 둔다.
 */
export function withKinds(state: UnderstoodState, kinds: PeripheralKind[]): UnderstoodState {
  if (state.interpretation === EMPTY_INTERPRETATION) return state
  const keep = <T,>(record: Partial<Record<PeripheralKind, T>>) => {
    const next: Partial<Record<PeripheralKind, T>> = {}
    for (const kind of kinds) if (record[kind] !== undefined) next[kind] = record[kind]
    return next
  }
  const interp = state.interpretation
  return {
    ...state,
    interpretation: {
      ...interp, kinds, stated: keep(interp.stated), budget: keep(interp.budget), budgetMin: keep(interp.budgetMin),
      emphasis: keep(interp.emphasis), brandLike: keep(interp.brandLike), brandAvoid: keep(interp.brandAvoid), exclude: keep(interp.exclude),
    },
  }
}
