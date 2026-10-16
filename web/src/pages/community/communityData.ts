export type CommunityBoard = 'all' | 'popular' | 'question' | 'review' | 'tip' | 'free'
export type CommunityView = 'home' | 'board' | 'post' | 'write' | 'search'

export interface CommunityPost {
  id: string
  board: Exclude<CommunityBoard, 'all'>
  boardLabel: string
  author: string
  handle: string
  time: string
  title: string
  excerpt: string
  comments: number
  likes: number
  views: number
  is_example: boolean
  likedByMe?: boolean
  coverUrl?: string | null
  mediaCount?: number
  badge?: string
  specs?: Array<{ label: string; value: string }>
  products?: Array<{ kind: string; name: string; detail: string; imageUrl?: string | null }>
}

export const boardInfo: Record<CommunityBoard, { label: string; description: string }> = {
  all: { label: '전체 글', description: '커뮤니티의 모든 게시글을 최신순으로 확인하세요.' },
  popular: { label: '인기 글', description: '최근 조회·댓글·추천 반응이 뜨거운 게시글을 모았습니다.' },
  question: { label: '질문 · Q&A', description: '견적, 호환성, 조립과 설정에 관한 질문을 나눠보세요.' },
  review: { label: '사용기 · 리뷰', description: '직접 사용한 제품과 셋업 경험을 공유합니다.' },
  tip: { label: '정보 · 팁', description: '부품 선택과 관리에 도움이 되는 정보를 모았습니다.' },
  free: { label: '자유 게시판', description: 'PC와 게임에 관한 이야기를 자유롭게 나눠보세요.' },
}
