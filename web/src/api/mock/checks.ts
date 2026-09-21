import type { Api } from '../types'
import { parseWon } from '../../utils/format'
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
}
