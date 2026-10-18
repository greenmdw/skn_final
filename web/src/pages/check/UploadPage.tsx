import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorMessage, type QuoteCapabilities, type QuoteConditions } from '../../api'
import { checkV2 } from '../../api/checkV2'
import QuoteUploader, { type UploadFile } from '../../components/check/QuoteUploader'
import { useToast } from '../../state/ToastContext'
import { readAsText } from '../../utils/checkReview'
import { registerCheckSession } from '../../utils/checkSessions'
import CheckLayout, { CHECK2 } from './CheckLayout'

const DEFAULT_TYPES = ['image/png', 'image/jpeg', 'image/webp']

/** ① 올리기 — 사진·텍스트, 조건, 질문만 둔다. 채팅과 사진 관계 질문은 없다(관계는 읽은 뒤 ② 에서 알려 준다). */
export default function UploadPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [search] = useSearchParams()
  const { showToast } = useToast()
  const [capabilities, setCapabilities] = useState<QuoteCapabilities | null>(null)
  const [tab, setTab] = useState<'image' | 'text'>('image')
  const [files, setFiles] = useState<UploadFile[]>([])
  const filesRef = useRef<UploadFile[]>([])
  filesRef.current = files
  const seq = useRef(0)
  const [text, setText] = useState('')
  const [question, setQuestion] = useState('')
  const [chips, setChips] = useState<string[]>([])
  const [conditions, setConditions] = useState<QuoteConditions>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api.quoteDrafts.capabilities().then(result => { if (alive) setCapabilities(result) }).catch(() => { /* 기본 한도로 안내한다 */ })
    return () => { alive = false }
  }, [])
  useEffect(() => () => { filesRef.current.forEach(entry => URL.revokeObjectURL(entry.url)) }, [])
  // 마이페이지의 "받은 견적 점검에 적용"으로 들어오면 텍스트 견적 탭에 내 현재 PC 구성을 미리 채운다(한 번만).
  useEffect(() => {
    const preset = location.state as { tab?: unknown; text?: unknown } | null
    if (preset?.tab !== 'text' || typeof preset.text !== 'string' || !preset.text) return
    setTab('text')
    setText(current => (current.trim() ? current : preset.text as string))
    navigate(location.pathname, { replace: true, state: null })
  }, [location, navigate])

  function addFiles(incoming: File[]) {
    const images = incoming.filter(file => file.type.startsWith('image/'))
    if (images.length === 0) { showToast('이미지 파일만 올릴 수 있어요.'); return }
    const maxFiles = capabilities?.maxFiles ?? 3
    const maxBytes = capabilities?.maxFileBytes ?? 10 * 1024 * 1024
    const types = capabilities?.supportedTypes ?? DEFAULT_TYPES
    const next = [...files]
    let skipped = ''
    for (const file of images) {
      if (next.length >= maxFiles) { skipped = `최대 ${maxFiles}장까지 올릴 수 있어요.`; break }
      if (!types.includes(file.type)) { skipped = 'PNG·JPEG·WebP 이미지만 올릴 수 있어요.'; continue }
      if (file.size > maxBytes) { skipped = `${file.name}은(는) 장당 ${Math.round(maxBytes / 1024 / 1024)}MB 이하여야 해요.`; continue }
      if (next.some(entry => entry.file.name === file.name && entry.file.size === file.size)) { skipped = '같은 파일은 한 번만 올릴 수 있어요.'; continue }
      next.push({ id: `file-${++seq.current}`, file, url: URL.createObjectURL(file) })
    }
    setFiles(next)
    if (skipped) showToast(skipped)
  }

  function removeFile(id: string) {
    setFiles(previous => {
      const target = previous.find(entry => entry.id === id)
      if (target) URL.revokeObjectURL(target.url)
      return previous.filter(entry => entry.id !== id)
    })
  }

  async function loadTextFile(file: File) {
    try { setText(await readAsText(file)); setError('') } catch (caught) { setError(errorMessage(caught, '파일을 읽지 못했습니다.')) }
  }

  function toggleChip(label: string, prompt: string) {
    setChips(previous => {
      if (previous.includes(label)) {
        setQuestion(current => current.replace(prompt, '').replace(/\s{2,}/g, ' ').trim())
        return previous.filter(entry => entry !== label)
      }
      setQuestion(current => (current.trim() ? `${current.trim()} ${prompt}` : prompt))
      return [...previous, label]
    })
  }

  async function recognize() {
    setError('')
    const useImages = tab === 'image'
    if (useImages && files.length === 0) { setError('견적 이미지를 먼저 추가해주세요.'); return }
    if (!useImages && !text.trim()) { setError('견적 텍스트를 입력해주세요.'); return }
    // 용도를 알아야 바꿀 부품을 추천할 수 있다 — 사진을 읽는 비용이 들기 전에 막는다(게임이면 해상도도)
    if (!conditions.purpose) { setError('평가 조건에서 용도를 골라 주세요. 용도를 알아야 바꿀 부품을 추천할 수 있어요.'); return }
    if (conditions.purpose === 'game' && !conditions.resolution) { setError('게임 용도는 해상도도 골라 주세요.'); return }
    const form = new FormData()
    if (useImages) files.forEach(entry => form.append('images', entry.file, entry.file.name))
    else form.append('text', text.trim())
    if (question.trim()) form.append('question', question.trim())
    const body: Record<string, unknown> = {
      purpose: conditions.purpose, resolution: conditions.resolution, priority: conditions.priority,
      budget_max: conditions.budgetMax,
    }
    form.append('conditions', JSON.stringify(Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined))))
    setBusy(true)
    try {
      const draft = await checkV2.createDraft(form)
      registerCheckSession(draft.draft_id)
      navigate(`${CHECK2}/${draft.draft_id}/parts`)
    } catch (caught) {
      setError(errorMessage(caught, '견적을 인식하지 못했습니다.'))
    } finally { setBusy(false) }
  }

  const legacyDraft = search.get('draft')           // 예전 주소(/check?draft=…)로 들어와도 지난 점검을 연다
  if (legacyDraft) return <Navigate to={`/check/${legacyDraft}`} replace />

  return (
    <CheckLayout current="upload" reachable={[]} chat={false}>
      <header className="c2-head">
        <h1>받은 견적 점검</h1>
        <p>견적 사진이나 텍스트를 올리면 부품을 읽고, 호환·용도 적합을 점검하고, 바꿀 부품을 추천해 드려요. 채팅은 견적을 읽은 뒤부터 열려요.</p>
      </header>
      {error && <p className="c2-error" role="alert">{error}</p>}
      <QuoteUploader
        capabilities={capabilities} tab={tab} onTab={setTab} files={files} onAddFiles={addFiles} onRemoveFile={removeFile}
        text={text} onText={setText} onTextFile={file => void loadTextFile(file)} question={question} onQuestion={setQuestion}
        activeChips={chips} onToggleChip={toggleChip} conditions={conditions} onConditions={setConditions} busy={busy} onRecognize={() => void recognize()}
      />
      <section className="c2-card">
        <p className="c2-note">사진을 여러 장 올리면 한 견적을 나눠 찍은 것인지 서로 다른 견적인지 읽은 뒤에 알려 드려요.</p>
      </section>
    </CheckLayout>
  )
}
