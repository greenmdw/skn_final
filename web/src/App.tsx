import { Routes, Route } from 'react-router-dom'
import { ToastProvider } from './state/ToastProvider'
import { SetupsProvider } from './state/SetupsProvider'
import { PlanProvider } from './state/PlanProvider'

function TrueFitPrototype() {
  return (
    <main className="app-shell">
      <iframe
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
            <Route path="*" element={<TrueFitPrototype />} />
          </Routes>
        </PlanProvider>
      </SetupsProvider>
    </ToastProvider>
  )
}
