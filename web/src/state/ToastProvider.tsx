import { useEffect, useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type ToastContextValue } from './ToastContext'

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState('')
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => () => { if (timerRef.current) window.clearTimeout(timerRef.current) }, [])

  const showToast = useCallback((text: string) => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    setMessage(text)
    setVisible(true)
    timerRef.current = window.setTimeout(() => setVisible(false), 2300)
  }, [])

  const value = useMemo<ToastContextValue>(() => ({ showToast }), [showToast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={'toast' + (visible ? ' show' : '')} role="status" aria-live="polite">
        {message}
      </div>
    </ToastContext.Provider>
  )
}

