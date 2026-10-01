import { useEffect, useRef, useState } from 'react'
import { isoToKo, koToIso } from '../utils/format'

// 한국식 날짜 입력(YY/MM/DD). 브라우저 기본 날짜칸(type="date")은 사용자의 OS 언어에 따라 mm/dd/yyyy 로 보여서,
// 글자 입력칸으로 직접 받고 숫자를 치면 / 를 자동으로 넣는다. 달력으로 고르고 싶으면 오른쪽 버튼을 누른다.
// 밖으로 내보내는 값은 서버가 받는 ISO(yyyy-mm-dd)다. 칸이 비어 있으면 '' 이고, 형식이 틀리면 ok 가 false 다.
interface Props {
  value: string
  onChange: (iso: string, ok: boolean) => void
  ariaLabel?: string
}

/** 입력·붙여넣기 문자열 → 숫자 6자리(yymmdd). 2026-10-05·20261005 처럼 연도 4자리로 붙여넣어도 받는다 */
function toDigits(raw: string): string {
  const iso = /^\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})/.exec(raw)
  if (iso) return (iso[1].slice(2) + iso[2].padStart(2, '0') + iso[3].padStart(2, '0')).slice(0, 6)
  const digits = raw.replace(/\D/g, '')
  return (digits.length > 6 && digits.startsWith('20') ? digits.slice(2) : digits).slice(0, 6)
}

export default function DateInput({ value, onChange, ariaLabel = '날짜' }: Props) {
  const [text, setText] = useState(isoToKo(value))
  const [touched, setTouched] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  // 부모가 값을 바꿔 주면(예: 달력으로 고름) 글자 칸도 따라간다. 타이핑 중인 미완성 값('')은 건드리지 않는다.
  useEffect(() => {
    if (value && value !== koToIso(text)) setText(isoToKo(value))
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  function onText(raw: string) {
    const digits = toDigits(raw)
    const next = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 6)].filter(Boolean).join('/')
    setText(next)
    if (digits.length === 0) { onChange('', true); return }
    const iso = digits.length === 6 ? koToIso(next) : null
    onChange(iso ?? '', iso !== null)
  }
  function onPicked(iso: string) {
    setText(isoToKo(iso))
    onChange(iso, true)
  }
  function openPicker() {
    const native = picker.current
    if (!native) return
    if (typeof native.showPicker === 'function') native.showPicker()
    else native.click()
  }

  const invalid = touched && text !== '' && koToIso(text) === null
  return (
    <div className="pl-date">
      <input inputMode="numeric" placeholder="YY/MM/DD" value={text} aria-label={ariaLabel} aria-invalid={invalid}
        onChange={event => onText(event.target.value)} onBlur={() => setTouched(true)} />
      <button type="button" className="pl-date-btn" onClick={openPicker} aria-label={`${ariaLabel} 달력으로 고르기`} title="달력으로 고르기">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
      </button>
      <input ref={picker} type="date" className="pl-date-native" tabIndex={-1} aria-hidden="true" value={value} onChange={event => event.target.value && onPicked(event.target.value)} />
      {invalid && <div className="pl-date-err" role="alert">YY/MM/DD 형식으로 입력해 주세요. 예: 26/10/05</div>}
    </div>
  )
}
