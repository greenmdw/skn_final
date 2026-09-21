import { useEffect } from 'react'

const BASE_TITLE = 'TrueFit AI PC Planner'

// 라우트마다 브라우저 탭 제목을 바꿉니다. title이 없으면 기본 제목을 씁니다.
export function useDocumentTitle(title?: string) {
  useEffect(() => { document.title = title ? `${title} · TrueFit` : BASE_TITLE }, [title])
}
