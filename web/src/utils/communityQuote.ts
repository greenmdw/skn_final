/**
 * 그려 놓은 글 본문(DOM)에서 인용 문장이 있는 자리를 찾아 <mark> 로 감싼다. 사용기 분석이 문장의 줄바꿈·공백을 정리했을 수 있어서
 * 공백 차이는 무시하고 찾고, 전체가 안 맞으면 앞부분(24자)만으로 한 번 더 찾는다. 서식(굵게·목록·표) 안에 있어도 찾는다.
 * 못 찾으면 null — 글이 수정된 경우이고, 이때는 아무것도 바꾸지 않는다.
 */
const escapeRegex = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function loosePattern(text: string, gap: string): RegExp | null {
  const clean = text.trim().replace(/^[“"'‘]+|[”"'’]+$/g, '').trim()
  if (clean.length < 4) return null
  return new RegExp(clean.split(/\s+/).map(escapeRegex).join(gap))
}

interface Segment { node: Text; start: number; end: number }

/** 글자 노드들을 이어 붙인 문자열에서 match 가 걸친 노드별 구간을 구한다. separator 만큼의 글자는 노드에 속하지 않는다. */
function segmentsOf(nodes: Text[], separator: string, start: number, end: number): Segment[] {
  const segments: Segment[] = []
  let offset = 0
  for (const node of nodes) {
    const length = node.nodeValue?.length ?? 0
    const from = Math.max(start, offset)
    const to = Math.min(end, offset + length)
    if (from < to) segments.push({ node, start: from - offset, end: to - offset })
    offset += length + separator.length
  }
  return segments
}

/** 이미 감싼 강조를 걷어 낸다. 같은 글에 효과가 다시 돌아도(개발 모드의 이중 실행·화면 전환) 강조가 겹치지 않게 한다. */
export function clearQuoteHighlight(root: HTMLElement) {
  root.querySelectorAll('mark.cm-quote-hit').forEach(mark => mark.replaceWith(...Array.from(mark.childNodes)))
  root.normalize()
}

export function highlightQuote(root: HTMLElement, sentence: string | null | undefined): HTMLElement | null {
  clearQuoteHighlight(root)
  if (!sentence) return null
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeValue && node.nodeValue.length > 0) nodes.push(node as Text)
  }
  // 줄바꿈(<br>)·문단·셀 경계에는 글자가 없으므로, 노드 사이에 공백 하나를 끼워 단어가 붙어 보이지 않게 먼저 찾아본다.
  for (const [separator, gap] of [[' ', '\\s+'], ['', '\\s*']] as const) {
    const full = nodes.map(node => node.nodeValue).join(separator)
    const match = [loosePattern(sentence, gap), loosePattern(sentence.trim().slice(0, 24), gap)]
      .map(pattern => pattern?.exec(full)).find(found => found)
    if (!match) continue
    // 줄바꿈·셀 사이의 공백뿐인 노드는 감싸지 않는다(눈에 띄는 칠이 없고 구조만 늘어난다).
    const segments = segmentsOf(nodes, separator, match.index, match.index + match[0].length)
      .filter(segment => (segment.node.nodeValue ?? '').slice(segment.start, segment.end).trim() !== '')
    if (!segments.length) continue
    let first: HTMLElement | null = null
    // 뒤에서부터 감싸야 앞쪽 구간의 위치가 어긋나지 않는다.
    for (const segment of [...segments].reverse()) {
      const target = segment.node.splitText(segment.start)
      target.splitText(segment.end - segment.start)
      const mark = document.createElement('mark')
      mark.className = 'cm-quote-hit'
      target.parentNode?.insertBefore(mark, target)
      mark.appendChild(target)
      first = mark
    }
    if (first) first.id = 'cm-quote-hit'
    return first
  }
  return null
}
