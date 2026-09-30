import { useParams } from 'react-router-dom'
import ListHistory from '../components/ListHistory'
import PlannerShell from '../components/PlannerShell'
import ProductThumb from '../components/ProductThumb'
import { planTotal } from '../state/planModel'
import { useDrawer } from '../state/DrawerContext'
import { useSetups } from '../state/SetupsContext'
import { wonFmt } from '../utils/format'

// 확정한 견적 리포트. 서버가 확정 시점에 저장한 부품·가격·이름·구매 예정일·목표 금액·메모를 보여 준다.
export default function ReportPage() {
  const { id } = useParams()
  const { savedSetups, loading, storageError } = useSetups()
  const { openSaved } = useDrawer()
  const setup = savedSetups.find(item => item.id === id)

  if (!setup) {
    return (
      <PlannerShell>
        <div className="pl-page narrow">
          <h2 className="pl-h2">리포트</h2>
          {loading
            ? <div className="pl-note">리포트를 불러오는 중이에요…</div>
            : <div className="pl-empty">{storageError || '이 리포트를 찾을 수 없어요. 로그인 상태를 확인하거나 저장한 견적에서 다시 열어 주세요.'}</div>}
          <div><button type="button" className="pl-btn ghost" onClick={openSaved}>저장한 견적 열기</button></div>
        </div>
      </PlannerShell>
    )
  }

  const total = planTotal(setup.plan)
  const confirmed = setup.savedAt ? new Date(setup.savedAt).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : ''
  return (
    <PlannerShell>
      <div className="pl-page pl-report">
        <div className="pl-noprint" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="pl-pill" onClick={openSaved}>저장한 견적</button>
          <button type="button" className="pl-pill" onClick={() => window.print()}>인쇄</button>
        </div>
        <article className="pl-paper">
          <div className="pl-paper-head">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="pl-mono" style={{ fontSize: 11, color: '#92a4b2' }}>TRUEFIT 견적 리포트</div>
              <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em' }}>{setup.title}</div>
              <div className="pl-note">
                {[confirmed && `${confirmed} 확정`, setup.date && `구매 예정 ${setup.date}`, `목표 금액 ${wonFmt(setup.target)}`].filter(Boolean).join(' · ')}
              </div>
              {setup.memo && <div style={{ fontSize: 13, lineHeight: 1.6 }}>메모 · {setup.memo}</div>}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="pl-note">합계</div>
              <div className="pl-mono" style={{ fontSize: 26, fontWeight: 600 }}>{wonFmt(total)}</div>
            </div>
          </div>

          <section>
            <div style={{ fontSize: 13, fontWeight: 700, paddingBottom: 8 }}>본체</div>
            {setup.plan.items.map(item => (
              <div className="pl-report-row" key={item.id}>
                <ProductThumb imageUrl={item.imageUrl} partKey={item.key} name={item.name} />
                <span className="cat" style={{ color: '#92a4b2' }}>{item.type}</span>
                <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <b>{item.name}</b>
                    {item.qty != null && <span className="pl-qty">×{item.qty}</span>}
                  </div>
                  {item.fit && <span className="pl-note">{item.fit}</span>}
                </div>
                <span className="pl-mono" style={{ textAlign: 'right' }}>{wonFmt(item.price)}</span>
                {item.purchaseUrl
                  ? <a href={item.purchaseUrl} target="_blank" rel="noopener noreferrer">판매처 보기 ↗</a>
                  : <span />}
              </div>
            ))}
          </section>

          <ListHistory listId={setup.id} />
        </article>
      </div>
    </PlannerShell>
  )
}
