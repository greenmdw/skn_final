import { wonFmt } from '../utils/format'

const COLORS = ['#60edc0', '#66c8f2', '#c58cff', '#f0cf85', '#ff8f80', '#8ff5d5', '#9fe0fb', '#a18aff']

// 부품별 가격 비중을 도넛으로, 가운데에 예산·사용·잔액(또는 초과)을 보여 준다. 모든 값은 서버가 준 가격에서 계산한다.
export default function BudgetDonut({ parts, budget }: { parts: { name: string; price: number }[]; budget: number | null }) {
  const used = parts.reduce((sum, part) => sum + part.price, 0)
  const base = Math.max(budget ?? 0, used) || 1
  const radius = 80
  const circumference = 2 * Math.PI * radius
  let offset = 0
  return (
    <div className="pl-donut">
      <svg width="200" height="200" viewBox="0 0 200 200" role="img" aria-label="부품별 예산 비중">
        <circle cx="100" cy="100" r={radius} fill="none" stroke="#233744" strokeWidth="22" />
        {parts.map((part, index) => {
          const length = (part.price / base) * circumference
          const segment = (
            <circle key={part.name + index} cx="100" cy="100" r={radius} fill="none" stroke={COLORS[index % COLORS.length]} strokeWidth="22"
              strokeDasharray={`${Math.max(length - 1.5, 0)} ${circumference}`} strokeDashoffset={-offset} transform="rotate(-90 100 100)">
              <title>{part.name} {wonFmt(part.price)}</title>
            </circle>
          )
          offset += length
          return segment
        })}
      </svg>
      <div className="pl-donut-mid">
        {budget !== null && <div style={{ fontSize: 11, color: '#92a4b2' }}>예산 {wonFmt(budget)}</div>}
        <div style={{ fontSize: 12 }}>사용 <b className="pl-mono">{wonFmt(used)}</b></div>
        {budget !== null && (used <= budget
          ? <div style={{ fontSize: 12, color: '#92a4b2' }}>잔액 <span className="pl-mono">{wonFmt(budget - used)}</span></div>
          : <div style={{ fontSize: 12, color: '#c58cff', fontWeight: 600 }}>초과 <span className="pl-mono">{wonFmt(used - budget)}</span></div>)}
      </div>
    </div>
  )
}
