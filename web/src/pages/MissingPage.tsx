import { Link } from 'react-router-dom'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function MissingPage({ title = '페이지를 찾을 수 없습니다.', description = '주소를 확인하거나 시작 화면으로 돌아가주세요.' }: { title?: string; description?: string }) {
  useDocumentTitle(title.replace(/\.$/, ''))
  return (
    <section className="landing">
      <div className="landing-inner">
        <h1>{title}</h1>
        <p>{description}</p>
        <div className="report-actions">
          <Link className="ghost-btn" to="/">시작 화면</Link>
          <Link className="ghost-btn" to="/plan">플래너로 이동</Link>
        </div>
      </div>
    </section>
  )
}
