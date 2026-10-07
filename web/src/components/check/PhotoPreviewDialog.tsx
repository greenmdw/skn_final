import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { fileSize } from '../../utils/checkReview'
import type { UploadFile } from './QuoteUploader'

const MIN_ZOOM = 1
const MAX_ZOOM = 6
const clamp = (value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value))

/** 올린 사진을 크게 보는 창. Ctrl+휠·버튼·키보드로 확대(원래 크기 아래로는 줄이지 않음)하고, 확대하면 끌어서 이동한다. */
export default function PhotoPreviewDialog({ files, index, onIndex, onClose, onRemove }: {
  files: UploadFile[]
  index: number
  onIndex: (index: number) => void
  onClose: () => void
  onRemove: (id: string) => void
}) {
  const file = files[index]
  const stageRef = useRef<HTMLDivElement>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const anchor = useRef<{ x: number; y: number; ratioX: number; ratioY: number } | null>(null)
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const [zoom, setZoom] = useState(1)
  const [fit, setFit] = useState<{ w: number; h: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const zoomTo = useCallback((next: number, point?: { x: number; y: number }) => {
    const image = imageRef.current
    if (image) {
      const rect = image.getBoundingClientRect()
      const stage = stageRef.current?.getBoundingClientRect()
      const x = point?.x ?? (stage ? stage.left + stage.width / 2 : rect.left + rect.width / 2)
      const y = point?.y ?? (stage ? stage.top + stage.height / 2 : rect.top + rect.height / 2)
      anchor.current = { x, y, ratioX: (x - rect.left) / rect.width, ratioY: (y - rect.top) / rect.height }
    }
    setZoom(clamp(next))
  }, [])

  // 확대·축소 뒤에도 커서(또는 창 중앙) 아래의 그림 위치가 그대로 보이게 스크롤을 맞춘다.
  useLayoutEffect(() => {
    const current = anchor.current
    const stage = stageRef.current
    const image = imageRef.current
    if (!current || !stage || !image) return
    const rect = image.getBoundingClientRect()
    stage.scrollLeft += rect.left + current.ratioX * rect.width - current.x
    stage.scrollTop += rect.top + current.ratioY * rect.height - current.y
    anchor.current = null
  }, [zoom])

  // 사진을 바꾸면 처음 크기로 돌린다.
  useEffect(() => {
    setZoom(1)
    setFit(null)
    anchor.current = null
    stageRef.current?.scrollTo({ left: 0, top: 0 })
  }, [file?.id])

  const measureFit = useCallback(() => {
    const image = imageRef.current
    if (image && zoom === 1) setFit({ w: image.offsetWidth, h: image.offsetHeight })
  }, [zoom])

  useEffect(() => {
    window.addEventListener('resize', measureFit)
    return () => window.removeEventListener('resize', measureFit)
  }, [measureFit])

  // Ctrl(또는 ⌘)+휠로만 확대·축소한다. 그냥 휠은 확대한 사진을 위아래로 스크롤하는 데 쓴다.
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const factor = Math.exp(-event.deltaY * 0.0015)
      setZoom(previous => {
        const next = clamp(previous * factor)
        if (next === previous) return previous
        const image = imageRef.current
        if (image) {
          const rect = image.getBoundingClientRect()
          anchor.current = { x: event.clientX, y: event.clientY, ratioX: (event.clientX - rect.left) / rect.width, ratioY: (event.clientY - rect.top) / rect.height }
        }
        return next
      })
    }
    stage.addEventListener('wheel', onWheel, { passive: false })
    return () => stage.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      else if (event.key === 'ArrowLeft' && index > 0) onIndex(index - 1)
      else if (event.key === 'ArrowRight' && index < files.length - 1) onIndex(index + 1)
      else if (event.key === '+' || event.key === '=') zoomTo(zoom * 1.25)
      else if (event.key === '-' || event.key === '_') zoomTo(zoom / 1.25)
      else if (event.key === '0') zoomTo(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, files.length, zoom, onClose, onIndex, zoomTo])

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const stage = stageRef.current
    if (!stage || zoom <= 1 || event.button !== 0) return
    drag.current = { x: event.clientX, y: event.clientY, left: stage.scrollLeft, top: stage.scrollTop }
    setDragging(true)
    stage.setPointerCapture(event.pointerId)
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const stage = stageRef.current
    const start = drag.current
    if (!stage || !start) return
    stage.scrollLeft = start.left - (event.clientX - start.x)
    stage.scrollTop = start.top - (event.clientY - start.y)
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag.current) return
    drag.current = null
    setDragging(false)
    stageRef.current?.releasePointerCapture(event.pointerId)
  }

  if (!file) return null
  const sized = zoom !== 1 && fit
  const percent = Math.round(zoom * 100)

  return (
    <div className="ck-dialog-back" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section className="ck-dialog ck-preview-dialog" role="dialog" aria-modal="true" aria-label={`${file.file.name} 미리보기`}>
        <div className="ck-modal-head">
          <div>
            <h2>{index + 1}번 사진 · {index === 0 ? '전체 견적' : '상세 보완'}</h2>
            <p className="ck-modal-intro">{file.file.name} · {fileSize(file.file.size)}</p>
          </div>
          <div className="ck-preview-tools" role="group" aria-label="확대·축소" title="Ctrl + 마우스 휠로도 확대·축소할 수 있어요">
            <button type="button" onClick={() => zoomTo(zoom / 1.25)} disabled={zoom <= MIN_ZOOM} aria-label="축소" title="축소 ( - )">−</button>
            <button type="button" className="ck-preview-percent" onClick={() => zoomTo(1)} title="화면에 맞추기 ( 0 )" aria-label={`현재 ${percent}%, 눌러서 화면에 맞추기`}>{percent}%</button>
            <button type="button" onClick={() => zoomTo(zoom * 1.25)} disabled={zoom >= MAX_ZOOM} aria-label="확대" title="확대 ( + )">＋</button>
          </div>
          <button type="button" className="ck-close" onClick={onClose} aria-label="미리보기 닫기">×</button>
        </div>
        <div className="ck-preview-wrap">
          <div
            className={`ck-preview-stage${zoom > 1 ? ' zoomed' : ''}${dragging ? ' dragging' : ''}`} ref={stageRef}
            onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}
          >
            <img
              ref={imageRef} src={file.url} alt={`${file.file.name} 원본 미리보기`} draggable={false} onLoad={measureFit}
              onDoubleClick={event => zoomTo(zoom === 1 ? 2.5 : 1, { x: event.clientX, y: event.clientY })}
              style={sized ? { width: fit.w * zoom, height: fit.h * zoom, maxWidth: 'none', maxHeight: 'none' } : undefined}
            />
          </div>
          <button type="button" className="ck-preview-nav prev" disabled={index === 0} onClick={() => onIndex(index - 1)} aria-label="이전 사진">‹</button>
          <button type="button" className="ck-preview-nav next" disabled={index === files.length - 1} onClick={() => onIndex(index + 1)} aria-label="다음 사진">›</button>
        </div>
        <div className="ck-modal-foot">
          <span className="ck-modal-foot-note">Ctrl + 마우스 휠로 확대·축소하고, 확대하면 끌어서 이동할 수 있어요.{files.length > 1 ? ' ← → 키로 다른 사진을 넘겨보세요.' : ''}</span>
          <button type="button" className="ck-text-button" onClick={() => { onClose(); onRemove(file.id) }}>이 사진 삭제</button>
          <button type="button" className="ck-primary" onClick={onClose}>닫기</button>
        </div>
      </section>
    </div>
  )
}
