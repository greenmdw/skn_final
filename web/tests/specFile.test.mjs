// 견적 점검 파일 유틸 — 규칙 기반 텍스트 파서와 이미지 파일 판별.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isImageFile, parseSpecFileText } from '../src/utils/specFile.ts'

test('key: value 줄만 뽑고, 저장장치(SSD) 별칭도 인식한다', () => {
  const text = 'CPU: i5-14400F\nSSD: 990 PRO\nStorage: 다른 SSD\n그래픽카드: RTX 4070\n파워: 750W\n'
  assert.deepEqual(parseSpecFileText(text), {
    CPU: 'i5-14400F', 저장장치: '다른 SSD', GPU: 'RTX 4070', 파워: '750W',
  })   // 같은 슬롯이 두 번 나오면(SSD 다음 Storage) 나중 줄이 남는다
})

test('자유 문장은 이 파서로 못 뽑는다 — LLM 추출이 있어야 한다', () => {
  assert.deepEqual(parseSpecFileText('라이젠 7800X3D에 4070 SUPER 얹었어요'), {})
})

test('isImageFile: MIME 타입 또는 확장자로 이미지 여부를 본다', () => {
  assert.equal(isImageFile(new File(['x'], 'shot.png', { type: 'image/png' })), true)
  assert.equal(isImageFile(new File(['x'], 'shot.PNG', { type: '' })), true)   // 확장자만으로도
  assert.equal(isImageFile(new File(['x'], 'spec.txt', { type: 'text/plain' })), false)
})
