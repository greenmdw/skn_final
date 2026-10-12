import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import MarketingHeader from '../../components/MarketingHeader'
import { useAuthUser } from '../../state/authStore'
import { usePlan } from '../../state/PlanContext'
import { useToast } from '../../state/ToastContext'
import {
  boardInfo,
  communityPosts,
  deals,
  productCatalog,
  type CommunityBoard,
  type CommunityPost,
  type CommunityView,
} from './communityData'
import '../../styles/community.css'

const validViews: CommunityView[] = ['home', 'board', 'post', 'write', 'deals', 'search']
const boardOrder: CommunityBoard[] = ['all', 'question', 'review', 'tip', 'free']
const validBoards: CommunityBoard[] = ['all', 'popular', 'question', 'review', 'tip', 'free']

interface CommunityComment {
  id: string
  author: string
  body: string
  time: string
  replies: Array<{ id: string; author: string; body: string; time: string }>
}

function SearchIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m16.2 16.2 4 4" /></svg>
}

function Avatar({ name }: { name: string }) {
  return <span className="cm-avatar" aria-hidden="true">{name.slice(0, 1)}</span>
}

function ExampleNotice() {
  return (
    <div className="cm-example-notice" role="note">
      <span>프론트 예시</span>
      게시글·댓글·추천 데이터는 화면 구조 확인용이며 아직 서버에 저장되지 않습니다.
    </div>
  )
}

function CategoryMenu({ current, onSelect }: { current: CommunityBoard; onSelect: (board: CommunityBoard) => void }) {
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
            <small>{board === 'all' ? communityPosts.length : communityPosts.filter(post => post.board === board).length}</small>
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

function PostCard({ post, liked, onOpen, onLike }: { post: CommunityPost; liked: boolean; onOpen: () => void; onLike: () => void }) {
  return (
    <article className="cm-post-row">
      <Avatar name={post.author} />
      <div className="cm-post-content">
        <div className="cm-post-head">
          <strong>{post.author}</strong><span>{post.handle}</span><span>·</span><span>{post.time}</span>
          <span className="cm-post-badges">
            {post.is_example && <span className="cm-badge example">예시</span>}
            {post.badge && <span className="cm-badge accent">{post.badge}</span>}
          </span>
        </div>
        <div className="cm-post-category">{post.boardLabel}</div>
        <button type="button" className="cm-post-title" onClick={onOpen}>{post.title}</button>
        <p>{post.excerpt}</p>
        {!!post.mediaCount && (
          <div className={'cm-media-grid count-' + post.mediaCount} aria-label={`첨부 이미지 ${post.mediaCount}장`}>
            {Array.from({ length: post.mediaCount }, (_, index) => <span key={index}>이미지 {index + 1}</span>)}
          </div>
        )}
        {post.specs && <div className="cm-spec-row">{post.specs.map(spec => <div key={spec.label}><small>{spec.label}</small><strong>{spec.value}</strong></div>)}</div>}
        {post.products && <div className="cm-linked-products">{post.products.map(product => <span key={product.name}>{product.kind} · {product.name}</span>)}</div>}
        <div className="cm-post-actions">
          <button type="button" onClick={onOpen}>댓글 {post.comments}</button>
          <button type="button" className={liked ? 'liked' : ''} onClick={onLike} aria-pressed={liked}>♡ 추천 {post.likes + (liked ? 1 : 0)}</button>
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

function Pagination({ page, pageCount, onPage, compact = false }: { page: number; pageCount: number; onPage: (page: number) => void; compact?: boolean }) {
  return <nav className={'cm-pagination' + (compact ? ' compact' : '')} aria-label="페이지 이동"><button type="button" onClick={() => onPage(page - 1)} disabled={page === 1}>‹</button>{Array.from({ length: pageCount }, (_, index) => <button type="button" key={index} className={page === index + 1 ? 'active' : ''} aria-current={page === index + 1 ? 'page' : undefined} onClick={() => onPage(index + 1)}>{index + 1}</button>)}<button type="button" onClick={() => onPage(page + 1)} disabled={page === pageCount}>›</button></nav>
}

export default function CommunityPage() {
  const [params, setParams] = useSearchParams()
  const { showToast } = useToast()
  const user = useAuthUser()
  const rawView = params.get('view') as CommunityView | null
  const view: CommunityView = rawView && validViews.includes(rawView) ? rawView : 'home'
  const rawBoard = params.get('board') as CommunityBoard | null
  const board: CommunityBoard = rawBoard && validBoards.includes(rawBoard) ? rawBoard : 'all'
  const postId = params.get('post') ?? communityPosts[0].id
  const keyword = params.get('q') ?? ''
  const [searchText, setSearchText] = useState(keyword)
  const [feedMode, setFeedMode] = useState<'latest' | 'popular'>('latest')
  const [feedPage, setFeedPage] = useState(1)
  const [liked, setLiked] = useState<Set<string>>(() => new Set())
  const [boardQuery, setBoardQuery] = useState('')
  const [boardPage, setBoardPage] = useState(1)
  const [comments, setComments] = useState<CommunityComment[]>([
    { id: 'comment-1', author: '렌더팜', body: '편집 비중이 높다면 메모리 64GB는 유지하는 편이 좋습니다. 파워는 GPU 제조사 권장 용량도 같이 확인하세요.', time: '12분 전', replies: [] },
    { id: 'comment-2', author: '조립도우미', body: '케이스의 CPU 쿨러 높이 제한과 메모리 간섭 여부를 먼저 확인해보세요.', time: '7분 전', replies: [{ id: 'reply-1', author: '쿨링연구소', body: '메모리 방열판 높이도 함께 보면 좋습니다.', time: '4분 전' }] },
  ])
  const [commentText, setCommentText] = useState('')
  const [writeCategory, setWriteCategory] = useState('')
  const [writeTitle, setWriteTitle] = useState('')
  const [writeBody, setWriteBody] = useState('')
  const [productQuery, setProductQuery] = useState('')
  const [selectedProducts, setSelectedProducts] = useState<string[]>([])

  const navigate = (nextView: CommunityView, next?: { board?: CommunityBoard; post?: string; q?: string }) => {
    const nextParams = new URLSearchParams()
    if (nextView !== 'home') nextParams.set('view', nextView)
    if (next?.board) nextParams.set('board', next.board)
    if (next?.post) nextParams.set('post', next.post)
    if (next?.q) nextParams.set('q', next.q)
    setParams(nextParams)
    document.querySelector('.cm-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const openBoard = (nextBoard: CommunityBoard) => navigate('board', { board: nextBoard })
  const openPost = (id: string) => navigate('post', { post: id })
  const toggleLike = (id: string) => {
    setLiked(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    showToast('추천 상태는 이 브라우저 화면에서만 유지됩니다.')
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
          <button type="button" className={view === 'deals' ? 'active' : ''} onClick={() => navigate('deals')}>프로모션</button>
          <form className="cm-global-search" onSubmit={submitSearch}>
            <SearchIcon /><input value={searchText} onChange={event => setSearchText(event.target.value)} placeholder="게시글과 제품 검색" aria-label="커뮤니티 검색" />
          </form>
        </div>
      </div>
      <main className="cm-main">
        {view === 'home' && (
          <HomeView feedMode={feedMode} feedPage={feedPage} liked={liked} onFeedMode={mode => { setFeedMode(mode); setFeedPage(1) }} onFeedPage={setFeedPage} onBoard={openBoard} onPost={openPost} onLike={toggleLike} onWrite={() => navigate('write')} onDeals={() => navigate('deals')} />
        )}
        {view === 'board' && (
          <BoardView board={board} query={boardQuery} page={boardPage} onQuery={setBoardQuery} onPage={setBoardPage} onBoard={value => { setBoardPage(1); openBoard(value) }} onPost={openPost} onWrite={() => navigate('write')} />
        )}
        {view === 'post' && (
          <PostView postId={postId} liked={liked.has(postId)} comments={comments} commentText={commentText} userName={user?.name ?? null} onBack={() => openBoard('all')} onBoard={openBoard} onPost={openPost} onWrite={() => navigate('write')} onLike={() => toggleLike(postId)} onCommentText={setCommentText} onComment={event => {
            event.preventDefault()
            if (!user) { showToast('댓글 작성은 로그인 후 이용할 수 있어요.'); return }
            if (!commentText.trim()) return
            setComments(current => [...current, { id: `comment-${Date.now()}`, author: user.name, body: commentText.trim(), time: '방금', replies: [] }])
            setCommentText('')
            showToast('댓글은 현재 화면에서만 추가되었습니다.')
          }} onReply={(commentId, text) => {
            if (!user) { showToast('답글 작성은 로그인 후 이용할 수 있어요.'); return false }
            setComments(current => current.map(comment => comment.id === commentId ? { ...comment, replies: [...comment.replies, { id: `reply-${Date.now()}`, author: user.name, body: text, time: '방금' }] } : comment))
            showToast('답글은 현재 화면에서만 추가되었습니다.')
            return true
          }} />
        )}
        {view === 'write' && (
          <WriteView userName={user?.name ?? null} category={writeCategory} title={writeTitle} body={writeBody} productQuery={productQuery} selectedProducts={selectedProducts} onCategory={setWriteCategory} onTitle={setWriteTitle} onBody={setWriteBody} onProductQuery={setProductQuery} onToggleProduct={id => setSelectedProducts(current => {
            if (current.includes(id)) return current.filter(value => value !== id)
            if (current.length >= 5) { showToast('제품은 최대 5개까지 추가할 수 있습니다.'); return current }
            return [...current, id]
          })} onDraft={() => showToast('임시 저장 API가 없어 현재 화면에만 유지됩니다.')} onCancel={() => navigate('home')} onSubmit={event => {
            event.preventDefault()
            if (!user) { showToast('글 작성은 로그인 후 이용할 수 있어요.'); return }
            if (writeCategory === '사용기 · 리뷰' && selectedProducts.length === 0) { showToast('사용기 · 리뷰는 제품을 1개 이상 추가해 주세요.'); return }
            showToast('게시글 저장 API가 없어 아직 게시할 수 없습니다.')
          }} />
        )}
        {view === 'deals' && <DealsView onWrite={() => navigate('write')} onUnavailable={() => showToast('프로모션 상세 API는 아직 연결되지 않았습니다.')} />}
        {view === 'search' && <SearchView keyword={keyword} onPost={openPost} onHome={() => navigate('home')} />}
      </main>
      <nav className="cm-mobile-nav" aria-label="커뮤니티 모바일 메뉴">
        <button type="button" className={view === 'home' ? 'active' : ''} onClick={() => navigate('home')}>⌂<span>홈</span></button>
        <button type="button" className={view === 'board' ? 'active' : ''} onClick={() => openBoard('all')}>⌕<span>탐색</span></button>
        <button type="button" className="write" onClick={() => navigate('write')}>＋<span>글쓰기</span></button>
        <button type="button" className={view === 'deals' ? 'active' : ''} onClick={() => navigate('deals')}>％<span>프로모션</span></button>
        <Link to="/mypage">○<span>마이</span></Link>
      </nav>
    </div>
  )
}

function HomeView({ feedMode, feedPage, liked, onFeedMode, onFeedPage, onBoard, onPost, onLike, onWrite, onDeals }: {
  feedMode: 'latest' | 'popular'; feedPage: number; liked: Set<string>; onFeedMode: (mode: 'latest' | 'popular') => void; onFeedPage: (page: number) => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onLike: (id: string) => void; onWrite: () => void; onDeals: () => void
}) {
  const latestOrder = ['mouse-review', 'keyboard-review', 'build-check-200', 'mini-pc-review', 'cooling-tip', 'white-setup', 'gpu-game', 'qhd-monitor']
  const latest = [...communityPosts].sort((a, b) => {
    const aIndex = latestOrder.indexOf(a.id)
    const bIndex = latestOrder.indexOf(b.id)
    return (aIndex < 0 ? 999 : aIndex) - (bIndex < 0 ? 999 : bIndex)
  })
  const ordered = feedMode === 'popular' ? [...communityPosts].sort((a, b) => b.likes - a.likes) : latest
  const pageSize = 10
  const pageCount = Math.max(1, Math.ceil(ordered.length / pageSize))
  const page = Math.min(feedPage, pageCount)
  const posts = ordered.slice((page - 1) * pageSize, page * pageSize)
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
  }, [feedMode, page])
  return (
    <>
      <ExampleNotice />
      <div className="cm-layout">
        <CategoryMenu current="all" onSelect={onBoard} />
        <div className="cm-stack">
          <section className="cm-card cm-intro">
            <div><span>오늘의 커뮤니티</span><h1>고민은 짧게, 좋은 선택은 함께.</h1><p>실사용자의 경험부터 최저가 정보까지 한곳에서 확인하세요.</p></div>
            <div className="cm-intro-actions"><button type="button" className="cm-btn" onClick={() => onBoard('popular')}>인기 글 보기</button><button type="button" className="cm-btn primary" onClick={onDeals}>프로모션 보기</button></div>
          </section>
          <section className="cm-card cm-feed">
            <div className="cm-feed-tabs"><button type="button" className={feedMode === 'latest' ? 'active' : ''} onClick={() => onFeedMode('latest')}>최신 글</button><button type="button" className={feedMode === 'popular' ? 'active' : ''} onClick={() => onFeedMode('popular')}>인기 글</button></div>
            <button type="button" className="cm-composer" onClick={onWrite}><Avatar name="나" /><span>궁금한 점이나 사용 경험을 공유해보세요.</span><b>글쓰기</b></button>
            {posts.map(post => <div id={`cm-post-${post.id}`} className={'cm-feed-post-anchor' + (activeId === post.id ? ' current' : '')} key={post.id}><PostCard post={post} liked={liked.has(post.id)} onOpen={() => onPost(post.id)} onLike={() => onLike(post.id)} /></div>)}
            <Pagination page={page} pageCount={pageCount} onPage={next => { onFeedPage(next); document.querySelector('.cm-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} />
          </section>
        </div>
        <FeedSummary posts={posts} mode={feedMode} page={page} pageCount={pageCount} activeId={activeId} onPage={onFeedPage} />
      </div>
    </>
  )
}

function BoardView({ board, query, page, onQuery, onPage, onBoard, onPost, onWrite }: {
  board: CommunityBoard; query: string; page: number; onQuery: (value: string) => void; onPage: (page: number) => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onWrite: () => void
}) {
  const boardPosts = board === 'popular' ? [...communityPosts].sort((a, b) => b.likes - a.likes).slice(0, 12) : communityPosts.filter(post => board === 'all' || post.board === board)
  const filtered = boardPosts.filter(post => !query.trim() || `${post.title} ${post.author}`.toLowerCase().includes(query.trim().toLowerCase()))
  const pageSize = 6
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)
  return (
    <>
      <header className="cm-page-head"><div><span>Community Board</span><h1>{boardInfo[board].label}</h1><p>{boardInfo[board].description}</p></div><div><button type="button" className="cm-btn" onClick={() => onBoard('all')}>전체 피드</button><button type="button" className="cm-btn primary" onClick={onWrite}>글쓰기</button></div></header>
      <ExampleNotice />
      <div className="cm-mobile-chips">{boardOrder.map(value => <button key={value} type="button" className={board === value ? 'active' : ''} onClick={() => onBoard(value)}>{boardInfo[value].label}</button>)}</div>
      <div className="cm-layout cm-board-layout">
        <CategoryMenu current={board} onSelect={onBoard} />
        <section className="cm-card cm-board-card">
          <div className="cm-filter"><strong>{boardInfo[board].label} <small>{filtered.length}개</small></strong><label><SearchIcon /><input value={query} onChange={event => { onQuery(event.target.value); onPage(1) }} placeholder="게시판 내 검색" /></label></div>
          <div className="cm-table-head"><span>분류</span><span>제목</span><span>작성자</span><span>조회</span><span>추천</span></div>
          {rows.length ? rows.map(post => <button type="button" className="cm-board-row" key={post.id} onClick={() => onPost(post.id)}><span>{post.boardLabel}</span><span><span className="cm-board-title-line"><strong>{post.title}</strong>{post.is_example && <span className="cm-badge example">예시</span>}</span><small>{post.excerpt}</small></span><span>{post.author}</span><span>{post.views}</span><span>{post.likes}</span></button>) : <p className="cm-empty">검색 결과가 없습니다.</p>}
          <Pagination page={Math.min(page, pageCount)} pageCount={pageCount} onPage={onPage} />
        </section>
        <aside className="cm-right-rail"><section className="cm-card cm-card-pad"><div className="cm-card-head"><h2>게시판 안내</h2></div><p>{boardInfo[board].description}</p><button type="button" className="cm-btn primary block" onClick={onWrite}>새 글 작성</button></section></aside>
      </div>
    </>
  )
}

function PostView({ postId, liked, comments, commentText, userName, onBack, onBoard, onPost, onWrite, onLike, onCommentText, onComment, onReply }: {
  postId: string; liked: boolean; comments: CommunityComment[]; commentText: string; userName: string | null; onBack: () => void; onBoard: (board: CommunityBoard) => void; onPost: (id: string) => void; onWrite: () => void; onLike: () => void; onCommentText: (value: string) => void; onComment: (event: FormEvent) => void; onReply: (commentId: string, text: string) => boolean
}) {
  const post = communityPosts.find(item => item.id === postId) ?? communityPosts[0]
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [replyText, setReplyText] = useState('')
  return (
    <>
      <header className="cm-page-head"><div><span>{post.boardLabel}</span><h1>게시글 상세</h1><p>본문과 댓글에 집중하는 읽기 화면입니다.</p></div><div><button type="button" className="cm-btn" onClick={onBack}>목록으로</button><button type="button" className="cm-btn primary" onClick={onWrite}>글쓰기</button></div></header>
      <div className="cm-detail-grid">
        <div className="cm-stack">
          <article className="cm-card cm-article">
            <span className="cm-badge accent">{post.boardLabel}</span><h1>{post.title}</h1>
            {post.products && <section className="cm-product-cards"><h2>연결 제품</h2>{post.products.map(product => <div key={product.name} className="cm-product-card"><span>{product.kind}</span><div><strong>{product.name}</strong><small>{product.detail}</small></div></div>)}</section>}
            <div className="cm-article-meta"><span><Avatar name={post.author} /><span><strong>{post.author}</strong><small>{post.time}</small></span></span><span>조회 {post.views} · 댓글 {post.comments}</span></div>
            {post.is_example && <div className="review-disclosure" role="note"><strong>예시 리뷰</strong><span>서비스 구성을 보여주기 위해 팀이 작성한 글입니다. 실제 구매·사용 후기가 아닙니다.</span></div>}
            <div className="cm-article-body">
              <p>{post.excerpt}</p>
              {post.mediaCount && <div className="cm-article-photo">게시글 이미지 영역</div>}
              {post.specs && <div className="cm-spec-box">{post.specs.map(spec => <div key={spec.label}><small>{spec.label}</small><strong>{spec.value}</strong></div>)}</div>}
              {post.board === 'question' ? <><p>예산과 사용 목적을 기준으로 호환성과 비용 배분을 함께 확인하고 싶습니다. 교체가 필요한 부품이 있다면 이유도 알려주세요.</p><blockquote>사용 목적과 실제 제품 모델에 따라 답변이 달라질 수 있습니다.</blockquote></> : <p>직접 사용하며 확인한 내용과 장단점을 정리했습니다. 다른 환경에서의 경험도 댓글로 공유해주세요.</p>}
            </div>
            <div className="cm-article-actions"><button type="button" className={liked ? 'active' : ''} onClick={onLike}>♡ 추천 {post.likes + (liked ? 1 : 0)}</button><button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>공유</button></div>
          </article>
          <section className="cm-card cm-comments">
            <h2>댓글 <span>{comments.length + comments.reduce((sum, comment) => sum + comment.replies.length, 0)}</span></h2>
            {comments.map(comment => <div className="cm-comment-thread" key={comment.id}><article><Avatar name={comment.author} /><div><strong>{comment.author}</strong><small>{comment.time}</small><p>{comment.body}</p><button type="button" className="cm-reply-button" onClick={() => { setReplyTo(current => current === comment.id ? null : comment.id); setReplyText('') }}>답글</button></div></article>{comment.replies.map(reply => <article className="cm-reply" key={reply.id}><Avatar name={reply.author} /><div><strong>{reply.author}</strong><small>{reply.time}</small><p><b>@{comment.author}</b> {reply.body}</p></div></article>)}{replyTo === comment.id && <form className="cm-reply-form" onSubmit={event => { event.preventDefault(); if (replyText.trim() && onReply(comment.id, replyText.trim())) { setReplyText(''); setReplyTo(null) } }}><Avatar name={userName ?? '나'} /><div><textarea value={replyText} onChange={event => setReplyText(event.target.value)} placeholder={`${comment.author}님에게 답글 남기기`} /><span><button type="button" className="cm-btn" onClick={() => setReplyTo(null)}>취소</button><button type="submit" className="cm-btn primary">답글 등록</button></span></div></form>}</div>)}
            <form onSubmit={onComment}><Avatar name={userName ?? '나'} /><div><textarea value={commentText} onChange={event => onCommentText(event.target.value)} placeholder={userName ? '댓글을 남겨보세요' : '로그인 후 댓글을 작성할 수 있어요'} /><button type="submit" className="cm-btn primary">댓글 등록</button></div></form>
          </section>
          <PostBoardList currentPostId={post.id} initialBoard={post.board} onPost={onPost} onBoard={onBoard} onWrite={onWrite} />
        </div>
        <aside className="cm-right-rail"><section className="cm-card cm-card-pad"><div className="cm-card-head"><h2>게시글 요약</h2></div><dl className="cm-summary"><div><dt>분류</dt><dd>{post.boardLabel}</dd></div><div><dt>작성자</dt><dd>{post.author}</dd></div><div><dt>상태</dt><dd>{post.badge ?? '의견 모집 중'}</dd></div></dl></section></aside>
      </div>
    </>
  )
}

function PostBoardList({ currentPostId, initialBoard, onPost, onBoard, onWrite }: { currentPostId: string; initialBoard: CommunityBoard; onPost: (id: string) => void; onBoard: (board: CommunityBoard) => void; onWrite: () => void }) {
  const [activeBoard, setActiveBoard] = useState<CommunityBoard>(initialBoard)
  const [sort, setSort] = useState<'latest' | 'views' | 'recommend'>('latest')
  const [searchField, setSearchField] = useState<'title' | 'author'>('title')
  const [draftQuery, setDraftQuery] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const tabs: Array<{ key: CommunityBoard; label: string }> = [{ key: 'all', label: '전체' }, { key: 'question', label: '질문' }, { key: 'free', label: '잡담' }, { key: 'tip', label: '정보' }, { key: 'review', label: '구매인증' }]
  let rows = communityPosts.filter(post => activeBoard === 'all' || post.board === activeBoard).filter(post => !query || (searchField === 'author' ? post.author : post.title).toLowerCase().includes(query.toLowerCase()))
  if (sort === 'views') rows = [...rows].sort((a, b) => b.views - a.views)
  if (sort === 'recommend') rows = [...rows].sort((a, b) => b.likes - a.likes)
  const pageSize = 6
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  return (
    <section className="cm-card cm-post-board">
      <div className="cm-post-board-tabs">{tabs.map(tab => <button type="button" key={tab.key} className={activeBoard === tab.key ? 'active' : ''} onClick={() => { setActiveBoard(tab.key); setPage(1); setQuery(''); setDraftQuery('') }}>{tab.label}</button>)}</div>
      <div className="cm-post-board-head"><div><h2>{boardInfo[activeBoard].label} 글 목록</h2><p>{boardInfo[activeBoard].description}</p></div><button type="button" className="cm-btn" onClick={() => onBoard(activeBoard)}>전체 목록</button></div>
      <div className="cm-table-head"><span>분류</span><span>제목</span><span>작성자</span><span>조회</span><span>추천</span></div>
      {pageRows.length ? pageRows.map(item => <button type="button" key={item.id} className={'cm-board-row' + (item.id === currentPostId ? ' current' : '')} onClick={() => onPost(item.id)}><span>{item.boardLabel}</span><span><span className="cm-board-title-line"><strong>{item.title}</strong>{item.is_example && <span className="cm-badge example">예시</span>}</span><small>댓글 [{item.comments}]</small></span><span>{item.author}</span><span>{item.views}</span><span>{item.likes}</span></button>) : <p className="cm-empty">검색 결과가 없습니다.</p>}
      <div className="cm-post-board-tools"><select value={sort} onChange={event => { setSort(event.target.value as typeof sort); setPage(1) }}><option value="latest">등록일 순</option><option value="views">조회 순</option><option value="recommend">추천 순</option></select><button type="button" className="cm-btn primary" onClick={onWrite}>✎ 글쓰기</button></div>
      <div className="cm-post-board-footer"><Pagination page={currentPage} pageCount={pageCount} onPage={setPage} /><form onSubmit={event => { event.preventDefault(); setQuery(draftQuery.trim()); setPage(1) }}><select value={searchField} onChange={event => setSearchField(event.target.value as typeof searchField)}><option value="title">제목검색</option><option value="author">작성자검색</option></select><input value={draftQuery} onChange={event => setDraftQuery(event.target.value)} placeholder="검색어를 입력해주세요." /><button type="submit" className="cm-btn">검색</button></form></div>
    </section>
  )
}

function WriteView({ userName, category, title, body, productQuery, selectedProducts, onCategory, onTitle, onBody, onProductQuery, onToggleProduct, onDraft, onCancel, onSubmit }: {
  userName: string | null; category: string; title: string; body: string; productQuery: string; selectedProducts: string[]; onCategory: (value: string) => void; onTitle: (value: string) => void; onBody: (value: string) => void; onProductQuery: (value: string) => void; onToggleProduct: (id: string) => void; onDraft: () => void; onCancel: () => void; onSubmit: (event: FormEvent) => void
}) {
  const [productKind, setProductKind] = useState('모니터')
  const [unlistedName, setUnlistedName] = useState('')
  const [options, setOptions] = useState<Record<string, string>>({})
  const [tags, setTags] = useState('')
  const matchingProducts = productCatalog.filter(product => product.kind === productKind && `${product.maker} ${product.name}`.toLowerCase().includes(productQuery.trim().toLowerCase()))
  const addUnlisted = () => {
    const name = unlistedName.trim()
    if (!name) return
    onToggleProduct(`custom:${productKind}:${name}`)
    setUnlistedName('')
  }
  return (
    <>
      <header className="cm-page-head"><div><span>Create</span><h1>새 글 작성</h1><p>필수 입력만 남겨 작성 부담을 낮췄습니다.</p></div><button type="button" className="cm-btn" onClick={onCancel}>취소</button></header>
      <ExampleNotice />
      {!userName && <div className="cm-login-callout">게시 기능은 로그인이 필요합니다. <Link to="/login">로그인하기</Link></div>}
      <form className="cm-card cm-write-form" onSubmit={onSubmit}>
        <label>게시판<select required value={category} onChange={event => onCategory(event.target.value)}><option value="">게시판 선택</option><option>질문 · Q&A</option><option>사용기 · 리뷰</option><option>정보 · 팁</option><option>자유 게시판</option></select></label>
        <label>제품 종류<select value={productKind} onChange={event => { setProductKind(event.target.value); onProductQuery('') }}><option>모니터</option><option>키보드</option><option>마우스</option><option>스피커</option></select></label>
        <fieldset className="full"><legend>연결 제품 <small>{category === '사용기 · 리뷰' ? '1개 이상 필수' : '선택'} · {selectedProducts.length} / 5개</small></legend><div className="cm-product-entry"><label>제품 검색<input value={productQuery} onChange={event => onProductQuery(event.target.value)} placeholder="제조사 또는 모델명 입력" /></label><label>목록에 없는 제품<span><input value={unlistedName} onChange={event => setUnlistedName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addUnlisted() } }} placeholder="제조사와 모델명을 입력하세요" /><button type="button" className="cm-btn" onClick={addUnlisted}>추가</button></span></label></div>{productQuery ? <div className="cm-product-results">{matchingProducts.length ? matchingProducts.map(product => <button type="button" key={product.id} className={selectedProducts.includes(product.id) ? 'selected' : ''} onClick={() => onToggleProduct(product.id)}><span><strong>{product.name}</strong><small>{product.maker} · {product.detail}</small></span><b>{selectedProducts.includes(product.id) ? '추가됨' : '추가'}</b></button>) : <p>검색 결과가 없습니다. 목록에 없는 제품으로 추가할 수 있습니다.</p>}</div> : <p className="cm-product-help">검색어를 입력하면 선택한 제품 종류의 카탈로그가 표시됩니다.</p>}<div className="cm-selected-product-cards">{selectedProducts.map(id => { const product = productCatalog.find(item => item.id === id); const custom = id.startsWith('custom:') ? id.split(':').slice(2).join(':') : ''; const name = product?.name ?? custom; const optionList = product?.options ?? []; return <div key={id}><span><strong>{name}</strong><small>{product ? `${product.kind} · 예시 카탈로그 제품` : `${productKind} · 목록에 없는 제품`}</small></span><label>옵션 (선택)<input value={options[id] ?? ''} list={optionList.length ? `options-${id}` : undefined} onChange={event => setOptions(current => ({ ...current, [id]: event.target.value }))} placeholder="예: 저소음 적축, 색상" />{optionList.length > 0 && <datalist id={`options-${id}`}>{optionList.map(option => <option value={option} key={option} />)}</datalist>}</label><button type="button" className="cm-btn" onClick={() => onToggleProduct(id)}>삭제</button></div> })}</div>{category === '사용기 · 리뷰' && <p className="cm-review-notice">사용기 글의 내용은 제품 추천에 참고 자료로 활용될 수 있습니다.</p>}</fieldset>
        <label className="full">제목<input required maxLength={80} value={title} onChange={event => onTitle(event.target.value)} placeholder="내용을 구체적으로 알 수 있는 제목을 입력하세요" /></label>
        <label className="full">내용<textarea required value={body} onChange={event => onBody(event.target.value)} placeholder="질문이라면 사용 환경, 예산, 시도한 방법을 함께 적어주세요." /></label>
        <label className="full">태그 <small>(선택)</small><input value={tags} onChange={event => setTags(event.target.value)} placeholder="예: 영상편집, 200만원견적, 조립초보" /></label>
        <div className="cm-form-actions full"><button type="button" className="cm-btn" onClick={onDraft}>임시 저장</button><button type="button" className="cm-btn" onClick={onCancel}>취소</button><button type="submit" className="cm-btn primary">게시하기</button></div>
      </form>
    </>
  )
}

function DealsView({ onWrite, onUnavailable }: { onWrite: () => void; onUnavailable: () => void }) {
  const [category, setCategory] = useState('전체')
  const [sort, setSort] = useState('인기순')
  const categories = ['전체', 'PC부품', '주변기기', '디지털', '소프트웨어', '종료 임박']
  let visibleDeals = deals.filter(deal => {
    if (category === '전체') return true
    if (category === 'PC부품') return ['ssd', 'ram', 'power', 'cooler'].includes(deal.id)
    if (category === '주변기기') return ['monitor', 'keyboard'].includes(deal.id)
    if (category === '종료 임박') return deal.badge === '종료 임박'
    return false
  })
  if (sort === '할인율순') visibleDeals = [...visibleDeals].sort((a, b) => Number.parseInt(a.discount) - Number.parseInt(b.discount))
  if (sort === '인기순') visibleDeals = [...visibleDeals].sort((a, b) => Number.parseInt(b.stats.match(/\d+/)?.[0] ?? '0') - Number.parseInt(a.stats.match(/\d+/)?.[0] ?? '0'))
  return (
    <><header className="cm-page-head"><div><span>Promotions</span><h1>실시간 프로모션</h1><p>회원들이 찾은 제품을 확인하고 후기와 함께 살펴보세요.</p></div><div><button type="button" className="cm-btn" onClick={onUnavailable}>가격 알림</button><button type="button" className="cm-btn primary" onClick={onWrite}>프로모션 제보</button></div></header><ExampleNotice /><div className="cm-deal-toolbar"><div>{categories.map(item => <button type="button" key={item} className={category === item ? 'active' : ''} onClick={() => setCategory(item)}>{item}</button>)}</div><select value={sort} onChange={event => setSort(event.target.value)}><option>인기순</option><option>최신순</option><option>할인율순</option></select></div>{visibleDeals.length ? <div className="cm-deal-grid">{visibleDeals.map(deal => <article className="cm-card cm-deal-card" key={deal.id}><button type="button" className="cm-deal-visual" onClick={onUnavailable}><span>{deal.discount}</span>제품 이미지</button><div><span className="cm-badge accent">{deal.badge}</span><h2>{deal.title}</h2><strong>{deal.price}</strong> <small>{deal.note}</small><footer><span>{deal.stats}</span><span>{deal.time}</span></footer></div></article>)}</div> : <div className="cm-card cm-empty">해당 분류의 프로모션이 없습니다.</div>}</>
  )
}

function SearchView({ keyword, onPost, onHome }: { keyword: string; onPost: (id: string) => void; onHome: () => void }) {
  const results = useMemo(() => communityPosts.filter(post => `${post.title} ${post.excerpt} ${post.author}`.toLowerCase().includes(keyword.toLowerCase())), [keyword])
  return (
    <><header className="cm-page-head"><div><span>Search</span><h1>통합 검색</h1><p>커뮤니티 게시글을 제목, 내용, 작성자로 찾습니다.</p></div></header><ExampleNotice /><section className="cm-card cm-search-results"><h2>‘{keyword || '검색어'}’ 검색 결과 <small>{results.length}개</small></h2>{results.length ? results.map(post => <button type="button" key={post.id} onClick={() => onPost(post.id)}><span>{post.boardLabel}</span><strong>{post.title}</strong><small>{post.excerpt}</small></button>) : <div className="cm-empty"><b>검색 결과가 없습니다.</b><p>다른 키워드로 다시 검색해보세요.</p><button type="button" className="cm-btn primary" onClick={onHome}>홈으로 돌아가기</button></div>}</section></>
  )
}
