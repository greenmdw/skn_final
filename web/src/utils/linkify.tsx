import { Fragment, type ReactNode } from 'react'

const URL_PATTERN = /https?:\/\/[^\s<>"'`]+/g
// 문장 끝에 붙은 구두점·닫는 괄호는 주소에 넣지 않는다("…html)입니다" 에서 ")" 는 문장의 일부).
const TRAILING = /[.,;:!?)\]}>…。、）」』]+$/

/** 긴 주소는 도메인과 마지막 경로만 보여 준다. 전체 주소는 링크(와 마우스 올렸을 때 툴팁)에 그대로 있다. */
function shortUrl(url: string): string {
  if (url.length <= 48) return url.replace(/^https?:\/\//, '')
  try {
    const parsed = new URL(url)
    const last = parsed.pathname.split('/').filter(Boolean).pop() ?? ''
    const tail = last.length > 28 ? `${last.slice(0, 28)}…` : last
    return tail ? `${parsed.host}/…/${tail}` : parsed.host
  } catch {
    return `${url.slice(0, 44)}…`
  }
}

/** 글 속의 http(s) 주소를 눌러서 열 수 있는 링크로 바꾼다. 다른 글자는 그대로 둔다. */
export function Linkified({ text }: { text: string }): ReactNode {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(URL_PATTERN)) {
    const raw = match[0]
    const url = raw.replace(TRAILING, '')
    if (!url) continue
    const start = match.index ?? 0
    if (start > last) parts.push(text.slice(last, start))
    parts.push(
      <a key={start} href={url} target="_blank" rel="noopener noreferrer" title={url} className="tf-link">{shortUrl(url)}</a>,
    )
    last = start + url.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts.map((part, index) => <Fragment key={index}>{part}</Fragment>)}</>
}
