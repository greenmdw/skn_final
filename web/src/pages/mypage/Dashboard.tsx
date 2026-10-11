import { Link, useNavigate } from 'react-router-dom'
import type { AuthUser } from '../../api'
import { useSetups } from '../../state/SetupsContext'
import { wonFmt } from '../../utils/format'
import { Icons } from './parts'
import { PC_FIELDS, configKey, dateText, newestFirst, reportPath, setupSummary, setupTotal, type MyPc } from './model'
import { conversationTitle, useOpenConversation } from './useOpenConversation'
import type { MyPageId } from './nav'

function PcBanner({ myPc, onClick }: { myPc: MyPc | null; onClick: () => void }) {
  const sub = myPc
    ? '등록된 구성: ' + PC_FIELDS.filter(([key]) => myPc.parts[key]).slice(0, 3).map(([key]) => myPc.parts[key]).join(' · ')
    : '지금 쓰는 PC를 등록하면 업그레이드 추천과 견적 점검이 더 정확해져요.'
  return (
    <button className="pc-banner" type="button" onClick={onClick}>
      <span className="pc-banner-icon">🖥️</span>
      <span><strong>{myPc ? '내 현재 PC' : '내 현재 PC를 등록해 보세요'}</strong><small>{sub}</small></span>
      <b>{myPc ? '관리' : '등록하기'} ›</b>
    </button>
  )
}

export default function Dashboard({ user, myPc, go, openConfig }: {
  user: AuthUser
  myPc: MyPc | null
  go: (page: MyPageId) => void
  openConfig: (id: string) => void
}) {
  const navigate = useNavigate()
  const { savedSetups, conversations, loading } = useSetups()
  const openConversation = useOpenConversation()
  const setups = [...savedSetups].sort(newestFirst)
  const recent = setups[0]
  const consults = (conversations ?? []).slice(0, 3)
  const stat = (page: MyPageId, icon: React.ReactNode, label: string, value: string) => (
    <div className="mp-stat" role="button" tabIndex={0} onClick={() => go(page)}
      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); go(page) } }}>
      <span>{icon}</span><div><small>{label}</small><strong>{value}</strong></div>
    </div>
  )

  return (
    <>
      <section className="mpx-welcome">
        <div className="mpx-hello">
          <div className="mpx-avatar" aria-hidden="true">{user.name.slice(0, 1)}</div>
          <div><h1>{user.name}님, 다시 오셨네요! 👋</h1><p>오늘도 나에게 딱 맞는 PC를 찾아보세요.</p></div>
        </div>
        <button className="mpx-memory" type="button" onClick={() => navigate('/start')}>
          <span className="mpx-brain">🖥️</span>
          <span><strong>새 견적 받기</strong>용도와 예산을 알려주면 나에게 맞는 구성을 추천해 드려요.</span>
          <b>›</b>
        </button>
      </section>

      <div className="mp-stats mp-stats-click">
        {stat('configs', Icons.cfg, '저장한 구성', loading ? '…' : `${setups.length}개`)}
        {stat('consults', Icons.chat, 'AI 상담 기록', conversations ? `${conversations.length}개` : '…')}
        {stat('reports', Icons.doc, '추천 리포트', loading ? '…' : `${setups.length}개`)}
      </div>

      <PcBanner myPc={myPc} onClick={() => go('mypc')} />

      <section className="mpx-grid">
        <article className="mp-section mpx-panel">
          <div className="mp-section-head"><h2>최근 구성</h2><button className="mp-text-button" type="button" onClick={() => go('configs')}>전체보기 〉</button></div>
          {recent ? (
            <div className="mpx-config-card">
              <div className="mpx-photo"><div><span className="mpx-emoji">🖥️</span><small>MY PC</small></div></div>
              <div className="mpx-info">
                <div className="mpx-title"><strong>{recent.title}</strong><span className="mpx-date">{dateText(recent.savedAt)}</span></div>
                <div className="mpx-price">{wonFmt(setupTotal(recent))}</div>
                <div className="mpx-specs">{setupSummary(recent, 4)}</div>
                <div className="mpx-btns">
                  <button className="mp-btn primary" type="button" onClick={() => openConfig(configKey(recent))}>구성 상세보기</button>
                  <Link className="mp-btn mp-link-btn" to={reportPath(recent)}>리포트 열기</Link>
                </div>
              </div>
            </div>
          ) : <div className="mp-empty-card"><strong>{loading ? '불러오는 중이에요' : '아직 저장한 구성이 없어요'}</strong><span>견적을 확정하면 여기에 모여요.</span></div>}
        </article>
        <article className="mp-section mpx-panel">
          <div className="mp-section-head"><h2>최근 AI 상담</h2><button className="mp-text-button" type="button" onClick={() => go('consults')}>전체보기 〉</button></div>
          {consults.length > 0 ? (
            <div className="mpx-consult-list">
              {consults.map(item => (
                <button key={item.listId} className="mpx-consult-row" type="button" onClick={() => void openConversation(item)}>
                  <span className="mpx-bubble">▣</span><span className="mpx-question">{conversationTitle(item)}</span><time>{dateText(item.lastActiveAt)}</time><span className="mpx-chev">›</span>
                </button>
              ))}
            </div>
          ) : <div className="mp-empty-card"><strong>{conversations ? '아직 상담 기록이 없어요' : '불러오는 중이에요'}</strong><span>대화로 견적을 받으면 여기에 남아요.</span></div>}
        </article>
      </section>

      <section className="mp-section">
        <div className="mp-section-head"><h2>추천 리포트</h2><button className="mp-text-button" type="button" onClick={() => go('reports')}>전체보기 〉</button></div>
        {setups.length > 0 ? (
          <div className="mpx-report-list">
            {setups.slice(0, 2).map(setup => (
              <div className="mpx-report-card" key={configKey(setup)}>
                <div className="mpx-photo mpx-photo-sm"><span className="mpx-emoji">🖥️</span></div>
                <div className="mpx-report-body">
                  <h3>{setup.title}</h3>
                  <div className="mpx-meta"><time>{dateText(setup.savedAt)}</time>{setup.peripherals && setup.peripherals.length > 0 && <span className="mpx-pill">주변기기 포함</span>}</div>
                  <div className="mpx-report-price">{wonFmt(setupTotal(setup))}</div>
                  <div className="mpx-btns"><Link className="mp-btn primary mp-link-btn" to={reportPath(setup)}>리포트 보기</Link></div>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="mp-empty-card"><strong>{loading ? '불러오는 중이에요' : '아직 확정한 리포트가 없어요'}</strong><span>견적을 확정하면 추천 리포트가 만들어져요.</span></div>}
      </section>
    </>
  )
}
