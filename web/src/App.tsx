import { Navigate, Routes, Route, useLocation } from 'react-router-dom'
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
import ComparePage from './pages/check/ComparePage'
import ConfirmPage from './pages/check/ConfirmPage'
import ResumePage from './pages/check/ResumePage'
import PartsPage from './pages/check/PartsPage'
import ReplacePage from './pages/check/ReplacePage'
import ReviewPage from './pages/check/ReviewPage'
import UploadPage from './pages/check/UploadPage'
import PeripheralsPage from './pages/PeripheralsPage'
import MyPage from './pages/MyPage'
import CommunityPage from './pages/community/CommunityPage'
import './styles/theme.css'

// 같은 모드에서 "새 견적"을 눌러도 주소는 유지되므로, 전달된 키로 화면을 다시 만들어
// 이전 대화의 입력·첨부·분석 결과가 새 대화에 남지 않게 한다.
function CheckRoute() {
  const location = useLocation()
  return <CheckPage key={location.state?.newConversationKey ?? 'check'} />
}

function UploadRoute() {
  const location = useLocation()
  return <UploadPage key={location.state?.newConversationKey ?? 'check'} />
}

function PeripheralsRoute() {
  const location = useLocation()
  return <PeripheralsPage key={location.state?.newConversationKey ?? 'peripherals'} />
}

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
            {/* 재기획 새 화면이 /check 를 쓴다. 구 화면은 새 화면이 안정될 때까지 /check-legacy 에 남겨 둔다(재기획 8단계) */}
            <Route path="/check" element={<UploadRoute />} />
            <Route path="/check/:id" element={<ResumePage />} />
            <Route path="/check/:id/parts" element={<PartsPage />} />
            <Route path="/check/:id/review" element={<ReviewPage />} />
            <Route path="/check/:id/replace" element={<ReplacePage />} />
            <Route path="/check/:id/confirm" element={<ConfirmPage />} />
            <Route path="/check/:id/compare" element={<ComparePage />} />
            <Route path="/check-legacy" element={<CheckRoute />} />
            <Route path="/peripherals" element={<PeripheralsRoute />} />
            <Route path="/mypage" element={<MyPage />} />
            <Route path="/community" element={<CommunityPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
