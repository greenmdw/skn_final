import type { Api } from '../types'
import { ApiError } from '../types'
import { parseWon } from '../../utils/format'
import { parseSpecFileText } from '../../utils/specFile'
import { delay } from './delay'
import { upgradePart } from './data/upgradePart'

// 목업: 입력한 PC 정보와 관계없이 고정된 GPU 업그레이드 제안을 돌려줍니다.
export const checks: Api['checks'] = {
  async suggestUpgrade() {
    return {
      part: 'GPU',
      currentNote: 'QHD 고주사율에서 게임별 여유 차이',
      productName: 'RTX 5070 Ti 16GB',
      productNote: '케이스 길이와 파워 커넥터 확인 필요',
      performance: '약 +28~35%',
      extraCost: parseWon(upgradePart.price),
      power: '약 +45W',
      effectSummary: 'QHD 게임 +28~35%',
      checkConditions: 'GPU 길이 · 파워 커넥터',
      disclaimer: '샘플 수치입니다. 실제 성능·예산 적합성은 분석되지 않았습니다.',
    }
  },
  async previewOwnedParts({ currentSpecs, text, imageDataUrl }) {
    // 목업은 실제 카탈로그도 LLM도 없어 매칭을 흉내만 낸다. text는 규칙 기반(key: value 줄)으로만
    // 나눈다 — 자유 문장 인식(LLM 추출)은 실서버에서만 된다는 걸 목업에서도 정직하게 보여준다.
    // 이미지는 목업에서 아예 흉내조차 못 낸다 — 실서버와 같은 문구로 에러를 낸다.
    // originalNote는 호출자(파일 업로드·행 수정)가 문맥에 맞게 채운다.
    await delay(200)
    if (imageDataUrl) throw new ApiError('이미지 인식은 지금 이 서버에서 켜져 있지 않습니다. 텍스트로 적어서 다시 시도해주세요.', 'image_extraction_unavailable')
    const merged = { ...(text?.trim() ? parseSpecFileText(text) : {}), ...(currentSpecs ?? {}) }
    return Object.entries(merged)
      .filter(([, value]) => value.trim())
      .map(([part, value]) => ({
        part, original: value.trim(), originalNote: '',
        matched: value.trim(), matchedNote: '샘플 모드에서는 실제 카탈로그와 대조하지 않습니다.',
        state: 'warn' as const, stateLabel: '확인 필요',
      }))
  },
}
