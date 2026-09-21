import { useState } from 'react'
import { AppTopBar } from '../components/layout/AppTopBar'
import { SetupDrawer } from '../components/layout/SetupDrawer'
import { DeskModal } from '../components/layout/DeskModal'
import { ChatPanel } from '../components/chat/ChatPanel'
import { PlannerPane } from '../components/planner/PlannerPane'
import { EvidencePane } from '../components/evidence/EvidencePane'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

type MobileTab = 'interview' | 'planner' | 'evidence'

const TABS: { key: MobileTab; label: string }[] = [
  { key: 'interview', label: 'AI 인터뷰' },
  { key: 'planner', label: 'PC 구성' },
  { key: 'evidence', label: '추천 근거' },
]

export function PlanPage() {
  useDocumentTitle('PC 구성')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [deskModalOpen, setDeskModalOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<MobileTab>('interview')

  return (
    <div className="app">
      <AppTopBar onOpenDrawer={() => setDrawerOpen(true)} />
      <nav className="mobile-tabs" aria-label="화면 영역 전환">
        {TABS.map(tab => (
          <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>
      <main className="workspace">
        <ChatPanel mobileActive={activeTab === 'interview'} />
        <PlannerPane mobileActive={activeTab === 'planner'} onOpenDeskModal={() => setDeskModalOpen(true)} />
        <EvidencePane mobileActive={activeTab === 'evidence'} />
      </main>
      <SetupDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <DeskModal open={deskModalOpen} onClose={() => setDeskModalOpen(false)} />
    </div>
  )
}
