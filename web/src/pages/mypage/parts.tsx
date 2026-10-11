import type { ReactNode } from 'react'

// 마이페이지 화면들이 같이 쓰는 작은 조각들.

export const Hero = ({ icon, title, description }: { icon: ReactNode; title: string; description: string }) => (
  <header className="mp-hero">
    <div><h1>{title}</h1><p>{description}</p></div>
    <div className="mp-hero-art" aria-hidden="true">{icon}</div>
  </header>
)

export const Row = ({ icon, title, subtitle, price, children }: { icon: ReactNode; title: string; subtitle: string; price: string; children: ReactNode }) => (
  <div className="mp-row">
    <span className="mp-row-icon">{icon}</span>
    <div><strong>{title}</strong><small>{subtitle}</small></div>
    <span className="mp-row-price">{price}</span>
    <div className="mp-row-actions">{children}</div>
  </div>
)

export const Empty = ({ title, text, children }: { title: string; text: string; children?: ReactNode }) => (
  <div className="mp-empty-card"><strong>{title}</strong><span>{text}</span>{children}</div>
)

export const Icons = {
  cfg: <svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M10 17v4M14 17v4" /></svg>,
  chat: <svg viewBox="0 0 24 24"><path d="M4 4h16v13H9l-5 4Z" /><path d="M8 10h.01M12 10h.01M16 10h.01" /></svg>,
  doc: <svg viewBox="0 0 24 24"><path d="M6 2h8l4 4v16H6Z" /><path d="M14 2v5h5M9 12h6M9 16h6" /></svg>,
}
