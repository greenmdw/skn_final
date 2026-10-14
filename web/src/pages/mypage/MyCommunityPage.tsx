import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage } from '../../api'
import {
  communityApi, relativeTime,
  type CommunityBoardType, type MyActivitySort, type WireCommunityItem, type WireMyActivitySummary, type WireMyComment, type WireMyPostItem, type WireNotification,
} from '../../api/http/community'
import type { MyCommunityActivity, MyCommunityFilter, MyCommunitySort, MyCommunityTab } from './myCommunityTypes'

const PAGE_SIZE = 5
const NOTICE_SIZE = 5
const TAB_LABELS: Array<[MyCommunityTab, string]> = [
  ['posts', '작성한 글'], ['comments', '작성한 댓글'], ['liked', '추천한 글'], ['saved', '저장한 글'],
]
const FILTERS: Array<[MyCommunityFilter, string]> = [
  ['all', '전체'], ['question', '질문'], ['review', '사용기'], ['tip', '정보'], ['free', '자유'],
]
const SORTS: Record<'posts' | 'others', Array<[MyCommunitySort, string]>> = {
  posts: [['latest', '최신순'], ['popular', '추천순'], ['views', '조회순']],
  others: [['latest', '최신순'], ['popular', '추천순'], ['comments', '댓글순']],
}
const EMPTY_TEXT: Record<MyCommunityTab, string> = {
  posts: '아직 작성한 글이 없어요', comments: '아직 작성한 댓글이 없어요', liked: '아직 추천한 글이 없어요', saved: '아직 저장한 글이 없어요',
}

const boardLabel = (type: CommunityBoardType) => ({ question: '질문', review: '사용기', tip: '정보', free: '자유' })[type]
const GONE_STATUS: Record<string, string> = { hidden: '숨겨진 글', deleted: '삭제된 글' }
const postPath = (id: string) => `/community?view=post&post=${encodeURIComponent(id)}`

function statsText(post: Pick<WireCommunityItem, 'view_count' | 'like_count' | 'comment_count'>) {
  return `조회 ${post.view_count.toLocaleString()} · 추천 ${post.like_count} · 댓글 ${post.comment_count}`
}

function postRow(post: WireCommunityItem | WireMyPostItem, kind: 'posts' | 'liked' | 'saved'): MyCommunityActivity {
  const goneStatus = 'post_status' in post && post.post_status !== 'published' ? GONE_STATUS[post.post_status] : null
  const stamp = kind === 'liked' ? ('liked_at' in post ? post.liked_at : null) : kind === 'saved' ? ('saved_at' in post ? post.saved_at : null) : post.published_at
  return {
    id: post.id, postId: post.id, type: post.board_type, label: boardLabel(post.board_type), title: post.title,
    description: post.excerpt, date: relativeTime(stamp ?? post.published_at), gone: goneStatus !== null,
    stats: goneStatus ? '' : statsText(post),
    status: goneStatus ?? (kind === 'liked' ? '추천함' : kind === 'saved' ? '저장됨' : post.board_type === 'question' ? '답변 확인' : '게시 중'),
  }
}

function commentRow(comment: WireMyComment): MyCommunityActivity {
  const goneStatus = comment.post_status !== 'published' ? GONE_STATUS[comment.post_status] : null
  return {
    id: comment.id, postId: comment.post.id, type: comment.post.board_type, label: boardLabel(comment.post.board_type), title: comment.post.title,
    description: comment.body, date: relativeTime(comment.created_at), gone: goneStatus !== null,
    stats: comment.parent_comment_id ? '내 답글' : '내 댓글',
    status: goneStatus ?? (comment.reply_count > 0 ? `답글 ${comment.reply_count}` : '작성 완료'),
  }
}

interface ListState { rows: MyCommunityActivity[]; total: number; pages: number; loading: boolean; error: string }
const emptyList: ListState = { rows: [], total: 0, pages: 1, loading: true, error: '' }

/** 번호는 최대 5개씩 보이고 지금 쪽이 가운데쯤 오도록 창이 움직인다 */
function pageNumbers(page: number, count: number, size = 5): number[] {
  const start = Math.max(1, Math.min(page - Math.floor(size / 2), count - size + 1))
  const end = Math.min(count, start + size - 1)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
}

export default function MyCommunityPage() {
  const [tab, setTab] = useState<MyCommunityTab>('posts')
  const [filter, setFilter] = useState<MyCommunityFilter>('all')
  const [sort, setSort] = useState<MyCommunitySort>('latest')
  const [page, setPage] = useState(1)
  const [list, setList] = useState<ListState>(emptyList)
  const [summary, setSummary] = useState<WireMyActivitySummary | null>(null)
  const [notices, setNotices] = useState<WireNotification[]>([])
  const [noticeError, setNoticeError] = useState('')

  const loadSummary = useCallback(() => {
    communityApi.me.summary().then(setSummary).catch(() => setSummary(null))
  }, [])
  const loadNotices = useCallback(() => {
    communityApi.me.notifications({ unread: true, pageSize: NOTICE_SIZE })
      .then(result => { setNotices(result.items); setNoticeError('') })
      .catch(error => setNoticeError(errorMessage(error, '새 활동을 불러오지 못했어요.')))
  }, [])

  useEffect(() => { loadSummary(); loadNotices() }, [loadSummary, loadNotices])

  useEffect(() => {
    let active = true
    setList(current => ({ ...current, loading: true, error: '' }))
    const boardType = filter === 'all' ? undefined : filter
    const paging = { boardType, page, pageSize: PAGE_SIZE }
    const done = (rows: MyCommunityActivity[], total: number, pages: number) => { if (active) setList({ rows, total, pages: Math.max(1, pages), loading: false, error: '' }) }
    const failed = (error: unknown) => { if (active) setList({ ...emptyList, loading: false, error: errorMessage(error, '목록을 불러오지 못했어요.') }) }
    if (tab === 'posts') {
      const listSort = sort === 'popular' ? 'recommend' : sort === 'views' ? 'views' : 'latest'
      communityApi.list({ mine: true, status: 'published', sort: listSort, ...paging })
        .then(result => done(result.items.map(post => postRow(post, 'posts')), result.total, result.total_pages)).catch(failed)
    } else {
      const activitySort: MyActivitySort = sort === 'popular' || sort === 'comments' ? sort : 'latest'
      const request = { sort: activitySort, ...paging }
      if (tab === 'comments') communityApi.me.comments(request).then(result => done(result.items.map(commentRow), result.total, result.total_pages)).catch(failed)
      else if (tab === 'liked') communityApi.me.likedPosts(request).then(result => done(result.items.map(post => postRow(post, 'liked')), result.total, result.total_pages)).catch(failed)
      else communityApi.me.savedPosts(request).then(result => done(result.items.map(post => postRow(post, 'saved')), result.total, result.total_pages)).catch(failed)
    }
    return () => { active = false }
  }, [tab, filter, sort, page])

  function changeTab(next: MyCommunityTab) { setTab(next); setFilter('all'); setSort('latest'); setPage(1) }
  function changeFilter(next: MyCommunityFilter) { setFilter(next); setPage(1) }
  const readNotice = (id: string) => {
    setNotices(current => current.filter(notice => notice.id !== id))
    communityApi.me.markRead(id).then(loadSummary).catch(() => loadNotices())
  }
  const readAll = () => {
    setNotices([])
    communityApi.me.markAllRead().then(loadSummary).catch(() => loadNotices())
  }

  const count = (value: number | undefined) => (summary ? `${value ?? 0}` : '…')
  const sortOptions = tab === 'posts' ? SORTS.posts : SORTS.others
  const pages = pageNumbers(page, list.pages)
  const tabCount: Record<MyCommunityTab, number | undefined> = {
    posts: summary?.post_count, comments: summary?.comment_count, liked: summary?.liked_post_count, saved: summary?.saved_post_count,
  }

  return (
    <>
      <header className="mpc-head">
        <div><span>MY COMMUNITY</span><h1>나의 커뮤니티</h1><p>최근 반응과 이어서 확인할 활동을 먼저 보여줍니다.</p></div>
        <Link className="mp-btn primary mp-link-btn" to="/community?view=write">새 글 작성</Link>
      </header>

      {list.error && <div className="mp-alert" role="alert">{list.error}</div>}

      <div className="mpc-layout">
        <section className="mp-section mpc-activity">
          <div className="mp-section-head"><h2>확인할 새 활동</h2><button type="button" className="mp-text-button" disabled={!notices.length} onClick={readAll}>모두 읽음</button></div>
          {noticeError
            ? <div className="mp-empty-card mpc-empty-compact"><strong>{noticeError}</strong></div>
            : notices.length === 0
              ? <div className="mp-empty-card mpc-empty-compact"><strong>새 활동이 없어요</strong><span>내 글에 댓글이 달리거나 내 댓글에 답글이 달리면 여기에 보여 드려요.</span></div>
              : <div className="mpc-notice-list">
                {notices.map(notice => (
                  <article className="mpc-notice" key={notice.id}>
                    <span className="mpc-notice-icon">{notice.type === 'new_reply' ? '답' : '댓'}</span>
                    <span className="mpc-notice-copy"><strong>{notice.title}</strong><span>{notice.message}</span><small>{relativeTime(notice.created_at)}</small></span>
                    <Link to={postPath(notice.post_id)} onClick={() => readNotice(notice.id)}>확인</Link>
                  </article>
                ))}
              </div>}
        </section>

        <aside className="mp-section mpc-summary">
          <h2>내 활동</h2>
          <dl>
            <div><dt>작성한 글</dt><dd>{count(summary?.post_count)}개</dd></div>
            <div><dt>작성한 댓글</dt><dd>{count(summary?.comment_count)}개</dd></div>
            <div><dt>받은 댓글</dt><dd>{count(summary?.received_comment_count)}개</dd></div>
            <div><dt>받은 추천</dt><dd>{count(summary?.received_like_count)}개</dd></div>
          </dl>
        </aside>
      </div>

      <section className="mp-section mpc-manager">
        <nav className="mpc-tabs" aria-label="나의 커뮤니티 활동">
          {TAB_LABELS.map(([id, label]) => <button type="button" key={id} className={tab === id ? 'on' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => changeTab(id)}>{label} {summary && <b>{tabCount[id]}</b>}</button>)}
        </nav>
        <div className="mpc-toolbar">
          <div className="mpc-filters" aria-label="게시글 유형 필터">
            {FILTERS.map(([id, label]) => <button type="button" key={id} className={filter === id ? 'on' : ''} onClick={() => changeFilter(id)}>{label}</button>)}
          </div>
          <select value={sort} aria-label="정렬 기준" onChange={event => { setSort(event.target.value as MyCommunitySort); setPage(1) }}>
            {sortOptions.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>

        {list.loading
          ? <div className="mp-empty-card mpc-empty-compact"><strong>불러오는 중이에요</strong></div>
          : list.rows.length
            ? <div className="mpc-activity-list">{list.rows.map(item => <ActivityRow key={item.id} item={item} />)}</div>
            : <div className="mp-empty-card mpc-empty-compact"><strong>{filter === 'all' ? EMPTY_TEXT[tab] : '해당 유형의 활동이 없어요'}</strong>{filter !== 'all' && <span>다른 필터를 선택해 보세요.</span>}</div>}
        {list.pages > 1 && <nav className="mpc-pagination" aria-label="페이지 이동">
          <button type="button" disabled={page === 1} onClick={() => setPage(value => Math.max(1, value - 1))}>‹</button>
          {pages.map(number => <button type="button" key={number} className={page === number ? 'on' : ''} onClick={() => setPage(number)}>{number}</button>)}
          <button type="button" disabled={page === list.pages} onClick={() => setPage(value => Math.min(list.pages, value + 1))}>›</button>
        </nav>}
      </section>
    </>
  )
}

function ActivityRow({ item }: { item: MyCommunityActivity }) {
  return (
    <article className="mpc-activity-row">
      <span className={`mpc-board ${item.type}`}>{item.label}</span>
      <span className="mpc-activity-copy">
        {item.gone ? <strong>{item.title}</strong> : <Link to={postPath(item.postId)}>{item.title}</Link>}
        {item.description && <p>{item.description}</p>}
        <small>{[item.date, item.stats].filter(Boolean).join(' · ')}</small>
      </span>
      <span className="mpc-status">{item.status}</span>
      {item.gone ? <span className="mpc-more" aria-hidden="true" /> : <Link className="mpc-more" to={postPath(item.postId)}>보기 〉</Link>}
    </article>
  )
}
