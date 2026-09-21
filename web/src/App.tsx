import { RouteScrollReset } from './components/layout/RouteScrollReset'
import { MissingPage } from './pages/MissingPage'
import { Routes, Route } from 'react-router-dom'
import { ToastProvider } from './state/ToastProvider'
import { SetupsProvider } from './state/SetupsProvider'
import { PlanProvider } from './state/PlanProvider'
import { MainPage } from './pages/MainPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { StartPage } from './pages/StartPage'
import { CheckPage } from './pages/CheckPage'
import { ReviewPage } from './pages/ReviewPage'
import { PlanPage } from './pages/PlanPage'
import { ConfirmPage } from './pages/ConfirmPage'
import { ReportPage } from './pages/ReportPage'

export default function App() {
  return (
    <ToastProvider>
      <SetupsProvider>
        <PlanProvider>
          <RouteScrollReset />
          <Routes>
            <Route path="/" element={<MainPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/start" element={<StartPage />} />
            <Route path="/check" element={<CheckPage />} />
            <Route path="/check/review" element={<ReviewPage />} />
            <Route path="/plan" element={<PlanPage />} />
            <Route path="/plan/confirm" element={<ConfirmPage />} />
            <Route path="/plan/report/:setupId" element={<ReportPage />} />
            <Route path="*" element={<MissingPage />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
