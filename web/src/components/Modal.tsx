import { useEffect, useRef, type ReactNode } from 'react'

// 기본 <dialog> 를 감싼 대화상자. open 이 바뀌면 열고 닫으며, 바깥(배경)을 누르거나 Esc 로 닫힌다.
export default function Modal({ open, onClose, className, children }: { open: boolean; onClose: () => void; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) { dialog.showModal(); dialog.scrollTop = 0 }
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog ref={ref} className={className} onClose={onClose} onClick={event => { if (event.target === ref.current) onClose() }}>
      {open ? children : null}
    </dialog>
  )
}
