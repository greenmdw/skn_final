import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage } from '../../api'
import { communityApi, relativeTime, type WireCommunityItem, type WireCommunityList } from '../../api/http/community'
import type { MyCommunityActivity, MyCommunityFilter, MyCommunitySort, MyCommunityTab } from './myCommunityTypes'

type CommunityState = { published: WireCommunityList | null; loading: boolean; error: string }

const initialState: CommunityState = { published: null, loading: true, error: '' }
const PAGE_SIZE = 3
const TAB_LABELS: Array<[MyCommunityTab, string]> = [
  ['posts', '작성한 글'], ['comments', '작성한 댓글'], ['liked', '추천한 글'], ['saved', '저장한 글'],
]
// 서버 API(GET /community/me/comments, /liked-posts, /saved-posts)는 준비돼 있지만 화면은 아직 연결 전인 탭. 샘플을 보여 주지 않고 준비 중 안내만 낸다(요청서: 개발요청_커뮤니티_마이페이지_백엔드).
const PENDING_TAB: Record<Exclude<MyCommunityTab, 'posts'>, string> = {
  comments: '내가 쓴 댓글 목록', liked: '추천한 글 목록', saved: '저장한 글 목록',
}
const FILTERS: Array<[MyCommunityFilter, string]> = [
  ['all', '전체'], ['question', '질문'], ['review', '사용기'], ['tip', '정보'], ['free', '자유'],
]

const boardLabel = (type: WireCommunityItem['board_type']) => ({ question: '질문', review: '사용기', tip: '정보', free: '자유' })[type]

function postActivity(post: WireCommunityItem): MyCommunityActivity {
  return {
    id: post.id, postId: post.id, type: post.board_type, label: boardLabel(post.board_type), title: post.title,
    description: post.excerpt, date: post.published_at ?? '', views: post.view_count, likes: post.like_count,
    comments: post.comment_count, status: post.board_type === 'question' ? '답변 확인' : '게시 중',
  }
}

export default function MyCommunityPage() {
  const [state, setState] = useState<CommunityState>(initialState)
  const [tab, setTab] = useState<MyCommunityTab>('posts')
  const [filter, setFilter] = useState<MyCommunityFilter>('all')
  const [sort, setSort] = useState<MyCommunitySort>('latest')
  const [page, setPage] = useState(1)

  useEffect(() => {
    let active = true
    communityApi.list({ mine: true, status: 'published', page: 1, pageSize: 50 }).then(published => {
      if (active) setState({ published, loading: false, error: '' })
    }).catch(error => {
      if (active) setState({ published: null, loading: false, error: errorMessage(error, '내가 작성한 글을 불러오지 못했어요.') })
    })
    return () => { active = false }
  }, [])

  const posts = useMemo(() => (state.published?.items ?? []).map(postActivity), [state.published])
  const pending = tab !== 'posts'
  const rows = useMemo(() => {
    const filtered = filter === 'all' ? posts : posts.filter(item => item.type === filter)
    return [...filtered].sort((a, b) => {
      if (sort === 'popular') return b.likes - a.likes
      if (sort === 'comments') return b.comments - a.comments
      return new Date(b.date).getTime() - new Date(a.date).getTime()
    })
  }, [filter, sort, posts])
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const visibleRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const receivedComments = posts.reduce((sum, post) => sum + post.comments, 0)
  const receivedLikes = posts.reduce((sum, post) => sum + post.likes, 0)
  const postCount = state.published?.total ?? posts.length

  function changeTab(next: MyCommunityTab) { setTab(next); setFilter('all'); setPage(1) }
  function changeFilter(next: MyCommunityFilter) { setFilter(next); setPage(1) }

  return (
    <>
      <header className="mpc-head">
        <div><span>MY COMMUNITY</span><h1>나의 커뮤니티</h1><p>최근 반응과 이어서 확인할 활동을 먼저 보여줍니다.</p></div>
        <Link className="mp-btn primary mp-link-btn" to="/community?view=write">새 글 작성</Link>
      </header>

      {state.error && <div className="mp-alert" role="alert">{state.error}</div>}

      <div className="mpc-layout">
        <section className="mp-section mpc-activity">
          <div className="mp-section-head"><h2>확인할 새 활동</h2></div>
          <div className="mp-empty-card mpc-empty-compact"><strong>알림 기능은 준비 중이에요</strong><span>내 글에 댓글이 달리거나 내 댓글에 답글이 달리면 여기에 보여 드릴 예정이에요.</span></div>
        </section>

        <aside className="mp-section mpc-summary">
          <h2>내 활동</h2>
          <dl>
            <div><dt>작성한 글</dt><dd>{state.loading ? '…' : `${postCount}개`}</dd></div>
            <div><dt>작성한 댓글</dt><dd>준비 중</dd></div>
            <div><dt>받은 댓글</dt><dd>{state.loading ? '…' : `${receivedComments}개`}</dd></div>
            <div><dt>받은 추천</dt><dd>{state.loading ? '…' : `${receivedLikes}개`}</dd></div>
          </dl>
        </aside>
      </div>

      <section className="mp-section mpc-manager">
        <nav className="mpc-tabs" aria-label="나의 커뮤니티 활동">
          {TAB_LABELS.map(([id, label]) => <button type="button" key={id} className={tab === id ? 'on' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => changeTab(id)}>{label} {id === 'posts' && !state.loading && <b>{postCount}</b>}</button>)}
        </nav>
        {!pending && <div className="mpc-toolbar">
          <div className="mpc-filters" aria-label="게시글 유형 필터">
            {FILTERS.map(([id, label]) => <button type="button" key={id} className={filter === id ? 'on' : ''} onClick={() => changeFilter(id)}>{label}</button>)}
          </div>
          <select value={sort} aria-label="정렬 기준" onChange={event => { setSort(event.target.value as MyCommunitySort); setPage(1) }}>
            <option value="latest">최신순</option><option value="popular">추천순</option><option value="comments">댓글순</option>
          </select>
        </div>}

        {pending ? <div className="mp-empty-card mpc-empty-compact"><strong>{PENDING_TAB[tab]}은 준비 중이에요</strong><span>서버 기능이 준비되면 이곳에 실제 활동이 보여요.</span></div> : state.loading ? <div className="mp-empty-card mpc-empty-compact"><strong>작성한 글을 불러오는 중이에요</strong></div> : visibleRows.length ? (
          <div className="mpc-activity-list">{visibleRows.map(item => <ActivityRow key={item.id} item={item} />)}</div>
        ) : (
          <div className="mp-empty-card mpc-empty-compact"><strong>해당 유형의 활동이 없어요</strong><span>다른 필터를 선택해 보세요.</span></div>
        )}
        {!pending && pageCount > 1 && <nav className="mpc-pagination" aria-label="페이지 이동">
          <button type="button" disabled={page === 1} onClick={() => setPage(value => Math.max(1, value - 1))}>‹</button>
          {Array.from({ length: pageCount }, (_, index) => <button type="button" key={index} className={page === index + 1 ? 'on' : ''} onClick={() => setPage(index + 1)}>{index + 1}</button>)}
          <button type="button" disabled={page === pageCount} onClick={() => setPage(value => Math.min(pageCount, value + 1))}>›</button>
        </nav>}
      </section>
    </>
  )
}

function ActivityRow({ item }: { item: MyCommunityActivity }) {
  const target = item.postId ? `/community?view=post&post=${encodeURIComponent(item.postId)}` : '/community'
  const date = item.date ? (item.date.includes('T') ? relativeTime(item.date) : item.date.replaceAll('-', '.')) : ''
  return (
    <article className="mpc-activity-row">
      <span className={`mpc-board ${item.type}`}>{item.label}</span>
      <span className="mpc-activity-copy"><Link to={target}>{item.title}</Link><p>{item.description}</p><small>{date} · 조회 {item.views.toLocaleString()} · 추천 {item.likes} · 댓글 {item.comments}</small></span>
      <span className="mpc-status">{item.status}</span>
      <Link className="mpc-more" to={target}>보기 〉</Link>
    </article>
  )
}
