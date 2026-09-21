import type { Api } from '../types'
import { wonFmt } from '../../utils/format'
import { delay } from './delay'

// 목업: 정해진 문장으로 답합니다. 실제 서비스에서는 챗봇 응답 API로 교체됩니다.
export const chat: Api['chat'] = {
  async reply({ topic, text, selectedPart, plan }) {
    if (topic === 'intent') {
      await delay(450)
      return {
        text: '요청하신 조건을 기록했어요. 성능 목표를 선택해주세요. 예산은 PC 구성 패널에서 직접 확인·수정할 수 있어요.',
        choices: [
          { label: 'QHD 144Hz', value: 'QHD 144Hz' }, { label: 'QHD 60Hz', value: 'QHD 60Hz' }, { label: '잘 모르겠어요', value: '추천값' },
        ],
      }
    }
    if (topic === 'performance') {
      await delay(450)
      return {
        text: '성능 목표를 ' + text + '로 기록했어요. 소음은 어느 정도 중요할까요?',
        choices: [
          { label: '최대한 조용하게', value: '저소음 우선' }, { label: '성능과 균형', value: '균형형' }, { label: '상관없어요', value: '성능 우선' },
        ],
      }
    }
    const part = plan?.items.find(p => p.key === selectedPart)
    if (/근거|이유|자세|상세|왜|설명/.test(text) && part) {
      return { text: part.name + '\n' + part.reasonTitle + '\n' + part.fit + '\n가격: ' + wonFmt(part.price) + '\n샘플 추천 근거입니다.' }
    }
    return { text: '질문을 받았습니다. 현재는 샘플 구성으로, 대화에 따른 자동 부품 변경은 아직 연결되지 않았습니다.' }
  },

  async reviewReply({ topic }) {
    await delay(350)
    return {
      text: topic === 'config'
        ? '자동 수정은 아직 지원하지 않습니다. 구성표의 수정 버튼으로 직접 변경해주세요.'
        : '질문을 받았습니다. 실제 분석은 아직 연결되지 않아 추가 추천을 계산할 수 없습니다.',
    }
  },
}
