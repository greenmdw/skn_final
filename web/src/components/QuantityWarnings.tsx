import type { PlanItem } from '../state/types'

// 한 대에 하나만 쓰는 부품(CPU·메인보드·파워·케이스)의 수량을 2개 이상으로 올렸을 때의 안내.
// 예산 초과 안내(.pl-alert)와 같은 모양이고, 둘 다 해당하면 위아래로 함께 보인다. 막지는 않고 확인만 묻는다.
export default function QuantityWarnings({ items }: { items: PlanItem[] }) {
  return (
    <>
      {items.map(item => (
        <div className="pl-alert warn" role="alert" key={item.id}>
          <b>{item.type} ×{item.qty}</b> · 한 대에 {item.type}는 보통 1개예요. 여러 대를 구매하시나요?
        </div>
      ))}
    </>
  )
}
