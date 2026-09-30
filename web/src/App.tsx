import { Navigate, Routes, Route } from 'react-router-dom'
import { ToastProvider } from './state/ToastProvider'
import { SetupsProvider } from './state/SetupsProvider'
import { PlanProvider } from './state/PlanProvider'
import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import HomePage from './pages/HomePage'
import ChoosePage from './pages/ChoosePage'
import ConditionsPage from './pages/ConditionsPage'
import PlanPage from './pages/PlanPage'
import CartPage from './pages/CartPage'
import ReportPage from './pages/ReportPage'
import ComingSoonPage from './pages/ComingSoonPage'

// 모든 화면이 React 이고 백엔드 API 로 데이터를 가져온다. 아직 백엔드와 연결하지 않은 화면은 가짜 데이터를 보이지 않고
// "개발 전" 안내(ComingSoonPage)만 보여 준다.
export default function App() {
  return (
    <ToastProvider>
      <SetupsProvider>
        <PlanProvider>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/choose" element={<ChoosePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/start" element={<ConditionsPage />} />
            <Route path="/plan" element={<PlanPage />} />
            <Route path="/cart" element={<CartPage />} />
            <Route path="/report/:id" element={<ReportPage />} />
            <Route path="/check" element={<ComingSoonPage title="받은 견적 점검" note="받은 견적을 올려 호환성과 가격을 점검하는 화면은 아직 개발 전이에요. 백엔드 연결 후에 열려요." />} />
            <Route path="/peripherals" element={<ComingSoonPage title="주변기기 견적" note="모니터·키보드·마우스·스피커를 고르는 화면은 아직 개발 전이에요. 백엔드 연결 후에 열려요." />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
