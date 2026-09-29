import { usePlan } from '../state/PlanContext'

// 견적 리스트 히스토리: 사용자가 사이트에서 채팅으로 이것저것 묻고, 마음에 든 것(favorite)을 골라 최종 리스트로 만든 여정을
// 요약해 보여 주는 자리. 요약 문장은 서버가 만들어 줘야 하는 값이라(docs/개발요청_백엔드_및_타팀.md) 아직 없으면
// 지어내지 않고 안내만 한다. 이 브라우저에 남아 있는 이번 대화의 질문은 그대로 보여 준다.
export default function ListHistory({ listId, summary }: { listId: string; summary?: string | null }) {
  const { state, messages } = usePlan()
  // 화면에 남아 있는 대화는 지금 작업 중인 구성의 것이다. 다른 견적의 리포트에는 붙이지 않는다.
  const mine = state.currentPlan?.id === listId
  const questions = mine ? messages.filter(m => m.role === 'user').map(m => m.text) : []

  return (
    <section className="pl-history" aria-labelledby="pl-history-title">
      <div className="pl-section-title">
        <b id="pl-history-title">견적 리스트 히스토리</b>
        <span className="pl-note">채팅으로 물어보고 골라 최종 리스트를 만든 여정</span>
      </div>
      {summary
        ? <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>{summary}</p>
        : <div className="pl-empty">이 견적을 만들기까지 나눈 대화와 고른 부품을 요약해서 보여 드릴 자리예요. 요약은 준비 중이에요.</div>}
      {questions.length > 0 && (
        <div>
          <div className="pl-group-title" style={{ marginBottom: 8 }}>이번에 물어본 것</div>
          <ol>
            {questions.map((text, index) => <li key={index}><span className="n">{index + 1}</span><span>{text}</span></li>)}
          </ol>
        </div>
      )}
    </section>
  )
}
