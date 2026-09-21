// 계약 테스트 — 실제 백엔드가 낸 응답(fixtures/backend_flow.json)을 화면 변환 로직에 통과시킨다.
// 백엔드 응답 모양이 바뀌어 화면이 읽는 필드가 사라지면 여기서 먼저 깨진다.
// fixtures 는 백엔드 흐름을 돌려 다시 만들 수 있다: 신규 조립 → 추천 → 가입 → 확정 → 목록 → 리포트(docs/pc_pipeline_quickstart.md).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { planFromResult, setupFromReport } from '../src/api/http/mapping.ts'

const flow = JSON.parse(readFileSync(new URL('./fixtures/backend_flow.json', import.meta.url), 'utf-8'))
const conditions = { intent: '게임용', performance: 'QHD 144Hz', quiet: '저소음 우선' }

test('추천 결과: 화면이 읽는 필드가 모두 있다', () => {
  const { result } = flow
  assert.equal(result.status, 'done')
  assert.ok(result.list_id)
  assert.ok(['pending', 'ready', 'failed'].includes(result.explanation.status))
  for (const item of result.items) {
    for (const key of ['item_id', 'slot', 'slot_label', 'price', 'price_source', 'qty', 'selected', 'timing', 'alternatives_count']) {
      assert.ok(key in item, `items[].${key} 없음`)
    }
    assert.equal(typeof item.product.name, 'string')
    assert.ok(['pending', 'ready', 'failed'].includes(item.reason.status))
  }
})

test('추천 결과 → 구성: 8개 슬롯이 모두 화면 키로 바뀌고 합계가 서버와 같다', () => {
  const plan = planFromResult(flow.result, { mode: 'new', budget: 2000000, conditions, checkSnapshot: null })
  assert.equal(plan.id, flow.result.list_id)
  assert.equal(plan.items.length, 8)
  assert.deepEqual(plan.items.map(item => item.key).sort(), ['board', 'case', 'cooler', 'cpu', 'gpu', 'psu', 'ram', 'ssd'])
  assert.equal(plan.items.reduce((sum, item) => sum + item.price, 0), flow.result.totals.selected_price)
  for (const item of plan.items) {
    assert.ok(item.name && item.type, '이름·종류가 비어 있음')
    assert.ok(Number.isSafeInteger(item.price) && item.price > 0)
    assert.equal(typeof item.fit, 'string')
  }
})

test('가입 응답: 화면이 쓰는 사용자 필드', () => {
  assert.ok(flow.signup.user.email)
  assert.ok(flow.signup.user.display_name)
})

test('로그인 없이 확정하면 401 unauthorized — 화면이 로그인 안내로 바꾸는 코드', () => {
  assert.equal(flow.unauth_confirm.status, 401)
  assert.equal(flow.unauth_confirm.body.error.code, 'unauthorized')
})

test('내 목록: 확정한 컴퓨터 목록이 stage=report 로 나온다', () => {
  const mine = flow.lists.items.find(item => item.list_id === flow.result.list_id)
  assert.ok(mine, '확정한 목록이 /lists 에 없음')
  assert.equal(mine.stage, 'report')
  assert.equal(mine.category, 'computer')
})

test('리포트 → 저장한 구성: 서버가 확정한 값이 그대로 보인다', () => {
  const { report } = flow
  const setup = setupFromReport(report, undefined)
  assert.equal(setup.id, report.list_id)
  assert.equal(setup.title, '계약 리스트')
  assert.equal(setup.date, '2026-10-30')
  assert.equal(setup.memo, '계약 테스트')
  assert.equal(setup.target, report.target_amount)
  assert.equal(setup.savedAt, report.confirmed_at)
  assert.equal(setup.plan.items.length, 8)
  assert.equal(setup.plan.items.reduce((sum, item) => sum + item.price, 0), report.total)
  assert.ok(Number.isFinite(Date.parse(setup.savedAt)), 'savedAt 이 날짜로 읽혀야 함(화면 검증기)')
})

test('추천 결과: 구매 전 확인과 세트 검증이 화면 변환을 통과한다', () => {
  const plan = planFromResult(flow.result, { mode: 'new', budget: 2000000, conditions, checkSnapshot: null })
  assert.ok(plan.compat, '세트 검증이 준비된 결과인데 compat 가 없음')
  assert.equal(plan.compat.problems.length, 0)                       // 처음 추천에는 확정된 비호환이 없다
  assert.ok(Array.isArray(plan.compat.unchecked))                    // 스펙을 몰라 확인 못 한 항목(없을 수도 있다 — 신규 조립은 대개 비어 있다)
  for (const item of plan.items) {
    assert.ok(item.checks.length > 0, item.type + ': 구매 전 확인이 비어 있음')
    assert.ok(item.checks.every(text => !/^\[[a-z_]+\]/.test(text)), '내부 축 이름([bios] 등)이 그대로 보임')
  }
})

test('후속 질문(부품 교체) 응답: 바뀐 구성이 화면 구성으로 바뀌고 총액이 서버와 같다', () => {
  const { text, before_total: beforeTotal, response } = flow.chat_swap
  assert.ok(text && response.reply.includes('GPU'))
  const plan = planFromResult(response.result, { mode: 'new', budget: 2000000, conditions, checkSnapshot: null })
  assert.equal(plan.items.length, 8)
  const total = plan.items.reduce((sum, item) => sum + item.price, 0)
  assert.equal(total, response.result.totals.selected_price)
  assert.ok(total < beforeTotal, '더 저렴한 것으로 바꿨는데 총액이 줄지 않음')
  assert.ok(plan.compat, '교체 뒤에도 세트 검증이 화면 구성에 실린다')
})

test('추천 결과: 호환 검사 상세가 서버 응답 그대로 화면 구성에 실린다', () => {
  const plan = planFromResult(flow.result, { mode: 'new', budget: 2000000, conditions, checkSnapshot: null })
  const checks = plan.compatChecks
  assert.ok(checks && checks.length >= 10, '검사 상세가 없음')
  for (const c of checks) {
    assert.ok(['ok', 'unknown', 'fail', 'skipped'].includes(c.state), c.axis + ': ' + c.state)
    assert.ok(c.label && c.detail, c.axis + ': 라벨·설명이 비어 있음')
  }
  const axes = checks.map(c => c.axis)
  for (const axis of ['socket', 'memory', 'gpu_len', 'cooler_socket', 'bios', 'power', 'psu_form', 'gpu_connector']) assert.ok(axes.includes(axis), axis + ' 검사가 없음')
  assert.equal(checks.filter(c => c.state === 'fail').length, 0)       // 처음 추천에는 확정된 비호환이 없다
})
