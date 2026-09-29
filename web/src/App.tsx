import { useCallback, useEffect, useRef } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { ToastProvider } from './state/ToastProvider'
import { SetupsProvider } from './state/SetupsProvider'
import { PlanProvider } from './state/PlanProvider'
import { logout, useAuthUser } from './state/authStore'
import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import ConditionsPage from './pages/ConditionsPage'
import PlanPage from './pages/PlanPage'

// 아직 React 로 옮기지 않은 화면(메인·조건 대화·추천·장바구니 …)은 프로토타입(iframe)이 그린다.
// 프로토타입과는 postMessage 로만 주고받는다: 로그인 사용자 → 화면, 화면 → 페이지 이동·로그아웃 요청.
function TrueFitPrototype() {
  const { screen } = useParams()   // /screen/<이름> 이면 그 화면으로 연다
  const frame = useRef<HTMLIFrameElement>(null)
  const navigate = useNavigate()
  const user = useAuthUser()

  const sendAuth = useCallback(() => {
    frame.current?.contentWindow?.postMessage({ tfAuth: user }, window.location.origin)
  }, [user])
  const sendScreen = useCallback(() => {
    if (screen) frame.current?.contentWindow?.postMessage({ tfScreen: screen }, window.location.origin)
  }, [screen])

  useEffect(sendAuth, [sendAuth])
  useEffect(sendScreen, [sendScreen])

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return
      const data = event.data as { tfNav?: string; tfLogout?: boolean; tfReady?: boolean } | null
      if (!data) return
      if (typeof data.tfNav === 'string' && data.tfNav.startsWith('/')) navigate(data.tfNav)
      else if (data.tfLogout) void logout()
      else if (data.tfReady) { sendAuth(); sendScreen() }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [navigate, sendAuth, sendScreen])

  return (
    <main className="app-shell">
      <iframe
        ref={frame}
        className="truefit-screen"
        src="/assets/prototype/truefit.html"
        title="TrueFit 프론트 화면"
      />
    </main>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <SetupsProvider>
        <PlanProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/start" element={<ConditionsPage />} />
            <Route path="/plan" element={<PlanPage />} />
            <Route path="/screen/:screen" element={<TrueFitPrototype />} />
            <Route path="*" element={<TrueFitPrototype />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
