import { Link } from 'react-router-dom'
import Brand from './Brand'
import '../styles/footer.css'

const serviceLinks = [
  ['/start', '새 컴퓨터 본체'],
  ['/check', '받은 견적 점검'],
  ['/peripherals', '주변기기 견적'],
  ['/community', '커뮤니티'],
] as const

export default function SiteFooter() {
  return (
    <footer className="tf-footer">
      <div className="tf-footer-main">
        <section className="tf-footer-brand">
          <Link to="/" aria-label="TrueFit 홈"><Brand /></Link>
          <p>예산과 사용 목적을 바탕으로 PC와 주변기기를 함께 검토하는 구매 계획 서비스입니다.</p>
          <div><span>PC 구성</span><span>견적 점검</span><span>주변기기 추천</span></div>
        </section>

        <nav className="tf-footer-links" aria-label="푸터 서비스 메뉴">
          <div><strong>SERVICE</strong><h2>서비스</h2>{serviceLinks.map(([to, label]) => <Link to={to} key={to}>{label}</Link>)}</div>
          <div><strong>GUIDE</strong><h2>이용 안내</h2><Link to="/">서비스 소개</Link><Link to="/choose">시작 방법 선택</Link><Link to="/community?view=board&board=question">질문 게시판</Link></div>
          <div><strong>MY TRUEFIT</strong><h2>내 활동</h2><Link to="/mypage">마이페이지</Link><Link to="/mypage?tab=configs">저장한 구성</Link><Link to="/mypage?tab=community">나의 커뮤니티</Link></div>
        </nav>
      </div>

      <div className="tf-footer-notice">
        <p><b>구매 전 확인해 주세요.</b> TrueFit의 가격·재고·상품 정보는 조회 시점과 판매처에 따라 달라질 수 있습니다. 최종 제품 정보와 결제 조건은 판매 페이지에서 다시 확인해 주세요.</p>
      </div>

      <div className="tf-footer-bottom">
        <span>© 2026 TrueFit. All rights reserved.</span>
        <nav aria-label="하단 바로가기"><Link to="/">서비스 소개</Link><Link to="/community">커뮤니티</Link><Link to="/mypage">마이페이지</Link></nav>
      </div>
    </footer>
  )
}
