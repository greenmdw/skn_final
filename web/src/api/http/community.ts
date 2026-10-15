import { request, requestForm } from './client'

// 커뮤니티 백엔드(/community/*, /catalog/products) 호출. 읽기(목록·상세·검색·댓글)는 로그인 없이 되고, 쓰기는 로그인이 필요하다
// (서버가 401 → ApiError('로그인이 필요합니다.', 'unauthorized') 로 돌려준다). CommunityPage 는 아직 정적 데이터를 쓰고 있다 —
// 이 모듈의 mapCommunityItem 이 서버 응답을 화면의 CommunityPost 모양으로 바꿔 주므로, 화면은 데이터 출처만 갈아 끼우면 된다.

export type CommunityBoardType = 'question' | 'review' | 'tip' | 'free'
export type CommunitySort = 'latest' | 'popular' | 'views' | 'recommend'

export interface WireCommunityProduct {
  id: string
  product_id: string | null
  product_kind: string
  name: string | null
  brand: string | null
  custom_product_name: string | null
  selected_option: string | null
  match_status: 'matched' | 'unmatched' | 'review_needed'
  display_order: number
  image_url: string | null
}

export interface WireCommunityImage {
  id: string
  url: string
  width: number
  height: number
  order: number
}

export interface WireCommunityItem {
  id: string
  board_type: CommunityBoardType
  board_label: string
  title: string
  excerpt: string
  author: { id: string; name: string }
  is_example: boolean
  status: 'draft' | 'published' | 'hidden' | 'deleted'
  comment_count: number
  like_count: number
  view_count: number
  liked_by_me: boolean
  saved_by_me?: boolean
  tags: string[]
  products: WireCommunityProduct[]
  published_at: string | null
  image_count: number
  cover_image_url: string | null
}

export interface WireCommunityDetail extends WireCommunityItem {
  body: string
  version: number
  images: WireCommunityImage[]
  created_at: string
  updated_at: string
  can_edit: boolean
  can_delete: boolean
  is_mine: boolean
}

export interface WireCommunityList {
  items: WireCommunityItem[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface WireCommunityComment {
  id: string
  author: { id: string; name: string } | null
  body: string
  is_deleted: boolean
  is_mine: boolean
  can_edit: boolean
  created_at: string
  updated_at: string
  edited: boolean
  replies?: WireCommunityComment[]
}

export interface CommunityProductInput {
  product_id?: string | null
  product_kind: string
  custom_product_name?: string | null
  selected_option?: string | null
}

export interface CommunityPostInput {
  board_type: CommunityBoardType
  title: string
  body: string
  tags?: string[]
  products?: CommunityProductInput[]
  publish?: boolean
  image_ids?: string[]
}

// ── 내 활동(마이페이지 "나의 커뮤니티") · 알림 · 저장 ──
export interface WireMyActivitySummary {
  post_count: number
  comment_count: number
  received_comment_count: number
  received_like_count: number
  liked_post_count: number
  saved_post_count: number
  unread_notification_count: number
}

/** 내가 추천·저장한 글. 숨김·삭제된 글도 항목은 남고 post_status 로 구분한다(제목은 서버가 "삭제된 글입니다"로 바꿔 준다). */
export interface WireMyPostItem extends WireCommunityItem {
  post_status: 'published' | 'hidden' | 'deleted'
  liked_at?: string
  saved_at?: string
}

export interface WireMyComment {
  id: string
  body: string
  created_at: string
  updated_at: string
  parent_comment_id: string | null
  reply_count: number
  post_status: 'published' | 'hidden' | 'deleted'
  post: { id: string; title: string; board_type: CommunityBoardType; board_label: string; status: string }
}

export interface WireNotification {
  id: string
  type: 'new_comment' | 'new_reply'
  title: string
  message: string
  count: number
  post_id: string
  comment_id: string | null
  read: boolean
  created_at: string
}

export interface WirePage<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export type MyActivitySort = 'latest' | 'popular' | 'comments'
export interface MyActivityQuery {
  boardType?: CommunityBoardType
  sort?: MyActivitySort
  page?: number
  pageSize?: number
}

export interface CommunityListQuery {
  boardType?: CommunityBoardType
  sort?: CommunitySort
  q?: string
  productKind?: string
  isExample?: boolean
  mine?: boolean
  status?: 'draft' | 'published' | 'hidden'
  page?: number
  pageSize?: number
}

export interface CatalogProduct {
  id: string
  kind: string
  maker: string
  name: string
  model: string
  detail: string
  options: string[]
  image_url: string | null
}

const query = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? '?' + text : ''
}

/** '방금' · 'N분 전' · 'N시간 전' · 'N일 전' · 날짜 — 화면의 time 칸에 쓴다. */
export function relativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return ''
  const diff = Math.max(0, now - new Date(iso).getTime())
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '방금'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}일 전`
  return new Date(iso).toLocaleDateString('ko-KR')
}

/** 서버 응답 → CommunityPage 의 CommunityPost 모양(communityData.ts). */
export function mapCommunityItem(item: WireCommunityItem) {
  return {
    id: item.id,
    board: item.board_type,
    boardLabel: item.board_label,
    author: item.author.name,
    handle: '',
    time: relativeTime(item.published_at),
    title: item.title,
    excerpt: item.excerpt,
    comments: item.comment_count,
    likes: item.like_count,
    views: item.view_count,
    is_example: item.is_example,
    mediaCount: item.image_count,
    coverUrl: item.cover_image_url,
    likedByMe: item.liked_by_me,
    products: item.products.map(product => ({
      kind: product.product_kind,
      name: product.name ?? product.custom_product_name ?? '',
      detail: product.selected_option ?? '',
      imageUrl: product.image_url,
    })),
  }
}

export const communityApi = {
  list: (q: CommunityListQuery = {}) =>
    request<WireCommunityList>('GET', '/community/posts' + query({
      board_type: q.boardType, sort: q.sort, q: q.q, product_kind: q.productKind, is_example: q.isExample, mine: q.mine,
      status: q.status, page: q.page, page_size: q.pageSize,
    })),
  search: (q: string, page = 1, pageSize = 10, boardType?: CommunityBoardType) =>
    request<WireCommunityList>('GET', '/community/search' + query({ q, page, page_size: pageSize, board_type: boardType })),
  get: (id: string) => request<WireCommunityDetail>('GET', `/community/posts/${id}`),
  // 주변기기 추천이 인용한 문장(quote_id → 문장·글 id). 링크를 복사해 열거나 새로고침해서 라우터 state 가 없을 때 문장을 되찾는다.
  quote: (quoteId: string) => request<{ quote_id: string; post_id: string; sentence: string }>('GET', `/community/quotes/${encodeURIComponent(quoteId)}`),
  create: (input: CommunityPostInput) => request<WireCommunityDetail>('POST', '/community/posts', input),
  update: (id: string, input: Partial<CommunityPostInput> & { version?: number }) =>
    request<WireCommunityDetail>('PATCH', `/community/posts/${id}`, input),
  publish: (id: string, version?: number) => request<WireCommunityDetail>('POST', `/community/posts/${id}/publish`, { version }),
  remove: (id: string) => request<void>('DELETE', `/community/posts/${id}`),

  comments: (postId: string) => request<{ items: WireCommunityComment[]; total: number }>('GET', `/community/posts/${postId}/comments`),
  addComment: (postId: string, body: string) => request<WireCommunityComment>('POST', `/community/posts/${postId}/comments`, { body }),
  addReply: (commentId: string, body: string) => request<WireCommunityComment>('POST', `/community/comments/${commentId}/replies`, { body }),
  editComment: (commentId: string, body: string) => request<WireCommunityComment>('PATCH', `/community/comments/${commentId}`, { body }),
  removeComment: (commentId: string) => request<void>('DELETE', `/community/comments/${commentId}`),

  like: (postId: string) => request<{ post_id: string; like_count: number; liked_by_me: boolean }>('POST', `/community/posts/${postId}/likes`),
  unlike: (postId: string) => request<{ post_id: string; like_count: number; liked_by_me: boolean }>('DELETE', `/community/posts/${postId}/likes`),

  save: (postId: string) => request<{ post_id: string; saved_by_me: boolean }>('POST', `/community/posts/${postId}/save`),
  unsave: (postId: string) => request<{ post_id: string; saved_by_me: boolean }>('DELETE', `/community/posts/${postId}/save`),

  me: {
    summary: () => request<WireMyActivitySummary>('GET', '/community/me/summary'),
    comments: (q: MyActivityQuery = {}) =>
      request<WirePage<WireMyComment>>('GET', '/community/me/comments' + query({ board_type: q.boardType, sort: q.sort, page: q.page, page_size: q.pageSize })),
    likedPosts: (q: MyActivityQuery = {}) =>
      request<WirePage<WireMyPostItem>>('GET', '/community/me/liked-posts' + query({ board_type: q.boardType, sort: q.sort, page: q.page, page_size: q.pageSize })),
    savedPosts: (q: MyActivityQuery = {}) =>
      request<WirePage<WireMyPostItem>>('GET', '/community/me/saved-posts' + query({ board_type: q.boardType, sort: q.sort, page: q.page, page_size: q.pageSize })),
    notifications: (opts: { unread?: boolean; page?: number; pageSize?: number } = {}) =>
      request<WirePage<WireNotification> & { unread_count: number }>('GET', '/community/me/notifications' + query({ unread: opts.unread, page: opts.page, page_size: opts.pageSize })),
    unreadCount: () => request<{ unread_count: number }>('GET', '/community/me/notifications/unread-count'),
    markRead: (id: string) => request<{ id: string; read: boolean; unread_count: number }>('PATCH', `/community/me/notifications/${id}/read`),
    markAllRead: () => request<{ updated: number; unread_count: number }>('PATCH', '/community/me/notifications/read-all'),
  },

  /** 이미지 한 장을 올려 임시로 저장한다(글에 붙이려면 create/update 의 image_ids 에 넣는다). */
  uploadImage: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestForm<WireCommunityImage>('/community/uploads', form)
  },
  removeUpload: (imageId: string) => request<void>('DELETE', `/community/uploads/${imageId}`),

  catalogProducts: (kind: string, q = '', limit = 20) =>
    request<{ items: CatalogProduct[] }>('GET', '/catalog/products' + query({ kind, q, limit })),
}
