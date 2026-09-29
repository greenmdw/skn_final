import { useEffect } from 'react'
import '../styles/drawer.css'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useDrawer } from '../state/DrawerContext'
import { planTotal } from '../state/planModel'
import { useSetups } from '../state/SetupsContext'
import { useAuthUser } from '../state/authStore'
import { wonFmt } from '../utils/format'

// 오른쪽에서 밀려 나오는 "저장한 견적" 패널(기획: TrueFit Prototype v2 의 UI-12). 항목을 누르면 그 견적의 리포트를 연다.
// 서버가 채팅 수·마지막 대화를 주지 않으므로 그 줄은 만들지 않는다.
export default function SavedDrawer() {
  const { savedOpen, closeSaved } = useDrawer()
  const { savedSetups, loading, storageError, removeSetup } = useSetups()
  const user = useAuthUser()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  useEffect(() => {
    if (!savedOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') closeSaved() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [savedOpen, closeSaved])

  if (!savedOpen) return null

  const open = (id: string) => { closeSaved(); navigate('/report/' + id) }
  async function remove(id: string, title: string) {
    if (window.confirm(`“${title}” 견적을 삭제할까요? 되돌릴 수 없어요.`)) await removeSetup(id)
  }

  return (
    <div className="sd-root">
      <div className="sd-scrim" onClick={closeSaved} />
      <aside className="sd-panel" role="dialog" aria-modal="true" aria-label="저장한 견적">
        <div className="sd-head">
          <span>저장한 견적</span>
          <button type="button" className="sd-close" aria-label="닫기" onClick={closeSaved}>×</button>
        </div>
        <div className="sd-list">
          {!user && (
            <div className="sd-note">
              저장한 견적은 로그인한 계정에만 있어요.{' '}
              <Link to={`/login?next=${encodeURIComponent(pathname)}`} onClick={closeSaved} style={{ color: '#60edc0', fontWeight: 700 }}>로그인하기 →</Link>
            </div>
          )}
          {storageError && <div className="sd-note bad" role="alert">{storageError}</div>}
          {user && loading && <div className="sd-note">불러오는 중이에요…</div>}
          {user && !loading && savedSetups.length === 0 && !storageError && (
            <div className="sd-note">아직 확정한 견적이 없어요. 추천을 받고 장바구니에서 확정하면 여기에 저장돼요.</div>
          )}
          {savedSetups.map(setup => (
            <div className="sd-item" key={setup.id} role="button" tabIndex={0}
              onClick={() => open(setup.id)} onKeyDown={event => { if (event.key === 'Enter') open(setup.id) }}>
              <div className="sd-item-top">
                <span className="sd-name">{setup.title}</span>
                <span className="sd-total">{wonFmt(planTotal(setup.plan))}</span>
              </div>
              <div className="sd-meta">
                {[setup.plan.mode === 'upgrade' ? '받은 견적' : '새 PC', setup.date, `부품 ${setup.plan.items.length}개`].filter(Boolean).join(' · ')}
              </div>
              <button type="button" className="sd-del" onClick={event => { event.stopPropagation(); void remove(setup.id, setup.title) }}>삭제</button>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}
