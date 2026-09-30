import { Link } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'

// 아직 백엔드와 연결하지 않은 화면. 가짜 데이터를 보여 주지 않고, 개발 전이라는 사실만 알려 준다.
export default function ComingSoonPage({ title, note }: { title: string; note: string }) {
  return (
    <PlannerShell>
      <div className="pl-page narrow">
        <div className="pl-eyebrow pl-mono">개발 전</div>
        <h2 className="pl-h2">{title}</h2>
        <div className="pl-empty">{note}</div>
        <div><Link className="pl-btn" style={{ textDecoration: 'none', display: 'inline-block' }} to="/start">새 컴퓨터 본체 추천 받기</Link></div>
      </div>
    </PlannerShell>
  )
}
