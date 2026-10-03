import type { Api, PeripheralCheck, PeripheralItem, PeripheralText } from '../types'
import { request } from './client'
import { isNotFound } from './session'
import type { WirePeripheralItem, WirePeripheralText, WirePeripherals } from './wire'

// 주변기기 추천(개발요청 6번). PC 견적 대화와 무관하게 호출할 수 있지만, 경로에 목록(list) id 가 필요해서
// 빈 세션 하나를 만들어 재사용한다. 서버가 그 세션을 못 찾으면(로그아웃·다른 계정) 새로 만들어 한 번만 다시 시도한다.

let cachedListId: string | null = null

async function ensureListId(): Promise<string> {
  if (cachedListId) return cachedListId
  const { list_id: listId } = await request<{ list_id: string }>('POST', '/session')
  cachedListId = listId
  return listId
}

const textFromWire = (t: WirePeripheralText): PeripheralText => ({
  status: (['pending', 'ready', 'failed'].includes(t.status) ? t.status : 'none') as PeripheralText['status'],
  text: t.text,
})

const itemFromWire = (i: WirePeripheralItem): PeripheralItem => ({
  kind: i.kind,
  kindLabel: i.kind_label,
  product: { name: i.product.name, brand: i.product.brand, productUrl: i.product.product_url, imageUrl: i.product.image_url },
  price: i.price,
  priceNote: i.price_note,
  requirement: i.requirement,
  checks: i.checks.map(c => ({ ...c, state: (['ok', 'fail'].includes(c.state) ? c.state : 'unknown') as PeripheralCheck['state'] })),
  reason: textFromWire(i.reason),
  alternatives: i.alternatives,
  guide: textFromWire(i.guide),
})

export const peripherals: Api['peripherals'] = {
  async recommend(req) {
    const body = {
      kinds: req.kinds,
      budget_max: req.budgetMax,
      purpose: req.purpose,
      priority: req.priority,
      noise_sensitive: req.noiseSensitive,
      resolution: req.resolution,
      pc_list_id: req.pcListId,
    }
    const call = async (listId: string) => request<WirePeripherals>('POST', `/session/${listId}/peripherals/recommend`, body)
    let wire: WirePeripherals
    try {
      wire = await call(await ensureListId())
    } catch (error) {
      if (!isNotFound(error)) throw error
      cachedListId = null
      wire = await call(await ensureListId())
    }
    return {
      status: wire.status,
      items: wire.items.map(itemFromWire),
      empty: wire.empty,
      referencePrice: wire.totals.reference_price,
      totalNote: wire.totals.note,
    }
  },
}
