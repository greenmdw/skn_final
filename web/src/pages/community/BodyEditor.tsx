import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent, type SyntheticEvent } from 'react'
import { ApiError } from '../../api/types'
import { communityApi, type WireCommunityImage } from '../../api/http/community'
import { useToast } from '../../state/ToastContext'

// 글 본문 편집기. 블로그처럼 글 사이에 이미지가 그림으로 바로 보인다.
// 저장 형식은 그대로 Markdown 이다: 글 덩어리는 그대로, 이미지는 `![설명](image:<id>)` 한 줄(앞뒤 빈 줄)로 바뀌어 body 로 나간다.
// 구조는 항상 "글 · 이미지 · 글 · 이미지 · 글"로 번갈아 놓여서, 이미지 앞뒤 어디에든 글을 쓸 수 있다.

type Block =
  | { key: string; kind: 'text'; text: string }
  | { key: string; kind: 'image'; image: WireCommunityImage; alt: string }

interface Caret { key: string; pos: number }

const MAX_IMAGES = 5

let keySeed = 0
const newKey = () => `b${++keySeed}`
const cleanAlt = (alt: string) => alt.replace(/[[\]\r\n]+/g, ' ').replace(/\s+/g, ' ').trim()

function serialize(blocks: Block[]): string {
  const parts: string[] = []
  for (const block of blocks) {
    if (block.kind === 'image') parts.push(`![${cleanAlt(block.alt)}](image:${block.image.id})`)
    else {
      const text = block.text.replace(/^\n+|\n+$/g, '')
      if (text.trim()) parts.push(text)
    }
  }
  return parts.join('\n\n')
}

const imagesOf = (blocks: Block[]) => blocks.flatMap(block => (block.kind === 'image' ? [block.image] : []))

const MARKER_LINE = /^[ \t]*!\[([^\]\n]*)\]\(image:([0-9a-f-]{8,})\)[ \t]*$/gim

/** 저장된 본문(Markdown)을 편집기 덩어리로 푼다. 마커의 이미지를 글 사진 목록에서 찾고, 마커 없이 붙어 있던 이미지는 맨 아래에 이어 붙인다(보이는 모습 그대로). */
function blocksFromBody(body: string, images: WireCommunityImage[]): Block[] {
  const byId = new Map(images.map(image => [image.id.toLowerCase(), image]))
  const used = new Set<string>()
  const known = body.replace(MARKER_LINE, (whole, _alt: string, id: string) => (byId.has(id.toLowerCase()) ? whole : ''))
  const pieces = known.split(MARKER_LINE)          // [글, 설명, id, 글, 설명, id, …, 글]
  const blocks: Block[] = []
  for (let i = 0; i < pieces.length; i += 3) {
    blocks.push({ key: newKey(), kind: 'text', text: (pieces[i] ?? '').replace(/^\n+|\n+$/g, '') })
    const id = pieces[i + 2]
    const image = id ? byId.get(id.toLowerCase()) : undefined
    if (image) { used.add(image.id.toLowerCase()); blocks.push({ key: newKey(), kind: 'image', image, alt: pieces[i + 1] ?? '' }) }
  }
  if (blocks[blocks.length - 1].kind === 'image') blocks.push({ key: newKey(), kind: 'text', text: '' })
  for (const image of images) {
    if (used.has(image.id.toLowerCase())) continue
    blocks.push({ key: newKey(), kind: 'image', image, alt: '' }, { key: newKey(), kind: 'text', text: '' })
  }
  return blocks
}

function AutoTextarea({ block, first, only, onText, onCaret, onPaste, onKeys, register }: {
  block: Extract<Block, { kind: 'text' }>; first: boolean; only: boolean
  onText: (key: string, text: string) => void
  onCaret: (key: string, event: SyntheticEvent<HTMLTextAreaElement>) => void
  onPaste: (key: string, event: ClipboardEvent<HTMLTextAreaElement>) => void
  onKeys: (key: string, event: KeyboardEvent<HTMLTextAreaElement>) => void
  register: (key: string, element: HTMLTextAreaElement | null) => void
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight + 2}px`
  }, [block.text])
  return (
    <textarea
      ref={element => { ref.current = element; register(block.key, element) }}
      data-block={block.key}
      id={first ? 'cm-write-body' : undefined}
      className={'cm-block-text' + (first ? ' first' : '')}
      rows={1}
      value={block.text}
      placeholder={only ? '질문이라면 사용 환경, 예산, 시도한 방법을 함께 적어주세요. 이미지는 여기에 바로 붙여넣거나 끌어다 놓을 수 있어요.' : first ? '' : '이어서 쓰기…'}
      onChange={event => onText(block.key, event.target.value)}
      onFocus={event => onCaret(block.key, event)}
      onSelect={event => onCaret(block.key, event)}
      onKeyUp={event => onCaret(block.key, event)}
      onClick={event => onCaret(block.key, event)}
      onPaste={event => onPaste(block.key, event)}
      onKeyDown={event => onKeys(block.key, event)}
    />
  )
}

export default function BodyEditor({ userName, initial, onChange }: {
  userName: string | null
  /** 글 수정 때 처음에 채울 본문과 그 글의 사진 */
  initial?: { body: string; images: WireCommunityImage[] }
  onChange: (body: string, images: WireCommunityImage[]) => void
}) {
  const { showToast } = useToast()
  const [blocks, setBlocks] = useState<Block[]>(() => (initial ? blocksFromBody(initial.body, initial.images) : [{ key: newKey(), kind: 'text', text: '' }]))
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const blocksRef = useRef(blocks)
  blocksRef.current = blocks
  const caret = useRef<Caret | null>(null)
  const fields = useRef(new Map<string, HTMLTextAreaElement>())
  const pendingFocus = useRef<{ key: string; pos: number } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const report = useRef(onChange)
  // 수정 화면에서 처음부터 글에 붙어 있던 이미지는 서버의 임시 이미지가 아니므로 지우기를 요청하지 않는다(저장할 때 글에서 빠진다).
  const attachedIds = useRef(new Set((initial?.images ?? []).map(image => image.id)))
  report.current = onChange

  useEffect(() => { report.current(serialize(blocks), imagesOf(blocks)) }, [blocks])

  // 글을 쓰다 취소하거나 화면을 떠나면 올려 둔 임시 이미지를 서버에서 지운다(서버는 글에 붙지 않은 이미지를 사용자당 10장까지만 받는다).
  // 게시하거나 임시 저장해서 이미 글에 붙은 이미지는 서버가 거절(409)하므로 그대로 남는다.
  useEffect(() => () => {
    for (const image of imagesOf(blocksRef.current)) if (!attachedIds.current.has(image.id)) communityApi.removeUpload(image.id).catch(() => undefined)
  }, [])

  // 이미지를 넣거나 지운 뒤에는 이어 쓸 글 칸으로 커서를 옮긴다.
  useLayoutEffect(() => {
    const target = pendingFocus.current
    if (!target) return
    pendingFocus.current = null
    const element = fields.current.get(target.key)
    if (element) { element.focus(); element.setSelectionRange(target.pos, target.pos) }
  }, [blocks])

  const register = useCallback((key: string, element: HTMLTextAreaElement | null) => {
    if (element) fields.current.set(key, element)
    else fields.current.delete(key)
  }, [])
  const trackCaret = useCallback((key: string, event: SyntheticEvent<HTMLTextAreaElement>) => {
    caret.current = { key, pos: event.currentTarget.selectionStart }
  }, [])
  const setText = useCallback((key: string, text: string) => {
    setBlocks(current => current.map(block => (block.key === key && block.kind === 'text' ? { ...block, text } : block)))
  }, [])

  // at 자리에 이미지 하나를 넣는다. 글 칸이면 커서에서 둘로 쪼개고, 이미지 칸이면 그 이미지 바로 뒤에 넣는다.
  const insertImage = (image: WireCommunityImage, at: Caret | null) => {
    const imageKey = newKey()
    const tailKey = newKey()
    const imageBlock: Block = { key: imageKey, kind: 'image', image, alt: '' }
    setBlocks(current => {
      const index = at ? current.findIndex(block => block.key === at.key) : -1
      const target = index >= 0 ? current[index] : null
      if (target && target.kind === 'text') {
        const pos = Math.min(at!.pos, target.text.length)
        const head = target.text.slice(0, pos).replace(/\n+$/, '')
        const rest = target.text.slice(pos).replace(/^\n+/, '')
        return [...current.slice(0, index), { ...target, text: head }, imageBlock, { key: tailKey, kind: 'text', text: rest }, ...current.slice(index + 1)]
      }
      if (target && target.kind === 'image') {
        return [...current.slice(0, index + 1), { key: newKey(), kind: 'text', text: '' }, imageBlock, { key: tailKey, kind: 'text', text: '' }, ...current.slice(index + 1)]
      }
      const last = current[current.length - 1]
      const base = last.kind === 'text' ? current : [...current, { key: newKey(), kind: 'text', text: '' } as Block]
      return [...base, imageBlock, { key: tailKey, kind: 'text', text: '' }]
    })
    caret.current = { key: tailKey, pos: 0 }
    pendingFocus.current = { key: tailKey, pos: 0 }
  }

  const addFiles = async (files: File[], at: Caret | null) => {
    const picked = files.filter(file => file.type.startsWith('image/'))
    if (picked.length === 0) return
    if (!userName) { showToast('이미지 첨부는 로그인 후 이용할 수 있어요.'); return }
    setUploading(true)
    try {
      let place = at
      for (const file of picked) {
        if (imagesOf(blocksRef.current).length >= MAX_IMAGES) { showToast('이미지는 최대 5장까지 첨부할 수 있습니다.'); break }
        const uploaded = await communityApi.uploadImage(file)
        insertImage(uploaded, place)
        place = caret.current
        await new Promise<void>(resolve => window.requestAnimationFrame(() => resolve()))   // 방금 넣은 칸이 그려진 뒤 다음 이미지를 넣는다
      }
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : '이미지를 올리지 못했습니다. 잠시 후 다시 시도해주세요.')
    } finally {
      setUploading(false)
    }
  }

  const filesOf = (data: DataTransfer | null) => Array.from(data?.files ?? []).filter(file => file.type.startsWith('image/'))
  const onPaste = (key: string, event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = filesOf(event.clipboardData)
    if (files.length === 0) return            // 글자 붙여넣기는 그대로 둔다
    event.preventDefault()
    void addFiles(files, { key, pos: event.currentTarget.selectionStart })
  }
  const dropTarget = (event: DragEvent<HTMLElement>): Caret | null => {
    const holder = (event.target as HTMLElement).closest<HTMLElement>('[data-block]')
    const key = holder?.getAttribute('data-block')
    if (!key) return caret.current
    const element = fields.current.get(key)
    return { key, pos: element ? element.selectionStart : 0 }
  }
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    setDragging(false)
    const files = filesOf(event.dataTransfer)
    if (files.length === 0) return
    event.preventDefault()
    void addFiles(files, dropTarget(event))
  }

  // 일반 글처럼 지운다: 이미지를 눌러 선택한 뒤 Backspace/Delete, 또는 이미지 바로 아래 글 칸 맨 앞에서 Backspace(위 칸 맨 끝에서 Delete).
  // 지우면 앞뒤 글이 이어 붙고, 커서는 이어진 자리에 놓인다.
  const removeImage = (key: string) => {
    const current = blocksRef.current
    const index = current.findIndex(block => block.key === key)
    if (index < 0) return
    const before = current[index - 1]
    const after = current[index + 1]
    // 아직 글에 붙지 않은 임시 이미지는 서버에서도 바로 지운다(서버는 글에 붙지 않은 이미지를 사용자당 10장까지만 받는다).
    // 임시 저장된 글에 붙은 이미지는 서버가 거절하는데(409), 그런 이미지는 저장할 때 글에서 빠지므로 무시한다.
    const removed = current[index]
    if (removed.kind === 'image' && !attachedIds.current.has(removed.image.id)) communityApi.removeUpload(removed.image.id).catch(() => undefined)
    if (before?.kind === 'text' && after?.kind === 'text') {
      const head = before.text.replace(/\n+$/, '')
      const joined = head + (head.trim() && after.text.trim() ? '\n\n' : '') + after.text.replace(/^\n+/, '')
      pendingFocus.current = { key: before.key, pos: head.length + (head.trim() && after.text.trim() ? 2 : 0) }
      setBlocks([...current.slice(0, index - 1), { ...before, text: joined }, ...current.slice(index + 2)])
      return
    }
    setBlocks(current.filter(block => block.key !== key))
  }
  const onKeys = (key: string, event: KeyboardEvent<HTMLTextAreaElement>) => {
    const field = event.currentTarget
    if (field.selectionStart !== field.selectionEnd) return
    const list = blocksRef.current
    const index = list.findIndex(block => block.key === key)
    if (event.key === 'Backspace' && field.selectionStart === 0 && list[index - 1]?.kind === 'image') {
      event.preventDefault()
      removeImage(list[index - 1].key)
    } else if (event.key === 'Delete' && field.selectionStart === field.value.length && list[index + 1]?.kind === 'image') {
      event.preventDefault()
      removeImage(list[index + 1].key)
    }
  }
  const onImageKey = (key: string, event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return      // 설명 입력칸에서 지우는 글자는 건드리지 않는다
    if (event.key === 'Backspace' || event.key === 'Delete') { event.preventDefault(); removeImage(key) }
  }
  const setAlt = (key: string, alt: string) => setBlocks(current => current.map(block => (block.key === key && block.kind === 'image' ? { ...block, alt } : block)))

  const count = imagesOf(blocks).length
  const only = blocks.length === 1

  return (
    <div className="cm-editor">
      <div className="cm-editor-bar">
        <button type="button" className="cm-photo-btn" disabled={uploading || count >= MAX_IMAGES} onClick={() => fileRef.current?.click()}>🖼 사진 넣기</button>
        <input ref={fileRef} type="file" hidden accept="image/jpeg,image/png,image/webp" multiple onChange={event => { void addFiles(Array.from(event.target.files ?? []), caret.current); event.target.value = '' }} />
        <span className="cm-editor-count">{uploading ? '이미지를 올리는 중…' : `이미지 ${count} / ${MAX_IMAGES}`}</span>
      </div>
      <div
        className={'cm-editor-body' + (dragging ? ' cm-drop' : '')}
        onDragOver={event => { if (Array.from(event.dataTransfer.types).includes('Files')) { event.preventDefault(); setDragging(true) } }}
        onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
        onDrop={onDrop}
      >
        {blocks.map((block, index) => block.kind === 'text'
          ? <AutoTextarea key={block.key} block={block} first={index === 0} only={only} onText={setText} onCaret={trackCaret} onPaste={onPaste} onKeys={onKeys} register={register} />
          : (
            <figure className="cm-block-image" key={block.key} data-block={block.key} tabIndex={0} onKeyDown={event => onImageKey(block.key, event)} aria-label="첨부 이미지 — 선택한 뒤 Backspace 또는 Delete 키로 지울 수 있어요">
              <img src={block.image.url} width={block.image.width} height={block.image.height} alt={block.alt || '첨부 이미지'} draggable={false} />
              <figcaption>
                <input value={block.alt} maxLength={80} onChange={event => setAlt(block.key, event.target.value)} placeholder="이미지 설명 (선택 · 무엇이 보이는지 한 줄)" aria-label="이미지 설명" />
              </figcaption>
            </figure>
          ))}
      </div>
      <p className="cm-product-help">이미지는 글 사이에 <b>붙여넣기(Ctrl+V)</b>하거나 끌어다 놓으면 커서 자리에 바로 보여요 · 지우려면 이미지를 눌러 선택한 뒤 <b>Backspace</b> · 최대 5장, JPEG·PNG·WebP, 장당 5MB · 첫 이미지가 대표예요.</p>    </div>
  )
}
