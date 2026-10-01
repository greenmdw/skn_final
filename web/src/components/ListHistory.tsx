import { useEffect, useState } from 'react'
import { api, type HistoryEventKind, type HistoryStepKind, type ListHistory as History } from '../api'

// 견적 리스트 히스토리: 이 견적이 대화로 어떻게 이 구성이 됐는지. 부품 카드의 "고른 이유"가 "이 제품이 왜 좋은가"라면
// 여기는 "대화가 어떻게 이 구성을 만들었나"다. 세 층으로 보여 준다 —
// 요약(2~3문장) → 이렇게 정해졌어요(결과를 바꾼 것만, 서버 history_journey) → 자세히(대화 순서 그대로, 접어 둔다).
// 내용은 서버(GET /lists/{id}/history)가 기록에서 만든다. 불러오지 못하면 지어내지 않고 안내만 한다.
const KIND_LABEL: Record<HistoryEventKind, string> = {
  condition: '조건', recommend: '추천', question: '질문', swap: '교체', remove: '제외', confirm: '확정',
}
const STEP_LABEL: Record<HistoryStepKind, string> = {
  start: '시작', change: '조건 변경', swap: '직접 교체', remove: '직접 제외', unapplied: '반영 못 함', confirm: '확정',
}

export default function ListHistory({ listId, revisionNo }: { listId: string; revisionNo?: number }) {
  const [history, setHistory] = useState<History | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    setHistory(null)
    setFailed(false)
    api.setups.history(listId, revisionNo)
      .then(result => { if (alive) setHistory(result) })
      .catch(() => { if (alive) setFailed(true) })
    return () => { alive = false }
  }, [listId, revisionNo])

  return (
    <section className="pl-history" aria-labelledby="pl-history-title">
      <div className="pl-section-title">
        <b id="pl-history-title">견적 리스트 히스토리</b>
        <span className="pl-note">대화가 어떻게 이 구성을 만들었는지</span>
      </div>
      {history?.summary
        ? <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>{history.summary}</p>
        : <div className="pl-empty">{failed
          ? '이 견적의 히스토리를 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.'
          : '이 견적을 만들기까지 나눈 대화와 고른 부품을 정리하는 중이에요…'}</div>}
      {history && history.steps.length > 0 && (
        <div>
          <div className="pl-group-title" style={{ marginBottom: 8 }}>이렇게 정해졌어요</div>
          <ol className="pl-steps">
            {history.steps.map((step, index) => (
              <li key={index} className={'k-' + step.kind}>
                <span className="n">{STEP_LABEL[step.kind]}</span>
                <div>
                  <div>{step.text}</div>
                  {step.quote && <div className="q">“{step.quote}”</div>}
                  {step.changes.length > 0 && (
                    <ul className="c">{step.changes.map((change, i) => <li key={i}>{change}</li>)}</ul>
                  )}
                  {step.notes.map((note, i) => <div key={i} className="note">{note}</div>)}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      {history && history.events.length > 0 && (
        <details className="pl-history-more">
          <summary>대화 순서대로 자세히 보기</summary>
          <ol>
            {history.events.map((event, index) => (
              <li key={index}><span className="n">{KIND_LABEL[event.kind]}</span><span>{event.text}</span></li>
            ))}
          </ol>
        </details>
      )}
    </section>
  )
}
