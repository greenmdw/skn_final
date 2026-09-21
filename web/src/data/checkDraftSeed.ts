import type { CheckDraft, ReviewRow } from '../state/types'

const initialRows: ReviewRow[] = [
  { part: 'CPU', original: 'AMD Ryzen 7 7800X3D', originalNote: '원문에서 읽음', matched: 'AMD Ryzen 7 7800X3D', matchedNote: 'AM5 · 8코어', state: 'ok', stateLabel: '확인' },
  { part: 'GPU', original: 'RTX 4070 SUPER', originalNote: '원문에서 읽음', matched: 'MSI RTX 4070 SUPER 12GB', matchedNote: '모델 후보 1개', state: 'ok', stateLabel: '확인' },
  { part: 'RAM', original: 'DDR5 32GB', originalNote: '속도 인식 안 됨', matched: 'DDR5 32GB · 모델 불명', matchedNote: '궁금한 확정됨', state: 'warn', stateLabel: '확인 필요' },
  { part: 'SSD', original: 'Samsung 990 PRO 1TB', originalNote: '원문에서 읽음', matched: 'Samsung 990 PRO 1TB', matchedNote: 'PCIe 4.0 NVMe', state: 'ok', stateLabel: '확인' },
  { part: 'BOARD', original: 'B650M WiFi', originalNote: '제조사 불명', matched: 'B650M WiFi · 모델 후보', matchedNote: 'AM5 · mATX', state: 'warn', stateLabel: '후보' },
  { part: 'DISPLAY', original: 'LG 27GR95QE', originalNote: '시스템에서 확인', matched: 'LG 27GR95QE', matchedNote: 'QHD · 240Hz', state: 'ok', stateLabel: '확인' },
]

export function createCheckDraft(): CheckDraft {
  return {
    question: 'QHD 게임을 하고 싶은데 GPU만 바꾸면 되는지, RAM도 추가해야 하는지 알려주세요. 소음은 지금보다 커지지 않았으면 좋겠습니다.',
    budget: '1,000,000원',
    rows: initialRows.map(row => ({ ...row })),
  }
}
