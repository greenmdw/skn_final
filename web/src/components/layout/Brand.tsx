import { Link } from 'react-router-dom'

export function Brand() {
  function scrollTopSmooth() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <Link to="/" className="brand" aria-label="TrueFit 홈페이지로 이동" onClick={scrollTopSmooth}>
      <div className="brand-mark" aria-hidden="true"><span className="m1" /><span className="m2" /><span className="m3" /></div>
      <div className="brand-name">True<em>Fit</em></div>
    </Link>
  )
}
