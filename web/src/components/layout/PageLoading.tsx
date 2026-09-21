import { useDocumentTitle } from '../../hooks/useDocumentTitle'

export function PageLoading({ message = '불러오는 중입니다...' }: { message?: string }) {
  useDocumentTitle('불러오는 중')
  return (
    <section className="landing">
      <div className="landing-inner">
        <p className="setup-hint" role="status">{message}</p>
      </div>
    </section>
  )
}
