import { memo, useEffect, useMemo, useRef, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import type { WireCommunityImage } from '../api/http/community'
import { clearQuoteHighlight, highlightQuote } from '../utils/communityQuote'

// 글 본문을 "제한된 Markdown"으로 그린다. 이미지는 본문의 `![설명](image:<이미지 id>)` 한 줄이 가리키는 자리에 그리고,
// 본문에 마커가 없는 이미지는 본문 맨 아래에 그린다(마커 없는 예전 글의 모습은 그대로).
// 규칙은 아래와 같다. 허용: 소제목(##·###), 문단·줄바꿈, 굵게·목록·인용, 표, 링크(http·https).
// 막는 것: 원본 HTML(라이브러리가 렌더하지 않고 버린다), 외부 이미지 주소, 허용 목록 밖의 요소(코드·취소선·구분선 등은 글자만 남긴다).
// 기존 일반 텍스트 글도 같은 렌더러로 그린다 — 한 줄 바꿈은 그대로 줄바꿈(remark-breaks)이라 모습이 거의 변하지 않는다.
const ALLOWED = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'img']

/** 링크는 http·https 만, 이미지는 우리 이미지 마커(image:<id>)만 통과한다. 나머지(javascript:·data: 등)는 비운다. */
function safeUrl(url: string, key: string): string {
  if (key === 'href') return /^https?:\/\//i.test(url) ? url : ''
  if (key === 'src') return /^image:[0-9a-f-]{8,}$/i.test(url) ? url : ''
  return ''
}

// 글 제목이 대제목이다. 본문의 #(h1)는 ##처럼, ####~######는 ###처럼 그린다.
const heading = (Tag: 'h2' | 'h3') => function Heading({ node: _node, ...props }: ComponentPropsWithoutRef<'h2'> & { node?: unknown }) { return <Tag {...props} /> }

const IMAGE_MARKER = /\]\(image:([0-9a-f-]{8,})\)/gi

const components = (images: WireCommunityImage[]): Components => ({
  h1: heading('h2'), h2: heading('h2'), h3: heading('h3'), h4: heading('h3'), h5: heading('h3'), h6: heading('h3'),
  // 허용하지 않는 주소(javascript: 등)는 링크로 만들지 않고 글자만 남긴다.
  a: ({ node: _node, ...props }) => (props.href ? <a {...props} target="_blank" rel="noopener nofollow noreferrer" /> : <span>{props.children}</span>),
  // 마커의 id 가 이 글의 이미지면 그 자리에 그리고, 아니면(다른 글의 이미지·없는 id·외부 주소) 아무것도 그리지 않는다.
  img: ({ src, alt }) => {
    const id = typeof src === 'string' && src.startsWith('image:') ? src.slice('image:'.length).toLowerCase() : null
    const image = id ? images.find(entry => entry.id.toLowerCase() === id) : undefined
    return image ? <PostImage image={image} alt={alt ?? ''} /> : null
  },
  table: ({ node: _node, ...props }) => <div className="cm-md-table"><table {...props} /></div>,
})

// width·height 를 주어 이미지가 늦게 떠도 글이 위아래로 튀지 않게 한다.
function PostImage({ image, alt }: { image: WireCommunityImage; alt: string }) {
  return <img className="cm-md-img" src={image.url} width={image.width} height={image.height} alt={alt || '첨부 이미지'} loading="lazy" />
}

function MarkdownBody({ body, images, quoteSentence }: { body: string; images: WireCommunityImage[]; quoteSentence: string | null }) {
  const root = useRef<HTMLDivElement>(null)
  const mapping = useMemo(() => components(images), [images])
  // 본문에 마커가 있는 이미지는 그 자리에 그려지므로, 나머지만 본문 맨 아래에 그린다.
  const trailing = useMemo(() => {
    const used = new Set(Array.from(body.matchAll(IMAGE_MARKER), match => match[1].toLowerCase()))
    return images.filter(image => !used.has(image.id.toLowerCase()))
  }, [body, images])

  // 주변기기 견적의 인용 문장에서 들어왔으면 그 문장을 찾아 강조하고 그 자리로 간다. 못 찾으면 글 맨 위 그대로.
  // 댓글·이미지가 늦게 자리를 잡아 위치가 밀릴 수 있어 한 번 더 맞춘다.
  useEffect(() => {
    const container = root.current
    if (!container || !quoteSentence) return
    const mark = highlightQuote(container, quoteSentence)
    if (!mark) return
    const go = () => mark.scrollIntoView({ block: 'center' })
    const timers = [window.setTimeout(go, 120), window.setTimeout(go, 700)]
    return () => { timers.forEach(window.clearTimeout); clearQuoteHighlight(container) }
  }, [body, quoteSentence])

  return (
    <div className="cm-md" ref={root}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} allowedElements={ALLOWED} unwrapDisallowed skipHtml urlTransform={safeUrl} components={mapping}>
        {body}
      </ReactMarkdown>
      {trailing.map(image => <PostImage key={image.id} image={image} alt="" />)}
    </div>
  )
}

// 글이 그대로면 다시 그리지 않는다 — 인용 문장을 감싼 <mark> 를 React 가 되돌리지 않게 하려는 것이기도 하다.
export default memo(MarkdownBody)
