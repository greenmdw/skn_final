// 숫자 입력 칸에서 쓰는 원 단위 예산 파서입니다.
export function parseBudget(value: string): number | null | undefined {
  const text = value.trim()
  if (!text) return null
  if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)\s*원?$/.test(text)) return undefined
  const amount = Number(text.replace(/[,\s원]/g, ''))
  return Number.isSafeInteger(amount) && amount > 0 && amount <= 100000000 ? amount : undefined
}

/**
 * 채팅 문장에서 예산을 찾습니다. 예: "150만원", "2,500,000원", "예산 미정".
 * allowPlain은 예산 질문에 답하는 단계에서만 켜서 QHD의 144 같은 숫자를 예산으로 오인하지 않게 합니다.
 */
export function parseBudgetText(value: string, allowPlain = false): number | null | undefined {
  const text = value.trim()
  if (!text) return undefined
  if (/(?:예산\s*)?(?:미정|정하지\s*않|상관\s*없|제한\s*없|무제한)/.test(text)) return null

  const normalized = text.replace(/,/g, '')
  const match = normalized.match(/(\d+(?:\.\d+)?)\s*(억원?|천만원|백만원|만원|만|천원|원)/)
  if (match) {
    const multipliers: Record<string, number> = {
      억: 100000000, 억원: 100000000, 천만원: 10000000, 백만원: 1000000,
      만원: 10000, 만: 10000, 천원: 1000, 원: 1,
    }
    const amount = Number(match[1]) * multipliers[match[2]]
    return Number.isSafeInteger(amount) && amount > 0 && amount <= 100000000 ? amount : undefined
  }

  if (allowPlain && /^\d+$/.test(normalized)) {
    const amount = Number(normalized)
    return Number.isSafeInteger(amount) && amount >= 10000 && amount <= 100000000 ? amount : undefined
  }
  return undefined
}
