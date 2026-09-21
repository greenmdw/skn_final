// 로그인 뒤 돌아갈 경로(?next=)는 같은 사이트의 경로만 받는다 — 다른 사이트로 보내는 열린 리다이렉트 방지.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { safeNext } from '../src/utils/redirect.ts'

test('같은 사이트 경로는 받는다', () => {
  assert.equal(safeNext('?next=/plan/confirm'), '/plan/confirm')
  assert.equal(safeNext('?next=%2Fplan%2Fconfirm'), '/plan/confirm')
  assert.equal(safeNext('?a=1&next=/plan'), '/plan')
})

test('없거나 비어 있으면 null', () => {
  assert.equal(safeNext(''), null)
  assert.equal(safeNext('?next='), null)
  assert.equal(safeNext('?other=/plan'), null)
})

test('다른 사이트·프로토콜 상대 경로·역슬래시는 거절', () => {
  assert.equal(safeNext('?next=https://evil.example/x'), null)
  assert.equal(safeNext('?next=//evil.example/x'), null)
  assert.equal(safeNext('?next=/\\evil.example'), null)
  assert.equal(safeNext('?next=javascript:alert(1)'), null)
  assert.equal(safeNext('?next=plan'), null)
})
