import { Link } from 'react-router-dom'
import { useSetups } from '../../state/SetupsContext'
import { wonFmt } from '../../utils/format'
import { Empty, Hero, Row } from './parts'
import { configKey, dateText, newestFirst, reportPath, setupSummary, setupTotal } from './model'
import { conversationTitle, useOpenConversation } from './useOpenConversation'

export function ConfigsPage({ openConfig }: { openConfig: (id: string) => void }) {
  const { savedSetups, loading, storageError } = useSetups()
  const setups = [...savedSetups].sort(newestFirst)
  return (
    <>
      <Hero icon="🖥️" title="내 구성" description="확정해서 저장한 PC 구성을 확인하고, 부품 상세와 리포트를 열어볼 수 있어요." />
      <section className="mp-section">
        <div className="mp-list">
          <div className="mp-list-head"><h2>저장한 구성 {setups.length}개</h2></div>
          {setups.map(setup => (
            <Row key={configKey(setup)} icon="🖥️" title={setup.title} subtitle={`${dateText(setup.savedAt)} · ${setupSummary(setup, 3)}`} price={wonFmt(setupTotal(setup))}>
              <button className="mp-btn" type="button" onClick={() => openConfig(configKey(setup))}>상세</button>
            </Row>
          ))}
          {setups.length === 0 && (loading
            ? <Empty title="불러오는 중이에요" text="저장한 구성을 읽고 있어요." />
            : <Empty title={storageError ? '구성을 불러오지 못했어요' : '아직 저장한 구성이 없어요'} text={storageError || '견적을 확정하면 여기에 저장돼요.'}>
              {!storageError && <Link className="mp-btn primary mp-link-btn" to="/start">새 견적 받기</Link>}
            </Empty>)}
        </div>
      </section>
    </>
  )
}

export function ConsultsPage() {
  const { conversations, conversationsError } = useSetups()
  const openConversation = useOpenConversation()
  const items = conversations ?? []
  const stageText = { category: '시작', conditions: '조건 정리 중', results: '추천 결과', report: '견적서 확정' } as const
  return (
    <>
      <Hero icon="💬" title="AI 상담 기록" description="이전 대화를 눌러 그 자리에서 이어서 확인할 수 있어요." />
      <section className="mp-section">
        <div className="mp-list">
          <div className="mp-list-head"><h2>상담 {items.length}개</h2></div>
          {items.map(item => (
            <Row key={item.listId} icon="▣" title={conversationTitle(item)}
              subtitle={`${dateText(item.lastActiveAt)} · ${stageText[item.stage]}${item.reports.length ? ` · 견적서 ${item.reports.length}개` : ''}`}
              price={item.stage === 'report' ? '완료' : '진행 중'}>
              <button className="mp-btn" type="button" onClick={() => void openConversation(item)}>상담 열기</button>
            </Row>
          ))}
          {items.length === 0 && (conversations === null && !conversationsError
            ? <Empty title="불러오는 중이에요" text="상담 기록을 읽고 있어요." />
            : <Empty title={conversationsError ? '상담 기록을 불러오지 못했어요' : '아직 상담 기록이 없어요'} text={conversationsError || '대화로 견적을 받으면 여기에 남아요.'} />)}
        </div>
      </section>
    </>
  )
}

export function ReportsPage() {
  const { savedSetups, loading, storageError } = useSetups()
  const setups = [...savedSetups].sort(newestFirst)
  return (
    <>
      <Hero icon="📄" title="추천 리포트" description="확정한 견적의 부품·가격과 추천 이유를 다시 확인하세요." />
      <section className="mp-section">
        <div className="mp-feature-grid">
          {setups.map(setup => (
            <Link key={configKey(setup)} className="mp-report-card" to={reportPath(setup)} style={{ textDecoration: 'none' }}>
              <span className="mp-card-icon">📄</span>
              <h3>{setup.title}</h3>
              <p>{dateText(setup.savedAt)} · {wonFmt(setupTotal(setup))}<br />{setupSummary(setup, 2)}</p>
              <span className="mp-card-link">리포트 열기</span>
            </Link>
          ))}
        </div>
        {setups.length === 0 && (loading
          ? <Empty title="불러오는 중이에요" text="리포트를 읽고 있어요." />
          : <Empty title={storageError ? '리포트를 불러오지 못했어요' : '아직 확정한 리포트가 없어요'} text={storageError || '견적을 확정하면 추천 리포트가 만들어져요.'} />)}
      </section>
    </>
  )
}
