import { isMockApi } from '../../api'

const LABELS = ['CPU 후보 분석', 'GPU 균형 계산', '예산 최적화', '호환성 검사']

export function AnalyzingPanel({ progressIndex }: { progressIndex: number }) {
  return (
    <div className="analyzing-panel">
      <div>
        <div className="scan-orb" />
        <h2>최적 구성을 분석 중입니다</h2>
        <p>{isMockApi ? '가상 부품 데이터 2,418개 조합을 비교하고 있어요.' : '부품 후보와 가격, 호환성을 비교하고 있어요.'}</p>
        <div className="analysis-log">
          {LABELS.map((label, i) => (
            <span key={label} className={i <= progressIndex ? 'checked' : ''}>
              {i < progressIndex ? '✓ ' : i === progressIndex ? '● ' : '○ '}{label}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
