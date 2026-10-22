import { useState } from 'react'
import type { PeripheralKind } from '../api/types'
import type { PartKey } from '../state/types'

// 카테고리 아이콘(24x24, 선). 제품 이미지가 없거나 불러오지 못하면 이걸 보여 준다.
const ICONS: Record<string, string[]> = {
  cpu: ['M7 7h10v10H7z', 'M10 10h4v4h-4z', 'M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3'],
  gpu: ['M3 8h18v8H3z', 'M6 16v2M18 16v2', 'M9 12a2 2 0 1 0 4 0a2 2 0 1 0-4 0'],
  ram: ['M3 9h18v6H3z', 'M7 15v2M11 15v2M15 15v2M6 11h2M11 11h2M16 11h2'],
  board: ['M4 4h16v16H4z', 'M8 8h4v4H8z', 'M15 8h2M15 12h2M8 16h8'],
  ssd: ['M5 6h14v12H5z', 'M8 10h8M8 14h5'],
  psu: ['M4 7h16v10H4z', 'M9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0', 'M7 5v2M17 5v2'],
  case: ['M7 3h10v18H7z', 'M10 7h4M10 11h4', 'M12 17h.01'],
  cooler: ['M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0', 'M12 10c0-4 3-5 4-3M14 12c4 0 5 3 3 4M12 14c0 4-3 5-4 3M10 12c-4 0-5-3-3-4'],
  monitor: ['M3 5h18v11H3z', 'M9 20h6M12 16v4'],
  keyboard: ['M3 7h18v10H3z', 'M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M7 14h10'],
  mouse: ['M8 3h8a3 3 0 0 1 3 3v8a7 7 0 0 1-14 0V6a3 3 0 0 1 3-3z', 'M12 3v6'],
  speaker: ['M7 3h10v18H7z', 'M12 8h.01', 'M12 16a3 3 0 1 0 0.01 0'],
}

export default function ProductThumb({ imageUrl, partKey, name }: { imageUrl?: string | null; partKey: PartKey | PeripheralKind | null; name: string }) {
  const [failed, setFailed] = useState(false)
  if (imageUrl && !failed) {
    return (
      <span className="pl-thumb">
        <img src={imageUrl} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      </span>
    )
  }
  const shapes = ICONS[partKey ?? 'cpu'] ?? ICONS.cpu
  return (
    <span className="pl-thumb icon" aria-hidden="true">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {shapes.map(d => <path key={d} d={d} />)}
      </svg>
    </span>
  )
}
