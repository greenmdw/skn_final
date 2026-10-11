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
import CheckPage from './pages/CheckPage'
import PeripheralsPage from './pages/PeripheralsPage'
import MyPage from './pages/MyPage'
import './styles/theme.css'

// 모든 화면은 React로 구성하며, 서버 데이터가 필요한 기능은 실제 백엔드 API만 사용한다.
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
            <Route path="/check" element={<CheckPage />} />
            <Route path="/peripherals" element={<PeripheralsPage />} />
            <Route path="/mypage" element={<MyPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
