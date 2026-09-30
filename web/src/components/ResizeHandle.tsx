import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

// 패널 오른쪽 가장자리를 끌어 가로 폭을 바꾸는 손잡이. 최소·최대 폭을 넘지 못하고, 더블클릭하면 기본 폭으로 돌아간다.
// 키보드로는 손잡이에 포커스를 두고 ←/→(16px), Home/End(최소/최대)로 바꾼다. 고른 폭은 브라우저에 기억한다.

/** 저장한 폭을 읽어 오고(없으면 기본값), 범위 안으로 맞춰 돌려준다. */
export function usePanelWidth(storageKey: string, initial: number, min: number, max: number) {
  const clamp = useCallback((value: number) => Math.min(max, Math.max(min, Math.round(value))), [min, max])
  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(storageKey))
      return saved ? clamp(saved) : initial
    } catch { return initial }
  })
  useEffect(() => {
    try { localStorage.setItem(storageKey, String(width)) } catch { /* 보관 실패는 무시 */ }
  }, [storageKey, width])
  return { width, setWidth: (value: number) => setWidth(clamp(value)), reset: () => setWidth(initial), min, max }
}

interface Props {
  width: number
  min: number
  max: number
  label: string
  onChange: (value: number) => void
  onReset: () => void
}

export default function ResizeHandle({ width, min, max, label, onChange, onReset }: Props) {
  // 끌기 시작 위치는 ref 에 둔다 — 누르자마자 들어오는 이동 이벤트가 다시 그리기 전의 값을 봐도 놓치지 않게.
  const drag = useRef<{ startX: number; startWidth: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  // 끄는 동안 본문 글자가 선택되거나 폭 전환 애니메이션이 끼어들지 않게 body 에 표시한다.
  useEffect(() => {
    if (!dragging) return
    document.body.classList.add('pl-resizing')
    return () => document.body.classList.remove('pl-resizing')
  }, [dragging])

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault()
    try { event.currentTarget.setPointerCapture(event.pointerId) } catch { /* 일부 입력 장치는 캡처를 못 해도 끌기는 된다 */ }
    drag.current = { startX: event.clientX, startWidth: width }
    setDragging(true)
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (drag.current) onChange(drag.current.startWidth + event.clientX - drag.current.startX)
  }
  function stop(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    drag.current = null
    setDragging(false)
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 48 : 16
    if (event.key === 'ArrowLeft') { event.preventDefault(); onChange(width - step) }
    else if (event.key === 'ArrowRight') { event.preventDefault(); onChange(width + step) }
    else if (event.key === 'Home') { event.preventDefault(); onChange(min) }
    else if (event.key === 'End') { event.preventDefault(); onChange(max) }
  }

  return (
    <div className={'pl-resizer' + (dragging ? ' on' : '')} role="separator" aria-orientation="vertical" aria-label={label}
      aria-valuemin={min} aria-valuemax={max} aria-valuenow={width} tabIndex={0} title={`${label} — 끌어서 조절, 더블클릭하면 원래 크기`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={stop} onPointerCancel={stop}
      onDoubleClick={onReset} onKeyDown={onKeyDown} />
  )
}
