// 화면 ↔ 백엔드 변환 규칙 테스트. Node 내장 러너(`npm test`)로 돌고 새 의존성이 없다 — mapping.ts 는 타입만 import 하므로
// Node 의 타입 제거(type stripping)로 바로 읽힌다.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  currentSpecsFromRows, itemFromWire, planFromResult, priorityFromText, purposeFromText, resolutionFromText,
  setupFromReport, slotKey, upgradePartsFromText,
} from '../src/api/http/mapping.ts'

const wireItem = (over = {}) => ({
  item_id: 'it-1', slot: 'CPU', slot_label: 'CPU',
  product: { name: 'AMD Ryzen 5 7600', brand: 'AMD', spec_summary: '6코어 · AM5' },
  price: 221750, price_source: 'synthetic', price_observed_at: null, qty: 1, selected: true, timing: 'now',
  budget_share: 0.168, review: null, reason: { status: 'ready', text: '게임 성능 대비 가격이 좋습니다.' },
  alternatives_count: 3, ...over,
})

test('슬롯 이름은 화면 부품 키로 바뀌고, 모르는 슬롯은 null', () => {
  const expected = { CPU: 'cpu', GPU: 'gpu', RAM: 'ram', 메인보드: 'board', 저장장치: 'ssd', 파워: 'psu', 케이스: 'case', 쿨러: 'cooler' }
  for (const [slot, key] of Object.entries(expected)) assert.equal(slotKey(slot), key)
  assert.equal(slotKey('모니터'), null)
})

test('용도 문장 → 백엔드 purpose', () => {
  assert.equal(purposeFromText('150만원으로 QHD 게임용 PC를 맞춰줘'), 'game')
  assert.equal(purposeFromText('영상편집용인데 조용했으면 좋겠어'), 'creation')
  assert.equal(purposeFromText('사무용 PC가 필요해요'), 'office')
  assert.equal(purposeFromText('대학생 공부용'), 'study')
  assert.equal(purposeFromText('그냥 PC 추천해줘'), 'other')
})

test('소음 선택지·문장 → priority', () => {
  assert.equal(priorityFromText('저소음 우선'), 'quiet')
  assert.equal(priorityFromText('성능 우선'), 'performance')
  assert.equal(priorityFromText('균형형'), 'value')
  assert.equal(priorityFromText('소음은 지금보다 커지지 않았으면 좋겠습니다'), 'quiet')
  assert.equal(priorityFromText(''), 'value')
})

test('성능 목표 → resolution (QHD 144Hz·60Hz 는 화소 처리량이 가까운 단계로 근사)', () => {
  assert.equal(resolutionFromText('QHD 144Hz'), 'QHD_165')
  assert.equal(resolutionFromText('QHD 60Hz'), 'FHD_144')
  assert.equal(resolutionFromText('4K 60Hz'), '4K')
  assert.equal(resolutionFromText('FHD 240Hz'), 'FHD_144')
  assert.equal(resolutionFromText('추천값'), null)
  assert.equal(resolutionFromText(''), null)
})

test('점검 질문에서 바꿀 부품 찾기 — 없으면 GPU', () => {
  assert.deepEqual(upgradePartsFromText('GPU만 바꾸면 되는지, RAM도 추가해야 하는지'), ['GPU', 'RAM'])
  assert.deepEqual(upgradePartsFromText('그래픽카드를 바꾸고 싶어요'), ['GPU'])
  assert.deepEqual(upgradePartsFromText('SSD 용량이 부족해요'), ['저장장치'])
  assert.deepEqual(upgradePartsFromText('뭘 바꾸면 좋을까요'), ['GPU'])
})

test('점검 행 → current_specs: 백엔드가 아는 부품만, 사용자가 쓴 원문으로', () => {
  const row = (part, original) => ({ part, original, originalNote: '', matched: 'x', matchedNote: '', state: 'ok', stateLabel: '확인' })
  const specs = currentSpecsFromRows([
    row('CPU', 'AMD Ryzen 7 7800X3D'), row('GPU', 'RTX 4070 SUPER'), row('BOARD', 'B650M WiFi'),
    row('SSD', 'Samsung 990 PRO 1TB'), row('DISPLAY', 'LG 27GR95QE'), row('RAM', '   '),
  ])
  assert.deepEqual(specs, { CPU: 'AMD Ryzen 7 7800X3D', GPU: 'RTX 4070 SUPER', 메인보드: 'B650M WiFi' })
})

test('추천 항목 → 화면 부품: 가격·이유·리뷰 없음 처리', () => {
  const item = itemFromWire(wireItem())
  assert.equal(item.key, 'cpu')
  assert.equal(item.price, 221750)
  assert.equal(item.fit, '게임 성능 대비 가격이 좋습니다.')
  assert.equal(item.reviews, '없음')           // 관측이 없으면 0건이 아니라 "없음"
  assert.equal(item.rating, '-')
  assert.equal(item.score, '예산의 17%')
  assert.equal(item.source, '데모 가격')
  assert.deepEqual(item.tags, ['데모 가격', '대안 3개'])
  assert.equal(item.label, 'CPU')
})

test('수량은 가격에 곱하고, 리뷰·평점·수집 가격이 있으면 그대로 보인다', () => {
  const item = itemFromWire(wireItem({
    slot: '쿨러', slot_label: '쿨러', qty: 2, price: 38200, price_source: 'observed', price_observed_at: '2026-09-18T00:00:00Z',
    review: { total_count: 1234, rating_refined: 4.36 }, timing: 'later', alternatives_count: 0,
  }))
  assert.equal(item.key, 'cooler')
  assert.equal(item.price, 76400)
  assert.equal(item.reviews, '1,234개')
  assert.equal(item.rating, '4.4')
  assert.equal(item.source, '수집 가격 · 2026-09-18')
  assert.equal(item.actionClass, 'later')
  assert.deepEqual(item.tags, ['수집 가격'])
})

test('이유 문장이 아직 없으면 정리 중, 실패하면 실패로 알린다', () => {
  assert.match(itemFromWire(wireItem({ reason: { status: 'pending', text: null } })).fit, /정리하고 있습니다/)
  assert.match(itemFromWire(wireItem({ reason: { status: 'failed', text: null } })).fit, /만들지 못했습니다/)
})

test('추천 결과 → 구성: 선택한 항목만, 점검 초안은 복사', () => {
  const draft = { question: 'q', budget: '1,000,000원', rows: [] }
  const plan = planFromResult(
    { list_id: 'L1', status: 'done', explanation: { status: 'ready' }, error: null,
      items: [wireItem(), wireItem({ item_id: 'it-2', slot: 'GPU', selected: false })] },
    { mode: 'upgrade', budget: 800000, conditions: { intent: 'i', performance: '', quiet: '' }, checkSnapshot: draft },
  )
  assert.equal(plan.id, 'L1')
  assert.equal(plan.mode, 'upgrade')
  assert.equal(plan.items.length, 1)
  assert.deepEqual(plan.checkSnapshot, draft)
  assert.notEqual(plan.checkSnapshot, draft)
})

test('확정 리포트 → 저장한 구성: 서버 값 + 화면 전용 값, 없으면 기본값', () => {
  const report = {
    list_id: 'L1', name: '내 PC', planned_purchase_at: '2026-10-30T00:00:00+09:00', target_amount: null, memo: '메모',
    total: 100000, confirmed_at: '2026-09-21T10:00:00+09:00',
    items: [{ slot: '메인보드', slot_label: '메인보드', product: { name: 'GIGABYTE A620M H' }, price: 88500, qty: 1, timing: 'now',
      review: null, evidence_text: '소켓이 맞습니다.' }],
  }
  const setup = setupFromReport(report, undefined)
  assert.equal(setup.id, 'L1')
  assert.equal(setup.date, '2026-10-30')
  assert.equal(setup.target, 100000)            // 목표 금액이 없으면 합계
  assert.equal(setup.plan.items[0].key, 'board')
  assert.equal(setup.plan.items[0].fit, '소켓이 맞습니다.')
  assert.equal(setup.desk.deskUnlocked, false)
  assert.deepEqual(setup.checkDraft.rows, [])
  assert.equal(setup.plan.mode, 'new')
})
