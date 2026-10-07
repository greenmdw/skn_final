import type { PeripheralKind, PeripheralRecommendRequest, PeripheralReviewAspect } from '../api/types'

export const PERIPHERAL_KINDS: { id: PeripheralKind; label: string; description: string }[] = [
  { id: 'monitor', label: '모니터', description: '해상도·주사율·화면 크기' },
  { id: 'keyboard', label: '키보드', description: '타건감·소음·배열' },
  { id: 'mouse', label: '마우스', description: '크기·무게·연결 방식' },
  { id: 'speaker', label: '스피커', description: '크기·출력·연결 방식' },
]

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

export interface ParsedPeripheralConditions {
  spec: string[]
  feel: string[]
  budgetMax?: number
  resolution?: PeripheralRecommendRequest['resolution']
  noiseSensitive?: boolean
}

/** 대화 문장에서 조건을 뽑는다. 서버가 받는 값(예산·해상도·소음)과, 화면에만 쌓아 두는 체감 문구를 나눈다. */
export function parsePeripheralCondition(text: string): ParsedPeripheralConditions {
  const spec: string[] = []
  const feel: string[] = []
  const parsed: ParsedPeripheralConditions = { spec, feel }
  const budget = text.match(/(\d+(?:[.,]\d+)?)\s*만\s*원/)
  if (budget) {
    spec.push(`예산 ${budget[1]}만 원`)
    parsed.budgetMax = Math.round(Number(budget[1].replace(',', '')) * 10_000)
  }
  if (/QHD|1440/i.test(text)) { spec.push(/165\s*Hz/i.test(text) ? 'QHD 165Hz' : 'QHD'); parsed.resolution = 'QHD_165' }
  else if (/FHD|1080/i.test(text)) { spec.push(/144\s*Hz/i.test(text) ? 'FHD 144Hz' : 'FHD'); parsed.resolution = 'FHD_144' }
  else if (/4K|UHD|2160/i.test(text)) { spec.push('4K'); parsed.resolution = '4K' }
  if (/조용|저소음|소음/.test(text)) { feel.push('조용한 사용감'); parsed.noiseSensitive = true }
  if (/쫀득|타건/.test(text)) feel.push('쫀득한 타건감')
  if (/가벼|경량/.test(text)) feel.push('가벼운 무게')
  if (/손이?\s*작|작은\s*손/.test(text)) feel.push('작은 손')
  if (/눈.*편|눈부심|피로/.test(text)) feel.push('눈이 편한 화면')
  return parsed
}
