import { useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'truefit.theme'
const THEME_EVENT = 'truefit-theme-change'

function storedTheme(): Theme {
  try { return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark' } catch { return 'dark' }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

applyTheme(storedTheme())

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(storedTheme)

  useEffect(() => {
    const sync = () => setThemeState(storedTheme())
    window.addEventListener(THEME_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(THEME_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  function setTheme(next: Theme) {
    try { localStorage.setItem(STORAGE_KEY, next) } catch { /* 저장할 수 없어도 현재 화면에는 적용한다 */ }
    applyTheme(next)
    setThemeState(next)
    window.dispatchEvent(new Event(THEME_EVENT))
  }

  return { theme, setTheme, toggleTheme: () => setTheme(theme === 'dark' ? 'light' : 'dark') }
}
