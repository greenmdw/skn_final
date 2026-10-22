import type { CommunityBoardType } from '../../api/http/community'

export type MyCommunityTab = 'posts' | 'comments' | 'liked' | 'saved'
export type MyCommunityFilter = 'all' | CommunityBoardType
/** 작성한 글 탭은 글 목록 API 의 정렬(최신·추천·조회), 나머지 탭은 활동 API 의 정렬(최신·추천·댓글)을 쓴다. */
export type MyCommunitySort = 'latest' | 'popular' | 'comments' | 'views'

/** 나의 커뮤니티 목록의 한 줄. 글·댓글·추천·저장 목록을 같은 모양으로 그린다. */
export interface MyCommunityActivity {
  id: string
  type: CommunityBoardType
  label: string
  title: string
  description: string
  date: string
  stats: string
  status: string
  /** 숨김·삭제된 원문이면 이동하지 않는다 */
  gone: boolean
  postId: string
}
