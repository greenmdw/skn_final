import NavigationLink from '../components/NavigationLink'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import MarketingHeader from '../components/MarketingHeader'
import SiteFooter from '../components/SiteFooter'
import '../styles/home.css'

// 메인 화면. 정적 소개 문구뿐이고 서버 데이터는 쓰지 않는다. 시작 버튼은 실제 화면으로 이동한다.
export default function HomePage() {
  const navigate = useNavigate()
  const pathsRef = useRef<HTMLElement>(null)
  const processRef = useRef<HTMLElement>(null)
  const [pathsVisible, setPathsVisible] = useState(false)
  const [processVisible, setProcessVisible] = useState(false)
  const go = (path: string) => navigate(path)

  useEffect(() => {
    const section = pathsRef.current
    if (!section) return

    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      setPathsVisible(true)
      observer.disconnect()
    }, { threshold: 0.18 })

    observer.observe(section)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const section = processRef.current
    if (!section) return

    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      setProcessVisible(true)
      observer.disconnect()
    }, { threshold: 0.5 })

    observer.observe(section)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="mk-scroll">
      <MarketingHeader />
      <div className="tf-home">
<section className="tf-hero" aria-labelledby="tf-hero-title">
<div className="tf-hero-copy">
<p className="tf-kicker">CHECK BEFORE YOU CHOOSE.</p>
<h1 id="tf-hero-title">받은 견적,<br />결제 전에 한 번 더<br /><em>TrueFit 견적 점검</em></h1>
<p className="tf-hero-lead">부품 호환성부터 가격과 성능 균형까지<br />꼼꼼하게 확인해 드립니다.</p>
<Link className="tf-primary" to="/choose">나의 견적 만들기 <span>↗</span></Link>
<p className="tf-hero-note">견적서를 올리면 부품별 점검 결과와<br />필요한 경우 교체 대안까지 알려 드립니다.</p>
</div>
</section>
<section className="tf-section tf-about" aria-labelledby="tf-about-title">
<div><p className="tf-kicker">ABOUT TrueFit</p><h2 id="tf-about-title">받은 견적은 그대로 믿지 말고,<br />한 번 더 점검하세요.</h2></div>
<div className="tf-about-copy"><h3>호환성부터 가격까지,<br />구매 전에 확인해요.</h3><p>TrueFit은 견적서의 부품을 인식하고 호환성, 가격 적정성, 용도별 성능 균형을 점검합니다. 확인이 필요한 부품과 더 나은 대안도 한곳에서 비교할 수 있어요.</p><NavigationLink to={'/check'} className="tf-text-link" onClick={() => go('/check')}>내 견적 점검하기 ↗</NavigationLink></div>
</section>
<section ref={pathsRef} className={`tf-section tf-paths${pathsVisible ? ' is-visible' : ''}`} aria-labelledby="tf-paths-title">
<p className="tf-kicker">TWO WAYS TO BUILD YOUR BASKET</p><h2 id="tf-paths-title">서로 다른 준비, 그에 맞는 기준.</h2>
<div className="tf-path-grid">
<article className="tf-path-card tf-path-card--computer">
<img className="tf-path-image" src="/assets/pc-components-banner.png" alt="" aria-hidden="true" />
<div className="tf-path-shade" aria-hidden="true" />
<div className="tf-path-content">
<p className="tf-path-label">01 · BUILD A PC</p>
<h3>컴퓨터</h3>
<p className="tf-path-description">원하는 예산과 용도에 맞춰,<br />함께 잘 작동하는 한 대를 구성합니다.</p>
<div className="tf-path-tags" aria-label="컴퓨터 추천 주요 기능"><span>◇ <b>8개 부품</b></span><span>♢ <b>호환성 검증</b></span><span>▥ <b>예산 최적화</b></span></div>
</div>
<div className="tf-path-preview" aria-label="컴퓨터 구성 분석 예시">
<p><i>✓</i><span>CPU ↔ 메인보드 호환</span><strong>호환 가능</strong></p>
<p><i>✓</i><span>예산 150만 원 이내</span><strong>142만 원</strong></p>
<p><i>✦</i><span>추천 구성 분석 완료</span><strong>완료</strong></p>
</div>
<NavigationLink to={'/choose?mode=computer'} className="tf-path-cta" onClick={() => go('/choose?mode=computer')}>컴퓨터 구성 시작하기 <span aria-hidden="true">→</span></NavigationLink>
</article>
<article className="tf-path-card tf-path-card--peripheral">
<img className="tf-path-image" src="/assets/gaming-setup-banner.png" alt="" aria-hidden="true" />
<div className="tf-path-shade" aria-hidden="true" />
<div className="tf-path-content">
<p className="tf-path-label">02 · DESK SETUP</p>
<h3>주변기기</h3>
<p className="tf-path-description">모니터, 키보드, 마우스까지<br />사용 환경에 맞는 데스크 셋업을 추천합니다.</p>
<div className="tf-path-tags" aria-label="주변기기 추천 주요 기능"><span>▣ <b>4개 품목</b></span><span>☆ <b>리뷰 기반</b></span><span>↗ <b>연결 방식 검토</b></span></div>
</div>
<div className="tf-path-preview" aria-label="주변기기 구성 분석 예시">
<p><i>✓</i><span>모니터 · 키보드 선택</span><strong>추천 완료</strong></p>
<p><i>✓</i><span>사용감 분석 완료</span><strong>완료</strong></p>
<p><i>✓</i><span>연결 방식 검토 완료</span><strong>문제없음</strong></p>
</div>
<NavigationLink to={'/peripherals'} className="tf-path-cta" onClick={() => go('/peripherals')}>주변기기 추천 받기 <span aria-hidden="true">→</span></NavigationLink>
</article>
</div></section>
<section ref={processRef} className={`tf-section tf-process${processVisible ? ' is-visible' : ''}`} aria-labelledby="tf-process-title">
<p className="tf-kicker">HOW IT WORKS</p><h2 id="tf-process-title">이야기에서 시작해, 나만의 리스트로.</h2><p className="tf-section-intro">조건을 바꾸고 후보를 비교하면서, 납득할 수 있는 장바구니를 만들어보세요.</p>
<div className="tf-step-grid">
<article><div className="tf-step-meta"><svg className="tf-step-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M7 14v6" /><circle cx="14" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></svg><b>01</b></div><h3>계획 이야기하기</h3><p>카테고리를 고르고 예산·사용 목적 등 필요한 조건을 입력해요.</p></article>
<article><div className="tf-step-meta"><svg className="tf-step-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z" /><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" /></svg><b>02</b></div><h3>추천 살펴보기</h3><p>후보별 가격과 선택 이유를 살펴보고, 원하는 제품으로 바꿔봐요.</p></article>
<article><div className="tf-step-meta"><svg className="tf-step-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 4.6 2.8 8.2 7 10 4.2-1.8 7-5.4 7-10V6l-7-3Z" /><path d="m8.5 12 2.2 2.2 4.8-5" /></svg><b>03</b></div><h3>확인하고 비교하기</h3><p>리뷰 요약과 검증 과정을 읽고, 아직 확인되지 않은 정보도 함께 체크해요.</p></article>
<article><div className="tf-step-meta"><svg className="tf-step-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-3.8L6 21V4.5Z" /><path d="M9 7h6" /></svg><b>04</b></div><h3>리스트로 남기기</h3><p>구매 시점과 목표 가격을 정해 저장하고, 리포트로 다시 확인해요.</p></article>
</div>
</section>
<section className="tf-section tf-reasons" aria-labelledby="tf-reasons-title">
<div className="tf-reasons-intro"><p className="tf-kicker">A CLEARER REASON TO CHOOSE</p><h2 id="tf-reasons-title">추천의 이유도,<span><em>모르는 부분도</em> 함께.</span></h2><p>TrueFit은 단순 추천이 아니라,<br />조건 검토부터 근거 확인, 리뷰 분석까지<br />한 번에 보여드립니다.</p><div className="tf-reasons-visual" aria-hidden="true"><img src="/assets/01-gaming-pc-photo.png" alt="" /></div></div>
<div className="tf-reason-list">
<article className="tf-reason-card tf-reason-card--condition"><div className="tf-reason-copy"><b>01</b><div><h3>조건에 맞는지 먼저</h3><p>예산, 용도, 호환성 등 원하는 조건에 맞는 조합인지 먼저 검토합니다.</p><div className="tf-reason-tags"><span>▤ 예산</span><span>⌘ 용도</span><span>✚ 호환성</span></div><small>✓ 조합 전체 기준으로 검토</small></div></div><img className="tf-reason-art" src="/assets/02-pc-parts-visual.png" alt="CPU, 그래픽카드와 메인보드 부품" /></article>
<article className="tf-reason-card tf-reason-card--evidence"><div className="tf-reason-copy"><b>02</b><div><h3>근거를 확인할 수 있게</h3><p>제조사 문서, 공식 스펙, 실제 리뷰 등 전문 매체의 정보를 기반으로 추천 근거를 제공합니다.</p><div className="tf-reason-tags"><span>▣ 제조사 문서</span><span>↗ 공식 스펙</span><span>▶ 전문 리뷰</span></div><small>✓ 출처와 확인 날짜까지 투명하게 제공</small></div></div><img className="tf-reason-art" src="/assets/03-document-visual.png" alt="인텔 제품 사양 문서" /></article>
<article className="tf-reason-card tf-reason-card--review"><div className="tf-reason-copy"><b>03</b><div><h3>리뷰는 어떻게 클렌징하나요?</h3><p>중복, 광고성, 의심 리뷰를 제거하고 실사용에 도움이 되는 리뷰만 분석에 사용합니다.</p><div className="tf-reason-tags"><span>▽ 중복 제거</span><span>⊘ 광고성 필터</span><span>⬟ 신뢰도 분석</span></div><small>✓ 더 신뢰할 수 있는 리뷰만 사용</small></div></div><img className="tf-reason-art" src="/assets/04-review-visual.png" alt="검증된 리뷰와 신뢰도 방패" /></article>
</div>
</section>
<section className="tf-section tf-faq" aria-labelledby="tf-faq-title">
<p className="tf-kicker">BEFORE YOU START</p><h2 id="tf-faq-title">자주 묻는 질문</h2>
<details><summary>로그인해야 이용할 수 있나요?</summary><p>로그인 없이도 조건을 입력하고 추천 결과를 확인할 수 있습니다. 최종 리스트를 저장하고 리포트를 확인하려면 로그인이 필요합니다.</p></details>
<details><summary>추천받은 제품을 다른 제품으로 바꿀 수 있나요?</summary><p>네. 추천 결과에서 다른 후보를 확인하고 원하는 제품으로 교체할 수 있습니다. 예산이나 원하는 조건을 변경해 다시 추천받을 수도 있습니다.</p></details>
<details><summary>최종 리스트에 담은 제품은 어떻게 구매하나요?</summary><p>각 제품의 상품 페이지 링크를 통해 판매 페이지로 이동할 수 있습니다. 최종 가격과 제품 정보를 확인한 뒤 해당 판매처에서 구매해 주세요.</p></details>
</section>

      </div>
      <SiteFooter />
    </div>
  )
}
