import { useEffect, useRef } from 'react'

export function useModalFocus(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose }, [onClose])
  useEffect(() => {
    const root = ref.current
    if (!open || !root) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusable = () => Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]')).filter(el => el.getClientRects().length > 0)
    const first = () => root.querySelector<HTMLElement>('[data-autofocus]') ?? focusable()[0] ?? root
    first().focus()
    function keydown(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close.current(); return }
      if (e.key !== 'Tab') return
      const list = focusable()
      if (!list.length) { e.preventDefault(); root?.focus(); return }
      const index = list.indexOf(document.activeElement as HTMLElement)
      if (index === -1 || (e.shiftKey && index === 0) || (!e.shiftKey && index === list.length - 1)) {
        e.preventDefault()
        list[e.shiftKey ? list.length - 1 : 0].focus()
      }
    }
    function focusin(e: FocusEvent) {
      if (e.target instanceof Node && !root!.contains(e.target)) first().focus()
    }
    document.addEventListener('keydown', keydown, true)
    document.addEventListener('focusin', focusin)
    return () => {
      document.removeEventListener('keydown', keydown, true)
      document.removeEventListener('focusin', focusin)
      document.body.style.overflow = oldOverflow
      if (previous?.isConnected) previous.focus()
    }
  }, [open])
  return ref
}
