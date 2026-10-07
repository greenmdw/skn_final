import { useTheme } from '../state/theme'

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const light = theme === 'light'
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme}
      aria-label={light ? '다크 모드로 변경' : '라이트 모드로 변경'} title={light ? '다크 모드' : '라이트 모드'}>
      <span aria-hidden="true">{light ? '☾' : '☀'}</span>
      <b>{light ? '다크' : '라이트'}</b>
    </button>
  )
}
