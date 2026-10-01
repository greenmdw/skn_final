import { useCallback } from 'react'
import { api, errorMessage } from '../api'
import { useSetups } from './SetupsContext'
import { useToast } from './ToastContext'

/** 견적서 하나를 지운다 — 좌측 패널 우클릭 메뉴와 리포트 화면의 삭제 버튼이 함께 쓴다. 지웠으면 true(이동은 부른 쪽이 정한다). */
export function useRemoveSheet() {
  const { reload } = useSetups()
  const { showToast } = useToast()
  return useCallback(async (listId: string, report: { revisionNo: number; name: string }, isLast: boolean): Promise<boolean> => {
    const note = isLast ? ' 마지막 견적서라 대화는 남고, 그 구성은 작성 중인 견적으로 돌아가요.' : ''
    if (!window.confirm(`“${report.name}” 견적서를 삭제할까요?${note} 되돌릴 수 없어요.`)) return false
    try {
      await api.lists.removeReport(listId, report.revisionNo)
    } catch (error) {
      showToast(errorMessage(error, '삭제하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
    reload()
    return true
  }, [reload, showToast])
}
