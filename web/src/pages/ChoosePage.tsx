import { useNavigate } from 'react-router-dom'
import MarketingHeader from '../components/MarketingHeader'
import '../styles/home.css'
import { CHOICE_ART } from './home/choiceArt'

const CARDS = [
  {
    "title": "새 컴퓨터 본체",
    "text": "부품 8종을 처음부터 짭니다. 용도와 예산을 말하면 서로 맞는 한 벌을 계산해 찾아 드려요.",
    "tags": [
      "CPU",
      "GPU",
      "RAM",
      "메인보드",
      "저장장치",
      "파워",
      "케이스",
      "쿨러"
    ],
    "cta": "시작하기 →",
    "to": "/start"
  },
  {
    "title": "받은 견적 점검",
    "text": "다나와·블로그·유튜브에서 받은 견적을 캡처나 텍스트로 올리세요. 호환과 가격을 점검하고, 저장한 견적과 비교할 수 있어요.",
    "tags": [
      "이미지 캡처",
      "텍스트·파일",
      "부품 비교"
    ],
    "cta": "견적 올리기 →",
    "to": "/check"
  },
  {
    "title": "주변기기 견적",
    "text": "원하는 느낌을 말해 주세요. “조용하고 쫀득한 타건감”처럼 써 본 사람만 아는 느낌을 리뷰에서 찾아 드려요.",
    "tags": [
      "모니터",
      "키보드",
      "마우스",
      "스피커"
    ],
    "cta": "품목 고르기 →",
    "to": "/peripherals"
  }
] as const

// 장바구니를 어떤 방식으로 시작할지 고르는 화면. 정적 안내와 일러스트뿐이고 서버 데이터는 쓰지 않는다.
export default function ChoosePage() {
  const navigate = useNavigate()
  return (
    <div className="mk-scroll">
      <MarketingHeader />
      <div className="tf-choice-page">
        <div className="tf-choice-heading">
          <h1>대화하면서 PC 견적을 짜고,<br />모든 추천에 이유를 보여 드립니다.</h1>
          <p>서로 맞는 부품 한 벌은 코드로 계산합니다. 궁금한 점은 채팅으로 묻고 고치세요. 구매 결정은 직접 하시면 됩니다.</p>
        </div>
        <div className="tf-choice-grid">
          {CARDS.map((card, index) => (
            <article className="tf-choice-card" key={card.to} onClick={() => navigate(card.to)}>
              <div className="tf-choice-media tf-choice-media-pc" dangerouslySetInnerHTML={{ __html: CHOICE_ART[index] }} />
              <h2>{card.title}</h2>
              <p>{card.text}</p>
              <div className="tf-choice-tags">{card.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
              <button type="button">{card.cta}</button>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}
