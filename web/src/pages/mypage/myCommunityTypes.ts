import type { CommunityBoardType } from '../../api/http/community'

export type MyCommunityTab = 'posts' | 'comments' | 'liked' | 'saved'
export type MyCommunityFilter = 'all' | CommunityBoardType
export type MyCommunitySort = 'latest' | 'popular' | 'comments'

/** 나의 커뮤니티 목록의 한 줄. 지금은 "작성한 글"만 서버 데이터로 채운다. */
export interface MyCommunityActivity {
  id: string
  type: CommunityBoardType
  label: string
  title: string
  description: string
  date: string
  views: number
  likes: number
  comments: number
  status: string
  postId?: string
}
