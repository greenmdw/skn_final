import type { Api, QuoteReviewRequest, QuoteReviewResult } from '../api'
import type { ReviewRow } from '../state/types'

/**
 * TEMPORARY UI PROTOTYPE DATA
 * 받은 견적 점검 백엔드 연결이 완료되면 이 파일 전체를 삭제하고,
 * CheckPage의 CHECK_REVIEW_USE_MOCK 분기와 import만 제거한다.
 */

type CheckReviewClient = Pick<Api['checks'],
  | 'previewOwnedParts'
  | 'createReview'
  | 'updateReview'
  | 'getReview'
  | 'comparePart'
  | 'sendMessage'
  | 'getMessages'
  | 'apply'
>

const MOCK_PARTS: ReviewRow[] = [
  { part: 'CPU', original: '인텔 코어 i5-14400F', originalNote: '', matched: 'Intel Core i5-14400F', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
  { part: 'GPU', original: 'MSI 지포스 RTX 4060 벤투스 2X 블랙 OC D6 8GB', originalNote: '', matched: 'MSI RTX 4060 VENTUS 2X BLACK OC 8GB', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
  { part: 'RAM', original: '삼성전자 DDR5-5600 16GB × 2', originalNote: '', matched: 'Samsung DDR5-5600 16GB', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
  { part: '메인보드', original: 'B760M 보드 DDR5', originalNote: '', matched: 'MSI PRO B760M-A WIFI DDR5', matchedNote: '공통 규격을 기준으로 대응했습니다.', state: 'warn', stateLabel: '모호함' },
  { part: 'SSD', original: 'SK하이닉스 Platinum P41 1TB', originalNote: '', matched: 'SK hynix Platinum P41 1TB', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
  { part: '파워', original: '정격 600W 파워', originalNote: '', matched: '마이크로닉스 Classic II 600W', matchedNote: '정격 출력 기준 후보입니다.', state: 'warn', stateLabel: '후보 대응' },
  { part: '케이스', original: '다크플래쉬 DLM21 MESH 블랙', originalNote: '', matched: 'darkFlash DLM21 MESH', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
  { part: '쿨러', original: '인텔 정품 기본 쿨러', originalNote: '', matched: 'Intel Laminar RM1', matchedNote: '', state: 'ok', stateLabel: '대응됨' },
]

export const CHECK_REVIEW_MOCK_PREVIEW_META: Record<string, { price: number; quantity: number }> = {
  CPU: { price: 238000, quantity: 1 },
  GPU: { price: 419000, quantity: 1 },
  RAM: { price: 128000, quantity: 2 },
  메인보드: { price: 149000, quantity: 1 },
  SSD: { price: 118000, quantity: 1 },
  파워: { price: 59000, quantity: 1 },
  케이스: { price: 62000, quantity: 1 },
  쿨러: { price: 0, quantity: 1 },
}

const wait = (milliseconds = 280) => new Promise(resolve => window.setTimeout(resolve, milliseconds))

function rowsFor(request?: QuoteReviewRequest): ReviewRow[] {
  const specs = request?.currentSpecs ?? {}
  return MOCK_PARTS.map(row => ({ ...row, original: specs[row.part] || row.original }))
}

function mockReview(request: QuoteReviewRequest = {}): QuoteReviewResult {
  const parts = rowsFor(request)
  const currentSpecs = Object.fromEntries(parts.map(row => [row.part, row.original]))
  return {
    listId: 'mock-check-review',
    version: 1,
    input: { currentSpecs, conditions: {}, inputHash: 'mock-ui-only' },
    parts,
    compat: {
      checks: [
        { axis: 'cpu_socket', label: 'CPU · 메인보드 소켓', state: 'ok', detail: 'LGA1700 소켓 기준으로 서로 호환됩니다.' },
        { axis: 'memory', label: '메모리 규격', state: 'ok', detail: '메인보드와 메모리 모두 DDR5 규격입니다.' },
        { axis: 'power', label: '전력 여유', state: 'ok', detail: '예상 소비전력 대비 정격 600W 용량에 여유가 있습니다.' },
        { axis: 'case', label: '케이스 장착', state: 'ok', detail: 'M-ATX 메인보드와 그래픽카드 장착 공간을 충족합니다.' },
      ],
      summary: { ok: 4, fail: 0, unknown: 0, skipped: 0 },
      incompatible: [],
    },
    prices: {
      available: true,
      reason: null,
      rows: [
        { part: 'CPU', matched: 'Intel Core i5-14400F', quoted: 238000, catalog: 231000, quantity: 1, diff: 7000, diffPercent: 3, state: 'similar', detail: '카탈로그 기준가와 비슷한 수준입니다.' },
        { part: 'GPU', matched: 'MSI RTX 4060 VENTUS 2X BLACK OC 8GB', quoted: 419000, catalog: 398000, quantity: 1, diff: 21000, diffPercent: 5.3, state: 'pricier', detail: '카탈로그 기준가보다 조금 높습니다.' },
        { part: 'RAM', matched: 'Samsung DDR5-5600 16GB', quoted: 128000, catalog: 124000, quantity: 2, diff: 4000, diffPercent: 3.2, state: 'similar', detail: '16GB 2개 합산 가격이 기준가와 비슷합니다.' },
        { part: '메인보드', matched: 'MSI PRO B760M-A WIFI DDR5', quoted: 149000, catalog: 155000, quantity: 1, diff: -6000, diffPercent: -3.9, state: 'similar', detail: '카탈로그 기준가와 비슷한 수준입니다.' },
        { part: 'SSD', matched: 'SK hynix Platinum P41 1TB', quoted: 118000, catalog: 114000, quantity: 1, diff: 4000, diffPercent: 3.5, state: 'similar', detail: '카탈로그 기준가와 비슷한 수준입니다.' },
        { part: '파워', matched: '마이크로닉스 Classic II 600W', quoted: 59000, catalog: 62000, quantity: 1, diff: -3000, diffPercent: -4.8, state: 'similar', detail: '카탈로그 기준가와 비슷한 수준입니다.' },
        { part: '케이스', matched: 'darkFlash DLM21 MESH', quoted: 62000, catalog: 59000, quantity: 1, diff: 3000, diffPercent: 5.1, state: 'similar', detail: '카탈로그 기준가와 비슷한 수준입니다.' },
        { part: '쿨러', matched: 'Intel Laminar RM1', quoted: 0, catalog: null, quantity: 1, diff: null, diffPercent: null, state: 'no_catalog', detail: 'CPU 기본 구성품이라 별도 가격을 비교하지 않았습니다.' },
      ],
      summary: { quotedTotal: 1173000, catalogTotal: 1143000 },
    },
    balance: {
      available: true,
      reason: null,
      rows: [
        { part: 'GPU', aspect: 'QHD 게임 성능', state: 'short', detail: '높은 옵션의 QHD 게임에서는 그래픽 옵션 조정이 필요할 수 있습니다.', measured: 2, target: 3 },
        { part: 'CPU', aspect: '그래픽카드 조합', state: 'ok', detail: '현재 그래픽카드와 균형이 맞는 구성입니다.', measured: 3, target: 3 },
        { part: 'RAM', aspect: '멀티태스킹', state: 'ok', detail: '총 32GB로 게임과 일반 작업을 함께 수행하기에 충분합니다.', measured: 32, target: 32 },
        { part: 'SSD', aspect: '저장 공간', state: 'ok', detail: '1TB 용량으로 운영체제와 여러 게임을 설치할 수 있습니다.', measured: 1, target: 1 },
      ],
      summary: { short: 1, excess: 0, ok: 3, unknown: 0 },
      notes: ['화면 구성을 위한 임시 목업 분석입니다.'],
    },
    compare: {
      available: true,
      reason: null,
      rows: [
        { part: 'GPU', quote: { name: 'RTX 4060' }, ours: { name: 'RTX 4060 Ti' }, sameProduct: false, priceDiff: 88000, priceDiffPercent: 21, priceState: 'pricier', tierDiff: 1, detail: '우리 추천은 QHD 성능을 위해 한 단계 높은 GPU를 선택했습니다.' },
        { part: 'SSD', quote: { name: 'Platinum P41 1TB' }, ours: { name: 'Platinum P41 1TB' }, sameProduct: true, priceDiff: 0, priceDiffPercent: 0, priceState: 'similar', tierDiff: 0, detail: '저장장치는 같은 제품을 선택했습니다.' },
      ],
      summary: { compared: 2 },
      notes: ['비교 화면 구성을 위한 임시 목업입니다.'],
    },
    computedAt: new Date().toISOString(),
  }
}

export const checkReviewMock: CheckReviewClient = {
  async previewOwnedParts(request) {
    await wait()
    return rowsFor({ currentSpecs: request.currentSpecs, text: request.text, imageDataUrl: request.imageDataUrl })
  },
  async createReview(request) {
    await wait(450)
    return mockReview(request)
  },
  async updateReview(_listId, request) {
    await wait()
    return mockReview(request)
  },
  async getReview() {
    await wait()
    return mockReview()
  },
  async comparePart(_listId, slot) {
    await wait()
    const current = MOCK_PARTS.find(row => row.part === slot)
    const basePrice = CHECK_REVIEW_MOCK_PREVIEW_META[slot]?.price ?? 150000
    const cpuCandidates = slot === 'CPU' ? [
      { name: 'Intel Core i5-14600KF', price: 329000, priceDelta: 91000, tier: 4, cores: '14코어 20스레드', incompatible: [] as string[], rating: 4.7, reviewCount: 188 },
      { name: 'Intel Core i5-13400F', price: 189000, priceDelta: -49000, tier: 3, cores: '10코어 16스레드', incompatible: [] as string[], rating: 4.6, reviewCount: 402 },
      { name: 'AMD 라이젠5 7500F', price: 189000, priceDelta: -49000, tier: 3, cores: '6코어 12스레드', incompatible: ['메인보드 소켓 LGA1700과 맞지 않아요'], rating: 4.7, reviewCount: 212 },
    ] : [
      { name: slot === 'GPU' ? 'GIGABYTE RTX 4060 Ti WINDFORCE OC 8GB' : `${current?.matched || slot} 상위 후보`, price: basePrice + 88000, priceDelta: 88000, tier: 4, cores: '상위 성능 등급', incompatible: [] as string[], rating: 4.7, reviewCount: 188 },
      { name: `${current?.matched || slot} 가성비 후보`, price: Math.max(0, basePrice - 30000), priceDelta: -30000, tier: 3, cores: '동급 성능 등급', incompatible: [] as string[], rating: 4.6, reviewCount: 402 },
      { name: `${current?.matched || slot} 대체 규격 후보`, price: Math.max(0, basePrice - 49000), priceDelta: -49000, tier: 3, cores: '대체 규격', incompatible: ['현재 구성과 규격 확인이 필요해요'], rating: 4.5, reviewCount: 126 },
    ]
    return {
      slot,
      baseline: { name: current?.matched || current?.original || slot },
      unmatchedTargets: [],
      note: '화면 구성을 확인하기 위한 임시 비교 후보입니다.',
      candidates: cpuCandidates.map(candidate => ({
          name: candidate.name,
          price: candidate.price,
          priceDelta: candidate.priceDelta,
          perfTier: candidate.tier,
          specs: [
            { key: 'summary', label: '스펙', unit: '', baseline: '기준 제품', candidate: candidate.cores, diff: null },
            { key: 'grade', label: '성능 등급', unit: '', baseline: 3, candidate: candidate.tier, diff: candidate.tier - 3 },
            { key: 'warranty', label: '보증 기간', unit: '년', baseline: 3, candidate: 3, diff: 0 },
          ],
          incompatible: candidate.incompatible,
          compatChanges: [],
          review: { rating: candidate.rating, count: candidate.reviewCount },
        })),
    }
  },
  async sendMessage(_listId, text) {
    await wait()
    return {
      reply: `“${text}”에 대한 점검 화면용 임시 답변입니다. 실제 근거와 답변은 백엔드 연결 후 표시됩니다.`,
      evidence: [],
      via: 'rules',
    }
  },
  async getMessages() {
    return []
  },
  async apply(_listId, slots) {
    await wait()
    return { listId: 'mock-applied-review', slots, missing: [], runId: 'mock-run' }
  },
}
