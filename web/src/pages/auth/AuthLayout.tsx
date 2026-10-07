import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ThemeToggle from '../../components/ThemeToggle'
import '../../styles/auth.css'

// 옛 authShell(): 위쪽에 "← TrueFit" 홈 링크와 로그인↔회원가입 전환 링크, 아래에 카드.
export default function AuthLayout({ switcher, children }: { switcher: ReactNode; children: ReactNode }) {
  return (
    <div className="auth-scroll">
      <section className="flow auth-route">
        <div className="auth-page">
          <div className="auth-wrap">
            <div className="auth-top">
              <Link className="auth-back" to="/">← TrueFit</Link>
              <div className="auth-top-actions"><span>{switcher}</span><ThemeToggle /></div>
            </div>
            {children}
          </div>
        </div>
      </section>
    </div>
  )
}
