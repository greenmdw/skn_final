import { useModalFocus } from '../../hooks/useModalFocus'
import type { TermsArticle } from '../../data/termsContent'

export function TermsModal({ open, title, articles, onClose }: { open: boolean; title: string; articles: TermsArticle[]; onClose: () => void }) {
  const ref = useModalFocus(open, onClose)
  if (!open) return null

  return (
    <div ref={ref} tabIndex={-1} className="desk-modal-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="desk-modal terms-modal">
        <div className="desk-modal-head">
          <div><p className="eyebrow">TERMS</p><h2>{title}</h2></div>
          <button className="modal-close" type="button" aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="desk-modal-body terms-modal-body">
          {articles.map(article => (
            <section key={article.heading} className="terms-article">
              <h3>{article.heading}</h3>
              {article.clauses.map((clause, i) => <p key={i}>{clause}</p>)}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
