import { useEffect, useMemo, useState, type DependencyList, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/types'
import {
  communityApi,
  mapCommunityItem,
  relativeTime,
  type CatalogProduct,
  type CommunityBoardType,
  type WireCommunityComment,
} from '../../api/http/community'
import MarketingHeader from '../../components/MarketingHeader'
import SiteFooter from '../../components/SiteFooter'
import { useAuthUser } from '../../state/authStore'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import {
  boardInfo,
  type CommunityBoard,
  type CommunityPost,
  type CommunityView,
} from './communityData'
import MarkdownBody from '../../components/MarkdownBody'
import BodyEditor from './BodyEditor'
import type { WireCommunityDetail, WireCommunityImage, WireCommunityProduct } from '../../api/http/community'
import '../../styles/community.css'

const validViews: CommunityView[] = ['home', 'board', 'post', 'write', 'search']
const boardOrder: CommunityBoard[] = ['all', 'question', 'review', 'tip', 'free']
const validBoards: CommunityBoard[] = ['all', 'popular', 'question', 'review', 'tip', 'free']

type Reaction = { liked: boolean; likes: number }
type ReactionOf = (post: Pick<CommunityPost, 'id' | 'likes' | 'likedByMe'>) => Reaction

const messageOf = (error: unknown) => (error instanceof ApiError ? error.message : '불러오지 못했습니다. 잠시 후 다시 시도해주세요.')

/** 서버에서 한 번 읽어 오는 값. deps 가 바뀌면 다시 읽고, 읽는 동안에는 이전 값을 그대로 둔다(화면이 깜빡이지 않게). */
function useAsync<T>(load: () => Promise<T>, deps: DependencyList) {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({ data: null, loading: true, error: null })
  useEffect(() => {
    let alive = true
    setState(current => ({ ...current, loading: true, error: null }))
    load().then(
      data => { if (alive) setState({ data, loading: false, error: null }) },
      error => { if (alive) setState({ data: null, loading: false, error: messageOf(error) }) },
    )
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

function useDebounced<T>(value: T, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** 좌측 메뉴의 게시판별 글 수 — 서버 목록의 total 을 쓴다. */
function useBoardCounts(version: number) {
  const [counts, setCounts] = useState<Record<string, number>>({})
  useEffect(() => {
    let alive = true
    Promise.all(boardOrder.map(board => communityApi.list({ boardType: board === 'all' ? undefined : (board as CommunityBoardType), pageSize: 1 }).then(result => [board, result.total] as const)))
      .then(entries => { if (alive) setCounts(Object.fromEntries(entries)) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [version])
  return counts
}

const boardOfCategory: Record<string, CommunityBoardType> = { '질문 · Q&A': 'question', '사용기 · 리뷰': 'review', '정보 · 팁': 'tip', '자유 게시판': 'free' }

interface SelectedProduct {
  key: string
  productId: string | null
  kind: string
  name: string
  detail: string
  options: string[]
  option: string
}

function SearchIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m16.2 16.2 4 4" /></svg>
}

function Avatar({ name }: { name: string }) {
  return <span className="cm-avatar" aria-hidden="true">{name.slice(0, 1)}</span>
}


function CategoryMenu({ current, counts, onSelect }: { current: CommunityBoard; counts: Record<string, number>; onSelect: (board: CommunityBoard) => void }) {
  const routerNavigate = useNavigate()
  const { resetPlan } = usePlan()
  const startFreshBuild = () => {
    resetPlan()
    routerNavigate('/start')
  }
  return (
    <aside className="cm-left-rail">
      <section className="cm-card cm-side-menu">
        <h2>커뮤니티</h2>
        {boardOrder.map(board => (
          <button key={board} type="button" className={'cm-side-link' + (current === board ? ' active' : '')} onClick={() => onSelect(board)}>
            <span>{boardInfo[board].label}</span>
            <small>{counts[board] ?? 0}</small>
          </button>
        ))}
      </section>
      <section className="cm-card cm-question-guide">
        <h2>처음 조립하시나요?</h2>
        <p>용도와 예산만 입력하면 AI가 나에게 딱 맞는 PC를 구성해 드려요.</p>
        <button type="button" onClick={startFreshBuild}>AI PC구성 바로가기</button>
      </section>
    </aside>
  )
}

function PostCard({ post, reaction, onOpen, onLike }: { post: CommunityPost; reaction: Reaction; onOpen: () => void; onLike: () => void }) {
  return (
    <article className="cm-post-row">
      <Avatar name={post.author} />
      <div className="cm-post-content">
        <div className="cm-post-head">
          <strong>{post.author}</strong>{post.handle && <span>{post.handle}</span>}<span>·</span><span>{post.time}</span>
          <span className="cm-post-badges">
            {post.is_example && <span className="cm-badge example">예시</span>}
            {post.badge && <span className="cm-badge accent">{post.badge}</span>}
          </span>
        </div>
        <div className="cm-post-category">{post.boardLabel}</div>
        <button type="button" className="cm-post-title" onClick={onOpen}>{post.title}</button>
        <p>{post.excerpt}</p>
        {post.coverUrl && (
          <div className="cm-cover" style={{ position: 'relative' }}>
            <img src={post.coverUrl} alt="" loading="lazy" onClick={onOpen} style={{ width: '100%', maxHeight: 320, objectFit: 'cover', borderRadius: 12, cursor: 'pointer', display: 'block' }} />
            {!!post.mediaCount && post.mediaCount > 1 && <span className="cm-badge" style={{ position: 'absolute', right: 8, bottom: 8 }}>+{post.mediaCount - 1}</span>}
          </div>
        )}
        {post.specs && <div className="cm-spec-row">{post.specs.map(spec => <div key={spec.label}><small>{spec.label}</small><strong>{spec.value}</strong></div>)}</div>}
        {!!post.products?.length && <div className="cm-linked-products">{post.products.map((product, index) => <span key={product.name + index}>{product.kind} · {product.name}</span>)}</div>}
        <div className="cm-post-actions">
          <button type="button" onClick={onOpen}>댓글 {post.comments}</button>
          <button type="button" className={reaction.liked ? 'liked' : ''} onClick={onLike} aria-pressed={reaction.liked}>♡ 추천 {reaction.likes}</button>
          <span>조회 {post.views}</span>
        </div>
      </div>
    </article>
  )
}

function getFeedReadingOffset(root: HTMLElement) {
  return Math.min(280, Math.max(220, root.clientHeight * .26))
}

function FeedSummary({ posts, mode, page, pageCount, activeId, onPage }: { posts: CommunityPost[]; mode: 'latest' | 'popular'; page: number; pageCount: number; activeId: string; onPage: (page: number) => void }) {
  const moveToPost = (postId: string) => {
    const root = document.querySelector<HTMLElement>('.cm-scroll')
    const post = document.getElementById(`cm-post-${postId}`)
    if (!root || !post) return
    const rootRect = root.getBoundingClientRect()
    const postRect = post.getBoundingClientRect()
    const readingOffset = getFeedReadingOffset(root)
    root.scrollTo({ top: root.scrollTop + postRect.top - rootRect.top - readingOffset + 2, behavior: 'auto' })
  }
  return (
    <aside className="cm-right-rail">
      <section className="cm-card cm-card-pad">
        <div className="cm-card-head"><h2>{mode === 'popular' ? '인기 글' : '최신 글'}</h2><span>{page} / {pageCount} 페이지</span></div>
        <ol className="cm-rank-list cm-feed-summary">{posts.map((post, index) => <li key={post.id} className={activeId === post.id ? 'current' : ''}><button type="button" aria-current={activeId === post.id ? 'true' : undefined} onClick={() => moveToPost(post.id)}>{post.title}</button><small>{(page - 1) * 10 + index + 1}</small></li>)}</ol>
        <Pagination page={page} pageCount={pageCount} onPage={onPage} compact />
      </section>
    </aside>
  )
}

// 맨앞 « · 이전 ‹ · 번호 · 다음 › · 맨뒤 ». 번호는 한 번에 10개(좁은 칸은 5개)만 보이고, 지금 쪽이 6번째 자리쯤 오도록 창이 같이 움직인다.
// 예) 1쪽: 1~10 · 11쪽: 6~15 · 마지막(25쪽 중) 21쪽: 16~25
function pageWindow(page: number, pageCount: number, size: number): number[] {
  const before = Math.floor(size / 2)
  const start = Math.max(1, Math.min(page - before, pageCount - size + 1))
  const end = Math.min(pageCount, start + size - 1)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
}

function Pagination({ page, pageCount, onPage, compact = false }: { page: number; pageCount: number; onPage: (page: number) => void; compact?: boolean }) {
  const numbers = pageWindow(page, pageCount, compact ? 5 : 10)
  const atFirst = page <= 1
  const atLast = page >= pageCount
  return (
    <nav className={'cm-pagination' + (compact ? ' compact' : '')} aria-label="페이지 이동">
      <button type="button" className="step" onClick={() => onPage(1)} disabled={atFirst} aria-label="첫 페이지">«</button>
      <button type="button" className="step" onClick={() => onPage(page - 1)} disabled={atFirst} aria-label="이전 페이지">‹</button>
      <span className="cm-pagination-pages">
        {numbers.map(number => <button type="button" key={number} className={page === number ? 'active' : ''} aria-current={page === number ? 'page' : undefined} onClick={() => onPage(number)}>{number}</button>)}
      </span>
      <button type="button" className="step" onClick={() => onPage(page + 1)} disabled={atLast} aria-label="다음 페이지">›</button>
      <button type="button" className="step" onClick={() => onPage(pageCount)} disabled={atLast} aria-label="마지막 페이지">»</button>
    </nav>
  )
}

export default function CommunityPage() {
  const [params, setParams] = useSearchParams()
  // 주변기기 견적 화면의 인용 문장에서 들어왔으면 그 문장(라우터 state)과 식별자(?quote=)가 따라온다.
  const quoteSentence = (useLocation().state as { quoteSentence?: unknown } | null)?.quoteSentence
  const quoteId = params.get('quote')
  const stateSentence = typeof quoteSentence === 'string' ? quoteSentence : null
  // 링크를 복사해 열거나 새로고침하면 라우터 state 가 없어서 ?quote= 만 남는다 — 그때는 서버에서 문장을 되찾는다(없거나 지워진 글이면 강조만 생략).
  const [fetchedQuote, setFetchedQuote] = useState<{ id: string; sentence: string } | null>(null)
  useEffect(() => {
    if (!quoteId || stateSentence) return
    let cancelled = false
    communityApi.quote(quoteId).then(found => { if (!cancelled) setFetchedQuote({ id: quoteId, sentence: found.sentence }) }).catch(() => {})
    return () => { cancelled = true }
  }, [quoteId, stateSentence])
  const quote = { id: quoteId, sentence: stateSentence ?? (fetchedQuote && fetchedQuote.id === quoteId ? fetchedQuote.sentence : null) }
  const { showToast } = useToast()
  const user = useAuthUser()
  const rawView = params.get('view') as CommunityView | null
  const view: CommunityView = rawView && validViews.includes(rawView) ? rawView : 'home'
  const rawBoard = params.get('board') as CommunityBoard | null
  const board: CommunityBoard = rawBoard && validBoards.includes(rawBoard) ? rawBoard : 'all'
  const postId = params.get('post') ?? ''
  const keyword = params.get('q') ?? ''
  const [searchText, setSearchText] = useState(keyword)
  const [feedMode, setFeedMode] = useState<'latest' | 'popular'>('latest')
  const [feedPage, setFeedPage] = useState(1)
  const [reactions, setReactions] = useState<Record<string, Reaction>>({})
  const [boardQuery, setBoardQuery] = useState('')
  const [boardPage, setBoardPage] = useState(1)
  const [dataVersion, setDataVersion] = useState(0)
  const counts = useBoardCounts(dataVersion)

  const navigate = (nextView: CommunityView, next?: { board?: CommunityBoard; post?: string; q?: string; edit?: string }) => {
    const nextParams = new URLSearchParams()
    if (nextView !== 'home') nextParams.set('view', nextView)
    if (next?.board) nextParams.set('board', next.board)
    if (next?.post) nextParams.set('post', next.post)
    if (next?.q) nextParams.set('q', next.q)
    if (next?.edit) nextParams.set('edit', next.edit)
    setParams(nextParams)
    document.querySelector('.cm-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const openBoard = (nextBoard: CommunityBoard) => navigate('board', { board: nextBoard })
  const openPost = (id: string) => navigate('post', { post: id })
  const reactionOf: ReactionOf = post => reactions[post.id] ?? { liked: post.likedByMe ?? false, likes: post.likes }
  const toggleLike = async (post: Pick<CommunityPost, 'id' | 'likes' | 'likedByMe'>) => {
    if (!user) { showToast('추천은 로그인 후 이용할 수 있어요.'); return }
    try {
      const result = reactionOf(post).liked ? await communityApi.unlike(post.id) : await communityApi.like(post.id)
      setReactions(current => ({ ...current, [post.id]: { liked: result.liked_by_me, likes: result.like_count } }))
    } catch (error) {
      showToast(messageOf(error))
    }
  }
  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    const value = searchText.trim()
    if (!value) return
    navigate('search', { q: value })
  }

  return (
    <div className="cm-scroll">
      <MarketingHeader />
      <div className="cm-subnav">
        <div>
          <button type="button" className={view === 'home' ? 'active' : ''} onClick={() => navigate('home')}>홈</button>
          <button type="button" className={view === 'board' && board === 'popular' ? 'active' : ''} onClick={() => openBoard('popular')}>인기</button>
          <form className="cm-global-search" onSubmit={submitSearch}>
            <SearchIcon /><input value={searchText} onChange={event => setSearchText(event.target.value)} placeholder="게시글과 제품 검색" aria-label="커뮤니티 검색" />
          </form>
        </div>
      </div>
      <main className="cm-main">
        {view === 'home' && (
          <HomeView counts={counts} feedMode={feedMode} feedPage={feedPage} reactionOf={reactionOf} onFeedMode={mode => { setFeedMode(mode); setFeedPage(1) }} onFeedPage={setFeedPage} onBoard={openBoard} onPost={openPost} onLike={toggleLike} onWrite={() => navigate('write')} />
        )}
        {view === 'board' && (
          <BoardView counts={counts} board={board} query={boardQuery} page={boardPage} onQuery={setBoardQuery} onPage={setBoardPage} onBoard={value => { setBoardPage(1); openBoard(value) }} onPost={openPost} onWrite={() => navigate('write')} />
        )}
        {view === 'post' && (postId
          ? <PostView postId={postId} quote={quote} user={user ? { name: user.name } : null} reactionOf={reactionOf} onBack={() => openBoard('all')} onBoard={openBoard} onPost={openPost} onWrite={() => navigate('write')} onEdit={() => navigate('write', { edit: postId })} onLike={toggleLike} onDeleted={() => { setDataVersion(value => value + 1); showToast('게시글을 삭제했습니다.'); openBoard('all') }} />
          : <p className="cm-empty">게시글을 선택해 주세요.</p>)}
        {view === 'write' && (params.get('edit')
          ? <EditPostLoader postId={params.get('edit') ?? ''} userName={user?.name ?? null} onCancel={() => openPost(params.get('edit') ?? '')} onDone={(id, edited) => { setDataVersion(value => value + 1); showToast(edited ? '수정했습니다.' : '게시했습니다.'); openPost(id) }} />
          : <WriteView userName={user?.name ?? null} onCancel={() => navigate('home')} onDone={(id, edited) => { setDataVersion(value => value + 1); showToast(edited ? '수정했습니다.' : '게시했습니다.'); openPost(id) }} />)}
        {view === 'search' && <SearchView keyword={keyword} onPost={openPost} onHome={() => navigate('home')} />}
      </main>
      <SiteFooter />
      <nav className="cm-mobile-nav" aria-label="커뮤니티 모바일 메뉴">
        <button type="button" className={view === 'home' ? 'active' : ''} onClick={() => navigate('home')}>⌂<span>홈</span></button>
        <button type="button" className={view === 'board' ? 'active' : ''} onClick={() => openBoard('all')}>⌕<span>탐색</span></button>
        <button type="button" className="write" onClick={() => navigate('write')}>＋<span>글쓰기</span></button>
        <Link to="/mypage">○<span>마이</span></Link>
      </nav>
    </div>
  )
}

function HomeView({ counts, feedMode, feedPage, reactionOf, onFeedMode, onFeedPage, onBoard, onPost, onLike, onWrite }: {
  counts: Record<string, number>; feedMode: 'latest' | 'popular'; feedPage: number; reactionOf: ReactionOf; onFeedMode: (mode: 'latest' | 'popular') => void; onFeedPage: (page: number) => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onLike: (post: CommunityPost) => void; onWrite: () => void
}) {
  const feed = useAsync(() => communityApi.list({ sort: feedMode, page: feedPage, pageSize: 10 }), [feedMode, feedPage])
  const posts = useMemo<CommunityPost[]>(() => feed.data?.items.map(mapCommunityItem) ?? [], [feed.data])
  const pageCount = Math.max(1, feed.data?.total_pages ?? 1)
  const page = feed.data?.page ?? feedPage
  const [activeId, setActiveId] = useState(posts[0]?.id ?? '')
  useEffect(() => {
    setActiveId(posts[0]?.id ?? '')
    const root = document.querySelector<HTMLElement>('.cm-scroll')
    const elements = posts.map(post => document.getElementById(`cm-post-${post.id}`)).filter((element): element is HTMLElement => Boolean(element))
    if (!root || elements.length === 0) return
    let frame = 0
    const update = () => {
      frame = 0
      const rootRect = root.getBoundingClientRect()
      const readingLine = rootRect.top + getFeedReadingOffset(root)
      const reachedBottom = root.scrollTop + root.clientHeight >= root.scrollHeight - 4
      const containing = elements.find(element => {
        const rect = element.getBoundingClientRect()
        return rect.top <= readingLine && rect.bottom > readingLine
      })
      const nearest = reachedBottom ? elements[elements.length - 1] : containing ?? elements.reduce((closest, element) => {
        const rect = element.getBoundingClientRect()
        const distance = readingLine < rect.top ? rect.top - readingLine : readingLine > rect.bottom ? readingLine - rect.bottom : 0
        return !closest || distance < closest.distance ? { element, distance } : closest
      }, null as { element: HTMLElement; distance: number } | null)?.element
      const nextId = nearest?.id.replace('cm-post-', '')
      if (nextId) setActiveId(current => current === nextId ? current : nextId)
    }
    const queueUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(update)
    }
    root.addEventListener('scroll', queueUpdate, { passive: true })
    window.addEventListener('resize', queueUpdate)
    update()
    return () => {
      root.removeEventListener('scroll', queueUpdate)
      window.removeEventListener('resize', queueUpdate)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [posts])
  return (
    <>
      <div className="cm-layout">
        <CategoryMenu current="all" counts={counts} onSelect={onBoard} />
        <div className="cm-stack">
          <section className="cm-card cm-intro">
            <div><span>오늘의 커뮤니티</span><h1>고민은 짧게, 좋은 선택은 함께.</h1><p>실사용자의 경험을 한곳에서 확인하세요.</p></div>
            <div className="cm-intro-actions"><button type="button" className="cm-btn" onClick={() => onBoard('popular')}>인기 글 보기</button></div>
          </section>
          <section className="cm-card cm-feed">
            <div className="cm-feed-tabs"><button type="button" className={feedMode === 'latest' ? 'active' : ''} onClick={() => onFeedMode('latest')}>최신 글</button><button type="button" className={feedMode === 'popular' ? 'active' : ''} onClick={() => onFeedMode('popular')}>인기 글</button></div>
            <button type="button" className="cm-composer" onClick={onWrite}><Avatar name="나" /><span>궁금한 점이나 사용 경험을 공유해보세요.</span><b>글쓰기</b></button>
            {feed.error && <p className="cm-empty">{feed.error}</p>}
            {!feed.error && !feed.loading && posts.length === 0 && <p className="cm-empty">아직 게시글이 없습니다. 첫 글을 남겨보세요.</p>}
            {!feed.error && feed.loading && posts.length === 0 && <p className="cm-empty">불러오는 중…</p>}
            {posts.map(post => <div id={`cm-post-${post.id}`} className={'cm-feed-post-anchor' + (activeId === post.id ? ' current' : '')} key={post.id}><PostCard post={post} reaction={reactionOf(post)} onOpen={() => onPost(post.id)} onLike={() => onLike(post)} /></div>)}
            <Pagination page={page} pageCount={pageCount} onPage={next => { onFeedPage(next); document.querySelector('.cm-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} />
          </section>
        </div>
        <FeedSummary posts={posts} mode={feedMode} page={page} pageCount={pageCount} activeId={activeId} onPage={onFeedPage} />
      </div>
    </>
  )
}

function BoardView({ counts, board, query, page, onQuery, onPage, onBoard, onPost, onWrite }: {
  counts: Record<string, number>; board: CommunityBoard; query: string; page: number; onQuery: (value: string) => void; onPage: (page: number) => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onWrite: () => void
}) {
  const [sort, setSort] = useState<'latest' | 'views' | 'recommend'>(board === 'popular' ? 'recommend' : 'latest')
  const debounced = useDebounced(query.trim())
  const list = useAsync(() => communityApi.list({
    boardType: board === 'all' || board === 'popular' ? undefined : (board as CommunityBoardType),
    sort,
    q: debounced || undefined,
    page,
    pageSize: 10,
  }), [board, debounced, page, sort])
  const rows = useMemo<CommunityPost[]>(() => list.data?.items.map(mapCommunityItem) ?? [], [list.data])
  const total = list.data?.total ?? 0
  const pageCount = Math.max(1, list.data?.total_pages ?? 1)
  return (
    <>
      <header className="cm-page-head"><div><span>Community Board</span><h1>{boardInfo[board].label}</h1><p>{boardInfo[board].description}</p></div><div><button type="button" className="cm-btn" onClick={() => onBoard('all')}>전체 피드</button><button type="button" className="cm-btn primary" onClick={onWrite}>글쓰기</button></div></header>
      <div className="cm-mobile-chips">{boardOrder.map(value => <button key={value} type="button" className={board === value ? 'active' : ''} onClick={() => onBoard(value)}>{boardInfo[value].label}</button>)}</div>
      <div className="cm-layout cm-board-layout">
        <CategoryMenu current={board} counts={counts} onSelect={onBoard} />
        <section className="cm-card cm-board-card">
          <div className="cm-filter"><strong>{boardInfo[board].label} <small>{total}개</small></strong><div className="cm-filter-tools"><label><SearchIcon /><input value={query} onChange={event => { onQuery(event.target.value); onPage(1) }} placeholder="게시판 내 검색" /></label><select aria-label="게시글 정렬" value={sort} onChange={event => { setSort(event.target.value as typeof sort); onPage(1) }}><option value="latest">등록일 순</option><option value="views">조회 순</option><option value="recommend">추천 순</option></select></div></div>
          <div className="cm-table-head"><span>분류</span><span>제목</span><span>작성자</span><span>조회</span><span>추천</span></div>
          {list.error ? <p className="cm-empty">{list.error}</p> : rows.length ? rows.map(post => <button type="button" className="cm-board-row" key={post.id} onClick={() => onPost(post.id)}><span>{post.boardLabel}</span><span><span className="cm-board-title-line"><strong>{post.title}</strong>{post.is_example && <span className="cm-badge example">예시</span>}</span><small>{post.excerpt}</small></span><span>{post.author}</span><span>{post.views}</span><span>{post.likes}</span></button>) : <p className="cm-empty">{list.loading ? '불러오는 중…' : '검색 결과가 없습니다.'}</p>}
          <Pagination page={Math.min(page, pageCount)} pageCount={pageCount} onPage={onPage} />
        </section>
        <aside className="cm-right-rail"><section className="cm-card cm-card-pad"><div className="cm-card-head"><h2>게시판 안내</h2></div><p>{boardInfo[board].description}</p><button type="button" className="cm-btn primary block" onClick={onWrite}>새 글 작성</button></section></aside>
      </div>
    </>
  )
}

function PostView({ postId, quote, user, reactionOf, onBack, onBoard, onPost, onWrite, onEdit, onLike, onDeleted }: {
  postId: string; quote: { id: string | null; sentence: string | null }; user: { name: string } | null; reactionOf: ReactionOf; onBack: () => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onWrite: () => void; onEdit: () => void; onLike: (post: CommunityPost) => void; onDeleted: () => void
}) {
  const { showToast } = useToast()
  const detail = useAsync(() => communityApi.get(postId), [postId])
  const [comments, setComments] = useState<WireCommunityComment[]>([])
  const [commentText, setCommentText] = useState('')
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [replyText, setReplyText] = useState('')
  // 저장(북마크): 처음 값은 글 응답의 saved_by_me, 누른 뒤에는 서버가 돌려준 값.
  const [savedOverride, setSavedOverride] = useState<boolean | null>(null)
  const [savingPost, setSavingPost] = useState(false)
  const loadComments = () => communityApi.comments(postId).then(result => setComments(result.items)).catch(error => showToast(messageOf(error)))
  useEffect(() => {
    setComments([])
    setReplyTo(null)
    setSavedOverride(null)
    loadComments()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postId])

  const wire = detail.data
  const post = useMemo(() => (wire ? mapCommunityItem(wire) : null), [wire])
  const nameOf = (comment: WireCommunityComment) => comment.author?.name ?? '알 수 없음'
  const commentTotal = comments.reduce((sum, comment) => sum + (comment.is_deleted ? 0 : 1) + (comment.replies ?? []).filter(reply => !reply.is_deleted).length, 0)
  const run = async (action: () => Promise<unknown>, failure?: () => void) => {
    try { await action(); return true } catch (error) { showToast(messageOf(error)); failure?.(); return false }
  }
  const submitComment = async (event: FormEvent) => {
    event.preventDefault()
    if (!user) { showToast('댓글 작성은 로그인 후 이용할 수 있어요.'); return }
    const text = commentText.trim()
    if (!text) return
    if (await run(() => communityApi.addComment(postId, text))) { setCommentText(''); await loadComments() }
  }
  const submitReply = async (commentId: string) => {
    if (!user) { showToast('답글 작성은 로그인 후 이용할 수 있어요.'); return }
    const text = replyText.trim()
    if (!text) return
    if (await run(() => communityApi.addReply(commentId, text))) { setReplyText(''); setReplyTo(null); await loadComments() }
  }
  const removeComment = async (commentId: string) => {
    if (await run(() => communityApi.removeComment(commentId))) await loadComments()
  }
  const toggleSave = async (current: boolean) => {
    if (!user) { showToast('글 저장은 로그인 후 이용할 수 있어요.'); return }
    if (savingPost) return
    setSavingPost(true)
    try {
      const result = current ? await communityApi.unsave(postId) : await communityApi.save(postId)
      setSavedOverride(result.saved_by_me)
      showToast(result.saved_by_me ? '저장했어요. 마이페이지 > 나의 커뮤니티에서 볼 수 있어요.' : '저장을 해제했어요.')
    } catch (error) { showToast(messageOf(error)) } finally { setSavingPost(false) }
  }
  // 이 글로 바로 들어오는 주소(인용 문장 등 다른 값은 빼고)를 복사한다. 보안 연결이 아닌 주소에서는 navigator.clipboard 가 없어서 대체 방법을 쓴다.
  const copyLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}?view=post&post=${encodeURIComponent(postId)}`
    let copied = false
    try {
      await navigator.clipboard.writeText(url)
      copied = true
    } catch {
      const box = document.createElement('textarea')
      box.value = url
      box.setAttribute('readonly', '')
      box.style.cssText = 'position:fixed;top:0;left:0;opacity:0'
      document.body.appendChild(box)
      box.select()
      try { copied = document.execCommand('copy') } catch { copied = false }
      document.body.removeChild(box)
    }
    showToast(copied ? '글 주소를 복사했어요.' : '주소를 복사하지 못했어요. 주소창의 주소를 직접 복사해 주세요.')
  }
  const removePost = async () => {
    if (!window.confirm('이 게시글을 삭제할까요?')) return
    if (await run(() => communityApi.remove(postId))) onDeleted()
  }

  if (!wire || !post) {
    return (
      <>
        <header className="cm-page-head"><div><span>Community</span><h1>게시글 상세</h1></div><div><button type="button" className="cm-btn" onClick={onBack}>목록으로</button></div></header>
        <p className="cm-empty">{detail.error ?? '불러오는 중…'}</p>
      </>
    )
  }
  const reaction = reactionOf(post)
  const saved = savedOverride ?? wire.saved_by_me ?? false
  const renderComment = (comment: WireCommunityComment, reply = false, parent?: WireCommunityComment) => (
    <article className={reply ? 'cm-reply' : undefined} key={comment.id}>
      <Avatar name={nameOf(comment)} />
      <div>
        <strong>{nameOf(comment)}</strong><small>{relativeTime(comment.created_at)}{comment.edited ? ' · 수정됨' : ''}</small>
        <p>{reply && parent && <b>@{nameOf(parent)} </b>}{comment.body}</p>
        {!reply && !comment.is_deleted && <button type="button" className="cm-reply-button" onClick={() => { setReplyTo(current => current === comment.id ? null : comment.id); setReplyText('') }}>답글</button>}
        {comment.is_mine && !comment.is_deleted && <button type="button" className="cm-reply-button" onClick={() => removeComment(comment.id)}>삭제</button>}
      </div>
    </article>
  )
  return (
    <>
      <header className="cm-page-head"><div><span>{post.boardLabel}</span><h1>게시글 상세</h1><p>본문과 댓글에 집중하는 읽기 화면입니다.</p></div><div><button type="button" className="cm-btn" onClick={onBack}>목록으로</button><button type="button" className="cm-btn primary" onClick={onWrite}>글쓰기</button></div></header>
      <div className="cm-detail-grid">
        <div className="cm-stack">
          <article className="cm-card cm-article">
            <span className="cm-badge accent">{post.boardLabel}</span><h1>{post.title}</h1>
            {!!post.products?.length && <section className="cm-product-cards"><h2>연결 제품</h2>{post.products.map((product, index) => <div key={product.name + index} className="cm-product-card">{product.imageUrl && <img src={product.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={event => { event.currentTarget.style.display = 'none' }} style={{ width: 56, height: 56, objectFit: 'contain', borderRadius: 8, flex: 'none' }} />}<span>{product.kind}</span><div><strong>{product.name}</strong><small>{product.detail}</small></div></div>)}</section>}
            <div className="cm-article-meta"><span><Avatar name={post.author} /><span><strong>{post.author}</strong><small>{post.time}</small></span></span><span>조회 {wire.view_count} · 댓글 {commentTotal}</span></div>
            {post.is_example && <div className="review-disclosure" role="note"><strong>예시 리뷰</strong><span>서비스 구성을 보여주기 위해 팀이 작성한 글입니다. 실제 구매·사용 후기가 아닙니다.</span></div>}
            <div className="cm-article-body">
              <MarkdownBody key={wire.id} body={wire.body} images={wire.images} quoteSentence={quote.sentence} />
            </div>
            <div className="cm-article-actions"><button type="button" className={reaction.liked ? 'active' : ''} onClick={() => onLike(post)}>♡ 추천 {reaction.likes}</button><button type="button" className={saved ? 'active' : ''} aria-pressed={saved} disabled={savingPost} onClick={() => toggleSave(saved)}>{saved ? '★ 저장됨' : '☆ 저장'}</button><button type="button" onClick={copyLink}>공유</button>{wire.can_edit && <button type="button" onClick={onEdit}>수정</button>}{wire.can_delete && <button type="button" onClick={removePost}>삭제</button>}</div>
          </article>
          <section className="cm-card cm-comments">
            <h2>댓글 <span>{commentTotal}</span></h2>
            {comments.map(comment => <div className="cm-comment-thread" key={comment.id}>{renderComment(comment)}{(comment.replies ?? []).map(reply => renderComment(reply, true, comment))}{replyTo === comment.id && <form className="cm-reply-form" onSubmit={event => { event.preventDefault(); submitReply(comment.id) }}><Avatar name={user?.name ?? '나'} /><div><textarea value={replyText} onChange={event => setReplyText(event.target.value)} placeholder={`${nameOf(comment)}님에게 답글 남기기`} /><span><button type="button" className="cm-btn" onClick={() => setReplyTo(null)}>취소</button><button type="submit" className="cm-btn primary">답글 등록</button></span></div></form>}</div>)}
            <form onSubmit={submitComment}><Avatar name={user?.name ?? '나'} /><div><textarea value={commentText} onChange={event => setCommentText(event.target.value)} placeholder={user ? '댓글을 남겨보세요' : '로그인 후 댓글을 작성할 수 있어요'} /><button type="submit" className="cm-btn primary">댓글 등록</button></div></form>
          </section>
          <PostBoardList currentPostId={post.id} initialBoard={post.board} onPost={onPost} onBoard={onBoard} onWrite={onWrite} />
        </div>
      </div>
    </>
  )
}

function PostBoardList({ currentPostId, initialBoard, onPost, onBoard, onWrite }: { currentPostId: string; initialBoard: CommunityBoard; onPost: (id: string) => void; onBoard: (board: CommunityBoard) => void; onWrite: () => void }) {
  const [activeBoard, setActiveBoard] = useState<CommunityBoard>(initialBoard)
  const [sort, setSort] = useState<'latest' | 'views' | 'recommend'>('latest')
  const [draftQuery, setDraftQuery] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const tabs: Array<{ key: CommunityBoard; label: string }> = [{ key: 'all', label: '전체' }, { key: 'question', label: '질문' }, { key: 'free', label: '잡담' }, { key: 'tip', label: '정보' }, { key: 'review', label: '구매인증' }]
  const list = useAsync(() => communityApi.list({ boardType: activeBoard === 'all' ? undefined : (activeBoard as CommunityBoardType), sort, q: query || undefined, page, pageSize: 10 }), [activeBoard, sort, query, page])
  const pageRows = useMemo<CommunityPost[]>(() => list.data?.items.map(mapCommunityItem) ?? [], [list.data])
  const pageCount = Math.max(1, list.data?.total_pages ?? 1)
  const currentPage = Math.min(page, pageCount)
  return (
    <section className="cm-card cm-post-board">
      <div className="cm-post-board-tabs">{tabs.map(tab => <button type="button" key={tab.key} className={activeBoard === tab.key ? 'active' : ''} onClick={() => { setActiveBoard(tab.key); setPage(1); setQuery(''); setDraftQuery('') }}>{tab.label}</button>)}</div>
      <div className="cm-post-board-head"><div><h2>{boardInfo[activeBoard].label} 글 목록</h2><p>{boardInfo[activeBoard].description}</p></div><button type="button" className="cm-btn" onClick={() => onBoard(activeBoard)}>전체 목록</button></div>
      <div className="cm-table-head"><span>분류</span><span>제목</span><span>작성자</span><span>조회</span><span>추천</span></div>
      {list.error ? <p className="cm-empty">{list.error}</p> : pageRows.length ? pageRows.map(item => <button type="button" key={item.id} className={'cm-board-row' + (item.id === currentPostId ? ' current' : '')} onClick={() => onPost(item.id)}><span>{item.boardLabel}</span><span><span className="cm-board-title-line"><strong>{item.title}</strong>{item.is_example && <span className="cm-badge example">예시</span>}</span><small>댓글 [{item.comments}]</small></span><span>{item.author}</span><span>{item.views}</span><span>{item.likes}</span></button>) : <p className="cm-empty">{list.loading ? '불러오는 중…' : '검색 결과가 없습니다.'}</p>}
      <div className="cm-post-board-tools"><select value={sort} onChange={event => { setSort(event.target.value as typeof sort); setPage(1) }}><option value="latest">등록일 순</option><option value="views">조회 순</option><option value="recommend">추천 순</option></select><button type="button" className="cm-btn primary" onClick={onWrite}>✎ 글쓰기</button></div>
      <div className="cm-post-board-footer"><Pagination page={currentPage} pageCount={pageCount} onPage={setPage} /><form onSubmit={event => { event.preventDefault(); setQuery(draftQuery.trim()); setPage(1) }}><input value={draftQuery} onChange={event => setDraftQuery(event.target.value)} placeholder="제목·내용·작성자 검색" /><button type="submit" className="cm-btn">검색</button></form></div>
    </section>
  )
}

const MARKER_LINE = /\]\(image:([0-9a-f-]{8,})\)/gi

/** 본문에 마커가 남아 있는 이미지만, 본문에 나온 순서대로(첫 이미지가 대표). 마커가 사라진 이미지는 글에서 빠진다. */
function usedImages(body: string, images: WireCommunityImage[]): WireCommunityImage[] {
  const byId = new Map(images.map(image => [image.id.toLowerCase(), image]))
  const seen = new Set<string>()
  const result: WireCommunityImage[] = []
  for (const match of body.matchAll(MARKER_LINE)) {
    const id = match[1].toLowerCase()
    const image = byId.get(id)
    if (image && !seen.has(id)) { seen.add(id); result.push(image) }
  }
  return result
}

function productToSelected(product: WireCommunityProduct): SelectedProduct {
  const name = product.name ?? product.custom_product_name ?? ''
  return {
    key: product.product_id ?? `custom:${product.product_kind}:${name}`, productId: product.product_id, kind: product.product_kind, name,
    detail: product.brand ? product.brand : `${product.product_kind} · 목록에 없는 제품`, options: [], option: product.selected_option ?? '',
  }
}

function WriteView({ userName, editing, onCancel, onDone }: { userName: string | null; editing?: WireCommunityDetail; onCancel: () => void; onDone: (id: string, edited: boolean) => void }) {
  const { showToast } = useToast()
  const [category, setCategory] = useState(() => (editing ? (Object.keys(boardOfCategory).find(key => boardOfCategory[key] === editing.board_type) ?? '') : ''))
  const [title, setTitle] = useState(editing?.title ?? '')
  const [body, setBody] = useState(editing?.body ?? '')
  const [productKind, setProductKind] = useState('모니터')
  const [productQuery, setProductQuery] = useState('')
  const [unlistedName, setUnlistedName] = useState('')
  const [selected, setSelected] = useState<SelectedProduct[]>(() => (editing ? editing.products.map(productToSelected) : []))
  const [results, setResults] = useState<CatalogProduct[]>([])
  const [saving, setSaving] = useState(false)
  const [images, setImages] = useState<WireCommunityImage[]>(editing?.images ?? [])

  useEffect(() => {
    const query = productQuery.trim()
    if (!query) { setResults([]); return }
    let alive = true
    const timer = window.setTimeout(() => {
      communityApi.catalogProducts(productKind, query, 20).then(result => { if (alive) setResults(result.items) }).catch(() => { if (alive) setResults([]) })
    }, 250)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [productQuery, productKind])

  const add = (item: SelectedProduct) => {
    setSelected(current => {
      if (current.some(value => value.key === item.key)) return current.filter(value => value.key !== item.key)
      if (current.length >= 5) { showToast('제품은 최대 5개까지 추가할 수 있습니다.'); return current }
      return [...current, item]
    })
  }
  const toggleCatalog = (product: CatalogProduct) => add({ key: product.id, productId: product.id, kind: productKind, name: product.name, detail: `${product.maker} · ${product.detail}`, options: product.options, option: '' })
  const addUnlisted = () => {
    const name = unlistedName.trim()
    if (!name) return
    add({ key: `custom:${productKind}:${name}`, productId: null, kind: productKind, name, detail: `${productKind} · 목록에 없는 제품`, options: [], option: '' })
    setUnlistedName('')
  }
  const setOption = (key: string, option: string) => setSelected(current => current.map(item => item.key === key ? { ...item, option } : item))

  const fields = () => ({
    board_type: boardOfCategory[category],
    title: title.trim(),
    body: body.trim(),
    products: category === '자유 게시판' ? [] : selected.map(item => ({ product_id: item.productId, product_kind: item.kind, custom_product_name: item.productId ? null : item.name, selected_option: item.option.trim() || null })),
    image_ids: usedImages(body, images).map(image => image.id),
  })
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!userName) { showToast('글 작성은 로그인 후 이용할 수 있어요.'); return }
    if (!category) { showToast('게시판을 선택해 주세요.'); return }
    if (!body.trim()) { showToast('내용을 입력해 주세요.'); return }
    if (category === '사용기 · 리뷰' && selected.length === 0) { showToast('사용기 · 리뷰는 제품을 1개 이상 추가해 주세요.'); return }
    setSaving(true)
    try {
      if (editing) {
        const updated = await communityApi.update(editing.id, { ...fields(), version: editing.version })
        onDone(updated.id, true)
      } else {
        const created = await communityApi.create({ ...fields(), publish: true })
        onDone(created.id, false)
      }
    } catch (error) {
      showToast(messageOf(error))
    } finally {
      setSaving(false)
    }
  }
  return (
    <>
      <header className="cm-page-head"><div><span>{editing ? 'Edit' : 'Create'}</span><h1>{editing ? '글 수정' : '새 글 작성'}</h1>{editing && <p>내용을 고친 뒤 수정 완료를 눌러 주세요.</p>}</div><button type="button" className="cm-btn" onClick={onCancel}>취소</button></header>
      {!userName && <div className="cm-login-callout">게시 기능은 로그인이 필요합니다. <Link to="/login">로그인하기</Link></div>}
      <form className="cm-card cm-write-form" onSubmit={submit}>
        <label>게시판<select required value={category} onChange={event => setCategory(event.target.value)}><option value="">게시판 선택</option><option>질문 · Q&A</option><option>사용기 · 리뷰</option><option>정보 · 팁</option><option>자유 게시판</option></select></label>
        {category !== '자유 게시판' && <>
          <label>제품 종류<select value={productKind} onChange={event => { setProductKind(event.target.value); setProductQuery('') }}><option>모니터</option><option>키보드</option><option>마우스</option><option>스피커</option></select></label>
          <fieldset className="full"><legend>연결 제품 <small>{category === '사용기 · 리뷰' ? '1개 이상 필수' : '선택'} · {selected.length} / 5개</small></legend><div className="cm-product-entry"><label>제품 검색<input value={productQuery} onChange={event => setProductQuery(event.target.value)} placeholder="제조사 또는 모델명 입력" /></label><label>목록에 없는 제품<span><input value={unlistedName} onChange={event => setUnlistedName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addUnlisted() } }} placeholder="제조사와 모델명을 입력하세요" /><button type="button" className="cm-btn" onClick={addUnlisted}>추가</button></span></label></div>{productQuery ? <div className="cm-product-results">{results.length ? results.map(product => { const on = selected.some(item => item.key === product.id); return <button type="button" key={product.id} className={on ? 'selected' : ''} onClick={() => toggleCatalog(product)}><span><strong>{product.name}</strong><small>{product.maker} · {product.detail}</small></span><b>{on ? '추가됨' : '추가'}</b></button> }) : <p>검색 결과가 없습니다. 목록에 없는 제품으로 추가할 수 있습니다.</p>}</div> : <p className="cm-product-help">검색어를 입력하면 선택한 제품 종류의 카탈로그가 표시됩니다.</p>}<div className="cm-selected-product-cards">{selected.map(item => <div key={item.key}><span><strong>{item.name}</strong><small>{item.productId ? `${item.kind} · ${item.detail}` : item.detail}</small></span><label>옵션 (선택)<input value={item.option} list={item.options.length ? `options-${item.key}` : undefined} onChange={event => setOption(item.key, event.target.value)} placeholder="예: 저소음 적축, 색상" />{item.options.length > 0 && <datalist id={`options-${item.key}`}>{item.options.map(option => <option value={option} key={option} />)}</datalist>}</label><button type="button" className="cm-btn" onClick={() => add(item)}>삭제</button></div>)}</div>{category === '사용기 · 리뷰' && <p className="cm-review-notice">사용기 글의 내용은 제품 추천에 참고 자료로 활용될 수 있습니다.</p>}</fieldset>
        </>}
        <label className="full">제목<input required maxLength={80} value={title} onChange={event => setTitle(event.target.value)} placeholder="내용을 구체적으로 알 수 있는 제목을 입력하세요" /></label>
        <div className="full cm-body-field">
          <label htmlFor="cm-write-body">내용</label>
          <BodyEditor userName={userName} initial={editing ? { body: editing.body, images: editing.images } : undefined} onChange={(next, used) => { setBody(next); setImages(used) }} />
        </div>
        <div className="cm-form-actions full"><button type="button" className="cm-btn" onClick={onCancel}>취소</button><button type="submit" className="cm-btn primary" disabled={saving}>{editing ? '수정 완료' : '게시하기'}</button></div>
      </form>
    </>
  )
}

function EditPostLoader({ postId, userName, onCancel, onDone }: { postId: string; userName: string | null; onCancel: () => void; onDone: (id: string, edited: boolean) => void }) {
  const detail = useAsync(() => communityApi.get(postId), [postId])
  const wire = detail.data
  if (!wire) {
    return (
      <>
        <header className="cm-page-head"><div><span>Edit</span><h1>글 수정</h1></div><button type="button" className="cm-btn" onClick={onCancel}>취소</button></header>
        <p className="cm-empty">{detail.error ?? '불러오는 중…'}</p>
      </>
    )
  }
  if (!wire.can_edit) {
    return (
      <>
        <header className="cm-page-head"><div><span>Edit</span><h1>글 수정</h1></div><button type="button" className="cm-btn" onClick={onCancel}>돌아가기</button></header>
        <p className="cm-empty">이 글은 수정할 수 없어요. 내가 쓴 글만 고칠 수 있습니다.</p>
      </>
    )
  }
  return <WriteView key={wire.id} userName={userName} editing={wire} onCancel={onCancel} onDone={onDone} />
}

function SearchView({ keyword, onPost, onHome }: { keyword: string; onPost: (id: string) => void; onHome: () => void }) {
  const search = useAsync(() => (keyword.trim() ? communityApi.search(keyword.trim(), 1, 30) : Promise.resolve(null)), [keyword])
  const results = useMemo<CommunityPost[]>(() => search.data?.items.map(mapCommunityItem) ?? [], [search.data])
  const total = search.data?.total ?? 0
  return (
    <><header className="cm-page-head"><div><span>Search</span><h1>통합 검색</h1><p>커뮤니티 게시글을 제목, 내용, 작성자, 태그, 연결 제품으로 찾습니다.</p></div></header><section className="cm-card cm-search-results"><h2>‘{keyword || '검색어'}’ 검색 결과 <small>{total}개</small></h2>{search.error ? <p className="cm-empty">{search.error}</p> : results.length ? results.map(post => <button type="button" key={post.id} onClick={() => onPost(post.id)}><span>{post.boardLabel}</span><strong>{post.title}</strong><small>{post.excerpt}</small></button>) : search.loading ? <p className="cm-empty">불러오는 중…</p> : <div className="cm-empty"><b>검색 결과가 없습니다.</b><p>다른 키워드로 다시 검색해보세요.</p><button type="button" className="cm-btn primary" onClick={onHome}>홈으로 돌아가기</button></div>}</section></>
  )
}
