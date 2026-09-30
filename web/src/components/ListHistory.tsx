import { useEffect, useState } from 'react'
import { api, type HistoryEventKind, type ListHistory as History } from '../api'

// 견적 리스트 히스토리: 사용자가 사이트에서 채팅으로 이것저것 묻고, 부품을 바꿔 최종 리스트로 만든 여정.
// 사건 목록과 요약 문장은 서버(GET /lists/{id}/history)가 만든다 — 사건은 코드가 기록에서 뽑고, 요약은 LLM 이
// 그 사건만 보고 쓴다(실패하면 규칙 문장). 불러오지 못하면 지어내지 않고 안내만 한다.
const KIND_LABEL: Record<HistoryEventKind, string> = {
  condition: '조건', recommend: '추천', question: '질문', swap: '교체', remove: '제외', confirm: '확정',
}

export default function ListHistory({ listId }: { listId: string }) {
  const [history, setHistory] = useState<History | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    setHistory(null)
    setFailed(false)
    api.setups.history(listId)
      .then(result => { if (alive) setHistory(result) })
      .catch(() => { if (alive) setFailed(true) })
    return () => { alive = false }
  }, [listId])

  return (
    <section className="pl-history" aria-labelledby="pl-history-title">
      <div className="pl-section-title">
        <b id="pl-history-title">견적 리스트 히스토리</b>
        <span className="pl-note">채팅으로 물어보고 골라 최종 리스트를 만든 여정</span>
      </div>
      {history?.summary
        ? <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>{history.summary}</p>
        : <div className="pl-empty">{failed
          ? '이 견적의 히스토리를 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.'
          : '이 견적을 만들기까지 나눈 대화와 고른 부품을 정리하는 중이에요…'}</div>}
      {history && history.events.length > 0 && (
        <div>
          <div className="pl-group-title" style={{ marginBottom: 8 }}>지나온 과정</div>
          <ol>
            {history.events.map((event, index) => (
              <li key={index}><span className="n">{KIND_LABEL[event.kind]}</span><span>{event.text}</span></li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}
