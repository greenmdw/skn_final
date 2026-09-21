export function EmptyPlan() {
  return (
    <div className="empty-plan">
      <div className="empty-visual">
        <img className="empty-image" src="/assets/pc-blueprint-empty.png" alt="부품 슬롯이 비어 있는 민트색 PC 타워 청사진" />
        <div className="empty-note" aria-hidden="true">당신의<br />최적의 PC가<br />여기에 완성됩니다.</div>
      </div>
      <div className="empty-copy">
        <h2>아직 PC 구성이 시작되지 않았어요.</h2>
        <p>왼쪽에서 하고 싶은 일과 예산을 말씀해주세요.<br />대화가 진행될수록 이곳이 실시간으로 구성됩니다.</p>
      </div>
    </div>
  )
}
