import { communityApi, type WireCommunityItem } from '../api/http/community'

/** 추천 제품의 "원문"으로 보여 줄 커뮤니티 글 */
export interface CommunitySource {
  id: string
  title: string
  excerpt: string
  coverUrl: string | null
  path: string
}

/** 글을 못 찾았을 때 가는 곳 */
export const COMMUNITY_REVIEW_BOARD = '/community?view=board&board=review'

const norm = (text: string) => text.toLowerCase().replace(/[^0-9a-z가-힣]/g, '')
const postPath = (id: string) => `/community?view=post&post=${encodeURIComponent(id)}`

function toSource(item: WireCommunityItem): CommunitySource {
  return { id: item.id, title: item.title, excerpt: item.excerpt, coverUrl: item.cover_image_url, path: postPath(item.id) }
}

/** 글에 연결된 제품 중 이 제품과 같은 이름이 있는지(한쪽이 다른 쪽을 포함하면 같은 것으로 본다) */
function linksProduct(item: WireCommunityItem, name: string): boolean {
  return item.products.some(product => {
    const other = norm(product.name ?? product.custom_product_name ?? '')
    return other !== '' && (name.includes(other) || other.includes(name))
  })
}

const cache = new Map<string, Promise<CommunitySource | null>>()

/**
 * 제품에 연결된 사용기 글을 커뮤니티 서버에서 찾는다. 같은 종류(키보드·마우스 …)의 사용기 중 연결 제품 이름이 같은 글을 먼저 보고,
 * 없으면 글 검색에서 제목·내용에 제품 이름이 들어 있는 첫 글을 쓴다. 못 찾으면 null — 서버 오류도 null 로 본다(원문 링크만 사용기 게시판으로 간다).
 */
export function findCommunitySource(productName: string, kindLabel: string): Promise<CommunitySource | null> {
  const name = norm(productName)
  if (!name) return Promise.resolve(null)
  const key = `${kindLabel}:${name}`
  const cached = cache.get(key)
  if (cached) return cached
  const found = (async () => {
    try {
      const linked = await communityApi.list({ boardType: 'review', productKind: kindLabel, sort: 'popular', pageSize: 50 })
      const hit = linked.items.find(item => linksProduct(item, name))
      if (hit) return toSource(hit)
      const searched = await communityApi.search(productName, 1, 10, 'review')
      const byText = searched.items.find(item => norm(`${item.title} ${item.excerpt}`).includes(name))
      return byText ? toSource(byText) : null
    } catch { return null }
  })()
  cache.set(key, found)
  // 실패해도 다음에 다시 찾을 수 있게, 못 찾은 결과는 오래 들고 있지 않는다.
  void found.then(source => { if (!source) window.setTimeout(() => cache.delete(key), 60_000) })
  return found
}
