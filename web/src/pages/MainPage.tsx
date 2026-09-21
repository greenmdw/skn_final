import { useNavigate } from 'react-router-dom'
import { Brand } from '../components/layout/Brand'
import { useToast } from '../state/ToastContext'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function MainPage() {
  useDocumentTitle()
  const navigate = useNavigate()
  const { showToast } = useToast()

  return (
    <div className="site-page">
      <header className="topbar">
        <Brand />
        <div className="top-actions" style={{ marginLeft: 'auto' }}>
          <button className="ghost-btn" type="button" onClick={() => navigate('/login')}>로그인</button>
          <button className="ghost-btn" type="button" onClick={() => navigate('/signup')}>회원가입</button>
        </div>
      </header>
      <main>
        <section className="hero-section">
          <div className="hero-bg"><img className="hero-image" src="/assets/hero-1.webp" alt="민트빛 조명이 비추는 집 안의 데스크톱 컴퓨터 공간" /></div>
          <div className="hero-copy">
            <p className="eyebrow">LESS SEARCHING. BETTER CHOOSING.</p>
            <h1 className="landing-title">잘 고르는 시작,<br /><span className="brand-accent">TrueFit</span></h1>
            <p className="landing-desc">Your needs, perfectly matched.<br />진짜 나에게 맞는 조합을 찾아드립니다.</p>
            <button className="analyze-btn hero-cta" type="button" onClick={() => navigate('/start')}>나의 장바구니 만들기 <span aria-hidden="true">↗</span></button>
            <p className="hero-note">무엇을 살지 막막할 땐, 대화부터 시작해 보세요.<br />이미 골라둔 견적이 있다면? <a href="#" onClick={e => { e.preventDefault(); navigate('/check') }}>호환성과 리뷰를 확인해보세요 →</a></p>
          </div>
        </section>
        <section className="about-section about-opening">
          <span className="eyebrow">ABOUT TrueFit</span>
          <div className="about-columns">
            <h2>검색은 줄이고,<br />내게 맞는 선택에 가까이.</h2>
            <div>
              <p className="about-lead">무엇을 사야 할지보다,<br />어떤 생활을 원하는지부터 시작해요.</p>
              <p>TrueFit은 예산과 사용 목적을 바탕으로 필요한 제품을 함께 정리하는 구매 계획 서비스입니다. 컴퓨터 한 대를 구성할 때도, 주변기기만 따로 고를 때도 선택의 이유와 확인할 점을 한곳에서 살펴볼 수 있어요.</p>
              <button type="button" className="about-text-link" onClick={() => navigate('/start')}>나의 계획 시작하기 ↗</button>
            </div>
          </div>
        </section>
        <section className="about-section">
          <span className="eyebrow">TWO WAYS TO BUILD YOUR BASKET</span>
          <h2>서로 다른 준비, 그에 맞는 기준.</h2>
          <div className="about-category-grid">
            <article className="about-category">
              <div className="about-card-top"><span>01 / COMPUTER</span><span>↗</span></div>
              <h3>컴퓨터</h3>
              <p className="about-lead">부품 하나보다,<br />함께 작동하는 한 대를 봅니다.</p>
              <p>게임·작업·학습 등 주로 하는 일과 예산을 알려주세요. 프로세서부터 케이스까지 필요한 구성을 모으고, 부품 간 호환성과 전체 조합의 확인 사항을 살펴보는 흐름입니다.</p>
              <ul><li>용도·해상도·예산에 맞는 구성</li><li>소켓·메모리 규격과 전력 여유 검토</li><li>대체 후보 비교와 세트 가격 확인</li></ul>
              <button type="button" className="about-text-link" onClick={() => navigate('/start')}>컴퓨터 구성 시작하기 →</button>
            </article>
            <article className="about-category">
              <div className="about-card-top"><span>02 / PERIPHERALS</span><span>↗</span></div>
              <h3>주변기기</h3>
              <p className="about-lead">모니터부터 마우스까지,<br />따로 골라도 확실하게.</p>
              <p>모니터·키보드·마우스·스피커 중 필요한 것만 골라 예산과 우선순위를 알려주세요. 컴퓨터 본체와 별개로 부속기기만 비교하고 확인하는 흐름입니다.</p>
              <ul><li>필요한 항목만 선택하는 구성</li><li>연결 방식과 예산 내 구성 검토</li><li>대체 후보 비교와 세트 가격 확인</li></ul>
              <button type="button" className="about-text-link" onClick={() => showToast('주변기기 카테고리는 아직 준비 중입니다.')}>주변기기 고르기 시작하기 →</button>
            </article>
          </div>
        </section>
        <section className="about-section">
          <span className="eyebrow">HOW IT WORKS</span>
          <h2>이야기에서 시작해, 나만의 리스트로.</h2>
          <p className="about-intro">조건을 바꾸고 후보를 비교하면서, 납득할 수 있는 장바구니를 만들어보세요.</p>
          <div className="about-process">
            <article><span className="process-number">01</span><h3>계획 이야기하기</h3><p>카테고리를 고르고 예산·사용 목적 등 필요한 조건을 입력해요.</p></article>
            <article><span className="process-number">02</span><h3>추천 살펴보기</h3><p>후보별 가격과 선택 이유를 살펴보고, 원하는 제품으로 바꿔봐요.</p></article>
            <article><span className="process-number">03</span><h3>확인하고 비교하기</h3><p>리뷰 요약과 검증 과정을 읽고, 아직 확인되지 않은 정보도 함께 체크해요.</p></article>
            <article><span className="process-number">04</span><h3>리스트로 남기기</h3><p>구매 시점과 목표 가격을 정해 저장하고, 리포트로 다시 확인해요.</p></article>
          </div>
        </section>
        <section className="about-section">
          <span className="eyebrow">A CLEARER REASON TO CHOOSE</span>
          <div className="about-columns">
            <div>
              <h2>추천의 이유도,<br />모르는 부분도 함께.</h2>
              <p>좋아 보이는 결과만 보여주기보다, 선택을 뒷받침할 정보가 무엇인지 구분하는 것을 목표로 합니다.</p>
            </div>
            <div className="about-principles">
              <article><span>01</span><div><h3>조건에 맞는지 먼저</h3><p>부품 하나하나가 아니라 컴퓨터 조합 전체를 기준으로 필요한 조건을 살펴봅니다.</p></div></article>
              <article><span>02</span><div><h3>근거를 확인할 수 있게</h3><p>문서 출처와 조회 시점을 함께 제공합니다. 정보가 없으면 검증 불가로 표시합니다.</p></div></article>
              <article><span>03</span><div><h3>리뷰는 어떻게 클렌징하나요?</h3><p>조작이 의심되거나 중복된 리뷰를 제외하고, 클렌징 전후 평점과 평점 분포를 비교해 보여드립니다.</p></div></article>
            </div>
          </div>
        </section>
        <section className="about-section about-faq" id="faq">
          <span className="eyebrow">BEFORE YOU START</span>
          <h2>자주 묻는 질문</h2>
          <details><summary>로그인해야 이용할 수 있나요?</summary><p>로그인 없이도 조건을 입력하고 추천 결과를 확인할 수 있습니다. 최종 리스트를 저장하고 리포트를 확인하려면 로그인이 필요합니다.</p></details>
          <details><summary>추천받은 제품을 다른 제품으로 바꿀 수 있나요?</summary><p>네. 추천 결과에서 다른 후보를 확인하고 원하는 제품으로 교체할 수 있습니다. 예산이나 원하는 조건을 변경해 다시 추천받을 수도 있습니다.</p></details>
          <details><summary>최종 리스트에 담은 제품은 어떻게 구매하나요?</summary><p>각 제품의 상품 페이지 링크를 통해 판매 페이지로 이동할 수 있습니다. 최종 가격과 제품 정보를 확인한 뒤 해당 판매처에서 구매해 주세요.</p></details>
        </section>
      </main>
    </div>
  )
}
