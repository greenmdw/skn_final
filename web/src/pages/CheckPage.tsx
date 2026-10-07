import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import PlannerShell from '../components/PlannerShell'
import AnalysisView, { type LiveLookupState } from '../components/check/AnalysisView'
import CheckChat, { type ChatEntry } from '../components/check/CheckChat'
import ItemEditDialog from '../components/check/ItemEditDialog'
import UpgradeDialog from '../components/check/UpgradeDialog'
import PartCompareDialog, { type CompareChoice } from '../components/check/PartCompareDialog'
import QuoteUploader, { type UploadFile } from '../components/check/QuoteUploader'
import RecognitionResult, { type ResultFilter } from '../components/check/RecognitionResult'
import SavedComparisonPanel, { type ComparisonAnswer } from '../components/check/SavedComparisonPanel'
import SavedQuotePicker from '../components/check/SavedQuotePicker'
import {
  api, ApiError, errorMessage,
  type QuoteCapabilities, type QuoteConditions, type QuoteDraft, type QuoteDraftAnalysis, type QuoteDraftChatMessage, type QuoteDraftComparison,
  type QuoteDraftItem, type QuoteRecommendedOption, type QuoteReplacementPreview, type QuoteSavedComparison,
} from '../api'
import { usePlan } from '../state/PlanContext'
import { useSetups } from '../state/SetupsContext'
import { useToast } from '../state/ToastContext'
import type { CheckDraft, CurrentPlan, SavedSetup } from '../state/types'
import {
  REVIEW_PART_KEYS, effectiveSelection, newClientId, pendingToEdits, questionTags, readAsText, scrollMainTo, type PendingEdit,
} from '../utils/checkReview'
import { checkSessionInfo, registerCheckSession, rememberCheckComparison } from '../utils/checkSessions'
import '../styles/check.css'

const INTRO: ChatEntry = {
  id: 'intro', kind: 'bot',
  text: '견적서가 여러 장이어도 괜찮아요. 사진을 한 번에 올리면 중복 부품은 합치고, 제품명과 가격은 나눠서 정리할게요.',
}
const DEFAULT_TYPES = ['image/png', 'image/jpeg', 'image/webp']

type BusyKind = 'recognize' | 'save' | 'analyze' | 'cart' | 'saved' | 'apply' | null

function answersFromHistory(messages: QuoteDraftChatMessage[], comparisonId: string): ComparisonAnswer[] {
  const answers: ComparisonAnswer[] = []
  let question = ''
  for (const message of messages) {
    if (message.comparisonId !== comparisonId) continue
    if (message.role === 'user') { question = message.text; continue }
    if (message.role === 'assistant' && message.displayTarget === 'saved_comparison_explanation' && message.answerId && !message.duplicateOf) {
      answers.push({ id: message.answerId, question: question || '질문', reply: message.text, visuals: message.visuals, guideRefs: message.guideRefs, via: message.via })
    }
  }
  return answers
}

function conditionsFromDraft(raw: Record<string, unknown>): QuoteConditions {
  const next: QuoteConditions = {}
  if (typeof raw.purpose === 'string') next.purpose = raw.purpose as QuoteConditions['purpose']
  if (typeof raw.resolution === 'string') next.resolution = raw.resolution as QuoteConditions['resolution']
  if (typeof raw.priority === 'string') next.priority = raw.priority as QuoteConditions['priority']
  if (Array.isArray(raw.games)) next.games = raw.games.map(String)
  if (typeof raw.budget_max === 'number') next.budgetMax = raw.budget_max
  return next
}

export default function CheckPage() {
  const { showToast } = useToast()
  const { loadCheckedQuote, startUpgradeMode } = usePlan()
  const { savedSetups, loading: savedSetupsLoading, storageError: savedSetupsError } = useSetups()
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const analysisRef = useRef<HTMLElement | null>(null)
  const seq = useRef(0)
  const nextId = (prefix: string) => `${prefix}-${++seq.current}`

  // 서버 한도
  const [capabilities, setCapabilities] = useState<QuoteCapabilities | null>(null)
  // 입력
  const [tab, setTab] = useState<'image' | 'text'>('image')
  const [files, setFiles] = useState<UploadFile[]>([])
  const filesRef = useRef<UploadFile[]>([])
  filesRef.current = files
  const [text, setText] = useState('')
  const [question, setQuestion] = useState('')
  const [activeChips, setActiveChips] = useState<string[]>([])
  const [conditions, setConditions] = useState<QuoteConditions>({})
  // 초안·검토
  const [draft, setDraft] = useState<QuoteDraft | null>(null)
  const [selection, setSelection] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<Record<string, PendingEdit>>({})
  const [filter, setFilter] = useState<ResultFilter>('all')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [comparedOnce, setComparedOnce] = useState(false)
  // 부품 비교·교체 목록
  const [compareCategory, setCompareCategory] = useState<string | null>(null)
  const [compareData, setCompareData] = useState<QuoteDraftComparison | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareError, setCompareError] = useState('')
  const [choice, setChoice] = useState<CompareChoice | null>(null)
  const [cart, setCart] = useState<Record<string, QuoteRecommendedOption>>({})
  const [cartPreview, setCartPreview] = useState<QuoteReplacementPreview | null>(null)
  const [cartPreviewBusy, setCartPreviewBusy] = useState(false)
  // 분석
  const [analysis, setAnalysis] = useState<QuoteDraftAnalysis | null>(null)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [liveLookup, setLiveLookup] = useState<Record<string, LiveLookupState>>({})
  // 저장 견적 비교
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerError, setPickerError] = useState('')
  const [pickedSetupId, setPickedSetupId] = useState<string | null>(null)
  const [comparison, setComparison] = useState<QuoteSavedComparison | null>(null)
  const [savedVisible, setSavedVisible] = useState(false)
  const [differenceOnly, setDifferenceOnly] = useState(false)
  const [answers, setAnswers] = useState<ComparisonAnswer[]>([])
  const answersRef = useRef<ComparisonAnswer[]>([])
  answersRef.current = answers
  const [openAnswerIds, setOpenAnswerIds] = useState<Set<string>>(new Set())
  const [pulse, setPulse] = useState(0)
  // 대화
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([INTRO])
  const [chatBusy, setChatBusy] = useState(false)
  // 공통
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [upgradeBusy, setUpgradeBusy] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [busy, setBusy] = useState<BusyKind>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api.quoteDrafts.capabilities().then(result => { if (alive) setCapabilities(result) }).catch(() => { /* 서버 응답 전에는 기본 한도로 안내한다 */ })
    return () => { alive = false }
  }, [])

  useEffect(() => () => { filesRef.current.forEach(entry => URL.revokeObjectURL(entry.url)) }, [])

  const scrollTo = useCallback((id: string) => {
    // 상태 반영 직후에는 대상이 아직 그려지지 않았을 수 있어 잠시 기다린다
    let tries = 0
    const attempt = () => {
      if (document.getElementById(id) || tries >= 20) { scrollMainTo(id); return }
      tries += 1
      window.setTimeout(attempt, 50)
    }
    window.setTimeout(attempt, 0)
  }, [])

  const savedSetupPicked = useMemo(() => savedSetups.find(setup => setup.id === pickedSetupId) ?? null, [savedSetups, pickedSetupId])
  const workflowStep = analysis && showAnalysis ? 4 : comparedOnce ? 3 : draft ? 2 : 1

  // ── 입력 ─────────────────────────────────────────────────────────────────
  function addFiles(incoming: File[]) {
    const images = incoming.filter(file => file.type.startsWith('image/'))
    if (images.length === 0) { showToast('이미지 파일만 올릴 수 있어요.'); return }
    const maxFiles = capabilities?.maxFiles ?? 3
    const maxBytes = capabilities?.maxFileBytes ?? 10 * 1024 * 1024
    const maxTotal = capabilities?.maxTotalBytes ?? 30 * 1024 * 1024
    const types = capabilities?.supportedTypes ?? DEFAULT_TYPES
    const next = [...files]
    let added = 0
    let skipped = ''
    for (const file of images) {
      if (next.length >= maxFiles) { skipped = `최대 ${maxFiles}장까지 올릴 수 있어요.`; break }
      if (!types.includes(file.type)) { skipped = 'PNG·JPEG·WebP 이미지만 올릴 수 있어요.'; continue }
      if (file.size > maxBytes) { skipped = `${file.name}은(는) 장당 ${Math.round(maxBytes / 1024 / 1024)}MB 이하여야 해요.`; continue }
      if (next.reduce((sum, entry) => sum + entry.file.size, 0) + file.size > maxTotal) { skipped = `전체 용량이 ${Math.round(maxTotal / 1024 / 1024)}MB를 넘을 수 없어요.`; continue }
      if (next.some(entry => entry.file.name === file.name && entry.file.size === file.size && entry.file.lastModified === file.lastModified)) { skipped = '같은 파일은 한 번만 올릴 수 있어요.'; continue }
      next.push({ id: nextId('file'), file, url: URL.createObjectURL(file) })
      added += 1
    }
    setFiles(next)
    showToast(added ? `${added}장 추가했어요. 총 ${next.length}장을 함께 인식합니다.${skipped ? ` ${skipped}` : ''}` : (skipped || '추가할 수 있는 새 이미지가 없어요.'))
  }

  function removeFile(id: string) {
    setFiles(previous => {
      const target = previous.find(entry => entry.id === id)
      if (target) URL.revokeObjectURL(target.url)
      return previous.filter(entry => entry.id !== id)
    })
  }

  async function loadTextFile(file: File) {
    const name = file.name.toLowerCase()
    if (!(file.type.startsWith('text/') || name.endsWith('.txt') || name.endsWith('.csv'))) { setError('텍스트 파일은 TXT 또는 CSV 형식만 올릴 수 있습니다.'); return }
    try {
      const content = await readAsText(file)
      const max = capabilities?.textMaxChars ?? 20_000
      if (content.length > max) { setError(`텍스트는 ${max.toLocaleString('ko-KR')}자 이하로 줄여주세요.`); return }
      setError('')
      setText(content)
    } catch (caught) { setError(errorMessage(caught, '파일을 읽지 못했습니다.')) }
  }

  function toggleChip(label: string, prompt: string) {
    setActiveChips(previous => {
      if (previous.includes(label)) {
        setQuestion(current => current.replace(prompt, '').replace(/\s{2,}/g, ' ').trim())
        return previous.filter(entry => entry !== label)
      }
      setQuestion(current => (current.trim() ? `${current.trim()} ${prompt}` : prompt))
      return [...previous, label]
    })
  }

  // ── 인식 ─────────────────────────────────────────────────────────────────
  function resetForDraft(next: QuoteDraft) {
    setDraft(next)
    setSelection(effectiveSelection(next, {}))
    setPending({})
    setFilter('all')
    setAnalysis(null)
    setShowAnalysis(false)
    setComparedOnce(false)
    setCart({}); setCartPreview(null)
    setLiveLookup({})
    setComparison(null); setSavedVisible(false); setAnswers([]); setOpenAnswerIds(new Set())
    setChatEntries([INTRO])
  }

  async function recognize() {
    setError('')
    const useImages = tab === 'image'
    if (useImages && files.length === 0) { setError('견적 이미지를 먼저 추가해주세요.'); return }
    if (!useImages && !text.trim()) { setError('견적 텍스트를 입력해주세요.'); return }
    const hasConditions = Object.values(conditions).some(value => value !== undefined)
    setBusy('recognize')
    try {
      const next = await api.quoteDrafts.create({
        images: useImages ? files.map(entry => entry.file) : [],
        text: useImages ? undefined : text,
        question,
        conditions: hasConditions ? conditions : undefined,
      })
      resetForDraft(next)
      registerCheckSession(next.draftId)
      const sourceCount = next.sources.filter(source => source.type === 'image' || source.type === 'text').length
      showToast(`${sourceCount}개 출처에서 서로 다른 제품 ${next.items.length}개를 부품 종류별로 정리했어요.`)
      scrollTo('ck-results')
    } catch (caught) {
      setError(errorMessage(caught, '견적을 인식하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  // ── 지난 점검 다시 열기 ──────────────────────────────────────────────────
  // 서버에는 초안(제품·가격·선택)과 분석 결과가 남아 있다. 올린 이미지 원본은 저장하지 않아 다시 볼 수 없다.
  async function restore(draftId: string) {
    setRestoring(true); setError('')
    try {
      const loaded = await api.quoteDrafts.get(draftId)
      resetForDraft(loaded)
      registerCheckSession(draftId)
      setQuestion(loaded.question ?? '')
      setConditions(conditionsFromDraft(loaded.conditions))
      let analyzed = true
      try { await api.checks.getReview(draftId) } catch { analyzed = false }
      if (analyzed) {
        await runAnalysis(loaded)
        const info = checkSessionInfo(draftId)
        if (info?.comparisonId) {
          try {
            const [saved, history] = await Promise.all([api.quoteDrafts.getSavedComparison(draftId, info.comparisonId), api.quoteDrafts.chatHistory(draftId)])
            const restored = answersFromHistory(history, saved.comparisonId)
            setComparison(saved); setSavedVisible(true)
            setAnswers(restored); setOpenAnswerIds(new Set(restored.length ? [restored[restored.length - 1].id] : []))
          } catch { /* 비교표를 못 읽어도 분석은 보여 준다 */ }
        }
      } else {
        scrollTo('ck-results')
      }
      showToast('지난 견적 점검을 불러왔어요. 올린 이미지는 서버에 저장하지 않아 다시 볼 수 없어요.')
    } catch (caught) {
      setError(errorMessage(caught, '지난 견적 점검을 불러오지 못했습니다.'))
    } finally { setRestoring(false) }
  }

  const restoreId = search.get('draft')
  const restoringRef = useRef<string | null>(null)
  useEffect(() => {
    if (!restoreId || restoringRef.current === restoreId) return
    restoringRef.current = restoreId
    setSearch({}, { replace: true })
    void restore(restoreId).finally(() => { restoringRef.current = null })
  }, [restoreId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 수정·저장 ────────────────────────────────────────────────────────────
  /** 수정 대기 항목과 분석 기준 선택을 서버에 한 번에 저장한다. 실패하면 null */
  async function persist(): Promise<QuoteDraft | null> {
    if (!draft) return null
    const edits = pendingToEdits(pending)
    const deleted = new Set(Object.entries(pending).filter(([, edit]) => edit.delete).map(([id]) => id))
    const chosen: Record<string, string> = {}
    for (const [category, itemId] of Object.entries(selection)) if (!deleted.has(itemId)) chosen[category] = itemId
    const selectionChanged = Object.entries(chosen).some(([category, itemId]) => draft.selectedItemByCategory[category] !== itemId)
    if (edits.length === 0 && !selectionChanged) return draft
    try {
      const next = await api.quoteDrafts.patchItems(draft.draftId, draft.version, edits, chosen)
      setDraft(next)
      setPending({})
      setSelection(effectiveSelection(next, {}))
      return next
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'STALE_REVIEW_VERSION') {
        try {
          const latest = await api.quoteDrafts.get(draft.draftId)
          setDraft(latest)
          setSelection(effectiveSelection(latest, selection))
        } catch { /* 최신 상태를 읽지 못해도 안내는 보여준다 */ }
        setError('초안이 다른 곳에서 바뀌어 최신 상태를 다시 불러왔어요. 수정 내용을 확인한 뒤 다시 시도해주세요.')
        return null
      }
      setError(errorMessage(caught, '수정 내용을 저장하지 못했습니다.'))
      return null
    }
  }

  function saveEdit(edit: PendingEdit) {
    if (!editingId || !draft) return
    const item = draft.items.find(entry => entry.id === editingId)
    setPending(previous => ({ ...previous, [editingId]: edit }))
    if (edit.delete && item) {
      setSelection(previous => {
        if (previous[item.category] !== item.id) return previous
        const rest = draft.items.find(entry => entry.category === item.category && entry.id !== item.id && !pending[entry.id]?.delete)
        const next = { ...previous }
        if (rest) next[item.category] = rest.id
        else delete next[item.category]
        return next
      })
    }
    setEditingId(null)
    showToast(edit.delete ? '이 항목을 삭제 목록에 담았어요. 다시 분석할 때 반영돼요.' : '수정을 목록에 담았어요. 여러 항목을 마친 뒤 한 번에 분석해요.')
  }

  async function reanalyzeEdits() {
    if (!draft) return
    const count = Object.keys(pending).length
    setBusy('save'); setError('')
    try {
      const saved = await persist()
      if (!saved) return
      showToast(`${count}건의 수정을 한 번에 반영했어요.`)
      if (showAnalysis) await runAnalysis(saved)
    } finally { setBusy(null) }
  }

  // ── 분석 ─────────────────────────────────────────────────────────────────
  async function runAnalysis(target: QuoteDraft) {
    const result = await api.quoteDrafts.analyze(target.draftId)
    setAnalysis(result)
    setShowAnalysis(true)
    setComparison(null); setSavedVisible(false); setAnswers([]); setOpenAnswerIds(new Set())
    const asked = question.trim() && question.trim() !== (target.question ?? '').trim() ? question.trim() : null
    let history: QuoteDraftChatMessage[] = []
    try { history = await api.quoteDrafts.chatHistory(result.listId) } catch { /* 이력을 못 읽어도 분석 결과는 보여준다 */ }
    const general: ChatEntry[] = history
      .filter(message => !message.comparisonId && message.role !== 'system')
      .map(message => ({ id: `h-${message.id}`, kind: message.role === 'user' ? 'user' : 'bot', text: message.text } as ChatEntry))
    setChatEntries([
      INTRO,
      { id: 'request', kind: 'request', question: target.question?.trim() || question.trim() || '이 견적을 전체적으로 평가해줘.', tags: questionTags(`${target.question ?? ''} ${question}`, activeChips) },
      { id: 'notice', kind: 'notice', text: '선택한 구성과 입력하신 기준으로 분석했어요. 결과를 보면서 추가로 궁금한 점을 물어보세요.' },
      ...general,
    ])
    scrollTo('ck-analysis')
    if (asked) void sendChat(asked, result)
  }

  async function analyze() {
    if (!draft) return
    setBusy('analyze'); setError('')
    try {
      const saved = await persist()
      if (!saved) return
      await runAnalysis(saved)
      showToast('견적 분석이 완료됐습니다.')
    } catch (caught) {
      setError(errorMessage(caught, '견적을 분석하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  function backToResults() {
    setShowAnalysis(false)
    scrollTo('ck-results')
  }

  async function runLiveLookup(item: QuoteDraftItem) {
    if (!draft) return
    setLiveLookup(previous => ({ ...previous, [item.id]: { status: 'loading' } }))
    try {
      const result = await api.quoteDrafts.liveLookupItem(draft.draftId, item.id)
      setLiveLookup(previous => ({ ...previous, [item.id]: { status: 'done', result } }))
      if (result.relevant && Object.values(result.supportedFields).some(value => value != null)) {
        setDraft(previous => previous ? { ...previous, items: previous.items.map(entry => entry.id === item.id ? { ...entry, liveValue: true } : entry) } : previous)
      }
    } catch (caught) {
      setLiveLookup(previous => ({ ...previous, [item.id]: { status: 'done', error: errorMessage(caught, '실시간 검색에 실패했습니다.') } }))
    }
  }

  // ── 부품 비교·교체 ───────────────────────────────────────────────────────
  async function openCompare(category: string) {
    if (!draft) return
    setCompareCategory(category); setCompareData(null); setCompareError(''); setChoice(null); setCompareLoading(true)
    setComparedOnce(true)
    try {
      const saved = await persist()
      if (!saved) { setCompareCategory(null); return }
      const baseline = saved.selectedItemByCategory[category] ?? effectiveSelection(saved, {})[category]
      const data = await api.quoteDrafts.compareCategory(saved.draftId, category, baseline)
      setCompareData(data)
      setChoice({ kind: 'recognized', itemId: data.baselineItemId })
    } catch (caught) {
      setCompareError(errorMessage(caught, '같은 부품군 후보를 불러오지 못했습니다.'))
    } finally { setCompareLoading(false) }
  }

  function closeCompare() {
    setCompareCategory(null); setCompareData(null); setChoice(null); setCompareError('')
  }

  function applyChoice() {
    if (!compareData || !choice || !compareCategory) return
    if (choice.kind === 'recognized') {
      const picked = choice.itemId
      setSelection(previous => ({ ...previous, [compareCategory]: picked }))
      const item = draft?.items.find(entry => entry.id === picked)
      showToast(`${compareCategory} 분석 기준을 “${item?.name ?? '선택한 제품'}”로 선택했어요.`)
    } else {
      const option = compareData.recommended.find(entry => entry.productId === choice.productId)
      if (option) {
        setCart(previous => ({ ...previous, [compareCategory]: option }))
        showToast(`${compareCategory} 후보를 교체 목록에 담았어요.`)
      }
    }
    closeCompare()
  }

  useEffect(() => {
    const entries = Object.entries(cart)
    if (!draft || entries.length === 0) { setCartPreview(null); return }
    let cancelled = false
    setCartPreviewBusy(true)
    api.quoteDrafts.previewReplacements(draft.draftId, entries.map(([category, option]) => ({ category, candidateProductId: option.productId })))
      .then(result => { if (!cancelled) setCartPreview(result) })
      .catch(caught => { if (!cancelled) { setCartPreview(null); setError(errorMessage(caught, '교체 영향을 계산하지 못했습니다.')) } })
      .finally(() => { if (!cancelled) setCartPreviewBusy(false) })
    return () => { cancelled = true }
  }, [cart, draft?.draftId, draft?.version]) // eslint-disable-line react-hooks/exhaustive-deps

  async function applyCart() {
    if (!draft) return
    const entries = Object.entries(cart)
    if (entries.length === 0) return
    setBusy('cart'); setError('')
    try {
      const saved = await persist()
      if (!saved) return
      const next = await api.quoteDrafts.applyReplacements(saved.draftId, saved.version, entries.map(([category, option]) => ({ category, candidateProductId: option.productId })))
      setDraft(next)
      setSelection(effectiveSelection(next, {}))
      setCart({}); setCartPreview(null)
      showToast(`${entries.length}개 부품을 한 번에 바꾸고 합계를 다시 계산했어요.`)
      if (showAnalysis) await runAnalysis(next)
    } catch (caught) {
      setError(errorMessage(caught, '교체 후보를 반영하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  // ── 저장 견적 비교 ───────────────────────────────────────────────────────
  async function confirmSavedComparison() {
    if (!analysis || !savedSetupPicked) return
    setBusy('saved'); setPickerError('')
    try {
      const result = await api.quoteDrafts.compareSaved(analysis.listId, savedSetupPicked.id, savedSetupPicked.revisionNo)
      let history: QuoteDraftChatMessage[] = []
      try { history = await api.quoteDrafts.chatHistory(analysis.listId) } catch { /* 이력은 없어도 비교는 보여준다 */ }
      const restored = answersFromHistory(history, result.comparisonId)
      rememberCheckComparison(analysis.listId, result.comparisonId)
      setComparison(result); setSavedVisible(true); setDifferenceOnly(false)
      setAnswers(restored); setOpenAnswerIds(new Set(restored.length ? [restored[restored.length - 1].id] : []))
      setPickerOpen(false)
      scrollTo('ck-saved-comparison')
    } catch (caught) {
      setPickerError(errorMessage(caught, '저장 견적을 비교하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  function toggleAnswer(id: string, open: boolean) {
    setOpenAnswerIds(previous => {
      const next = new Set(previous)
      if (open) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function showAnswer(id: string) {
    setSavedVisible(true)
    setOpenAnswerIds(previous => new Set(previous).add(id))
    window.setTimeout(() => scrollMainTo(`ck-answer-${id}`, 'center'), 60)
  }

  // ── 대화 ─────────────────────────────────────────────────────────────────
  async function sendChat(textValue: string, target: QuoteDraftAnalysis | null = analysis) {
    if (!target) {
      setQuestion(previous => (previous.trim() ? `${previous.trim()} ${textValue}` : textValue))
      setChatEntries(previous => [...previous, { id: nextId('u'), kind: 'user', text: textValue }])
      showToast('추가 질문을 분석 기준에 반영했어요.')
      return
    }
    const clientId = newClientId()
    const comparisonId = target === analysis ? comparison?.comparisonId : undefined
    const placeholderId = `pending-${clientId}`
    setChatEntries(previous => [...previous, { id: `u-${clientId}`, kind: 'user', text: textValue }])
    if (comparisonId) {
      setAnswers(previous => [...previous, { id: placeholderId, question: textValue, reply: '두 견적의 부품과 가격 차이를 질문에 맞춰 정리하고 있어요.', visuals: [], guideRefs: [], loading: true }])
      setOpenAnswerIds(previous => new Set(previous).add(placeholderId))
    }
    setChatBusy(true)
    try {
      const reply = await api.quoteDrafts.sendChat(target.listId, textValue, { clientMessageId: clientId, comparisonId })
      const forComparison = Boolean(comparisonId) && reply.displayTarget === 'saved_comparison_explanation' && Boolean(reply.answerId)
      if (forComparison && reply.answerId) {
        const originalId = reply.duplicateOf && answersRef.current.some(answer => answer.id === reply.duplicateOf) ? reply.duplicateOf : null
        if (originalId) {
          setAnswers(previous => previous.filter(answer => answer.id !== placeholderId))
          setChatEntries(previous => [...previous, { id: `r-${clientId}`, kind: 'reply', answerId: originalId, summary: reply.reply, reused: true }])
          showAnswer(originalId)
          showToast('이전에 작성한 답변을 보여드렸어요.')
        } else {
          const answerId = reply.answerId
          setAnswers(previous => previous.map(answer => (answer.id === placeholderId
            ? { id: answerId, question: textValue, reply: reply.reply, visuals: reply.visuals, guideRefs: reply.guideRefs, via: reply.via }
            : answer)))
          setOpenAnswerIds(previous => { const next = new Set(previous); next.delete(placeholderId); next.add(answerId); return next })
          setChatEntries(previous => [...previous, { id: `r-${clientId}`, kind: 'reply', answerId, summary: reply.reply, reused: false }])
          setPulse(value => value + 1)
          showAnswer(answerId)
          showToast('질문 답변을 두 견적 차이 해설에 표시했어요.')
        }
      } else {
        if (comparisonId) setAnswers(previous => previous.filter(answer => answer.id !== placeholderId))
        setChatEntries(previous => [...previous, { id: `b-${clientId}`, kind: 'bot', text: reply.reply }])
      }
    } catch (caught) {
      if (comparisonId) setAnswers(previous => previous.filter(answer => answer.id !== placeholderId))
      setChatEntries(previous => [...previous, { id: `e-${clientId}`, kind: 'bot', text: errorMessage(caught, '질문에 답하지 못했어요. 잠시 후 다시 시도해주세요.') }])
    } finally { setChatBusy(false) }
  }

  // ── 업그레이드 추천 ──────────────────────────────────────────────────────
  async function startUpgrade(budgetWon: number, upgradeQuestion: string) {
    if (!analysis) return
    setUpgradeBusy(true)
    const checkDraft: CheckDraft = { question: upgradeQuestion, budget: String(budgetWon), rows: analysis.parts }
    const started = await startUpgradeMode(checkDraft)
    setUpgradeBusy(false)
    if (started) { setUpgradeOpen(false); navigate('/plan') }
  }

  // ── 장바구니 ─────────────────────────────────────────────────────────────
  async function applyWholeQuote() {
    if (!analysis) return
    const priceByPart = new Map((analysis.prices?.rows ?? []).map(row => [row.part, row]))
    const slots = analysis.parts.map(part => part.part)
    setBusy('apply'); setError('')
    try {
      const result = await api.checks.apply(analysis.listId, slots)
      const items = analysis.parts.map((part, index) => {
        const price = priceByPart.get(part.part)
        const quantity = price?.quantity ?? 1
        const rowTotal = price?.quoted ?? 0
        return {
          id: `${result.listId}-${REVIEW_PART_KEYS[part.part] ?? 'part'}-${index}`,
          key: REVIEW_PART_KEYS[part.part] ?? null,
          type: part.part,
          name: part.matched || part.original,
          price: rowTotal,
          qty: quantity,
          unitPrice: quantity > 0 ? Math.round(rowTotal / quantity) : rowTotal,
          meta: part.original,
          source: '받은 견적',
          action: '',
          actionClass: '' as const,
          score: '',
          fit: part.matchedNote || `받은 견적에서 인식한 ${part.part} 부품입니다.`,
          reasonTitle: '인식 결과',
          tags: [part.stateLabel],
          rating: '',
          reviews: '',
          label: '',
        }
      })
      const checkDraft: CheckDraft = { question: '받은 견적 점검 결과', budget: '', rows: analysis.parts }
      const plan: CurrentPlan = {
        id: result.listId,
        mode: 'new',
        items,
        budget: null,
        conditions: { intent: '받은 견적 점검', performance: '', quiet: '' },
        checkSnapshot: checkDraft,
        compat: {
          problems: analysis.compat.checks.filter(check => check.state === 'fail').map(check => check.detail),
          unchecked: analysis.compat.checks.filter(check => check.state === 'unknown').map(check => check.detail),
        },
        compatChecks: analysis.compat.checks,
      }
      loadCheckedQuote(plan, checkDraft)
      showToast('이 견적을 장바구니에 담았습니다.')
      navigate('/cart')
    } catch (caught) { setError(errorMessage(caught, '견적을 장바구니에 반영하지 못했습니다.')) }
    finally { setBusy(null) }
  }

  const editingItem = editingId && draft ? draft.items.find(item => item.id === editingId) ?? null : null
  const savedPanel = comparison && savedVisible ? (
    <SavedComparisonPanel
      comparison={comparison} differenceOnly={differenceOnly} onDifferenceOnly={setDifferenceOnly}
      onClose={() => setSavedVisible(false)} answers={answers} openIds={openAnswerIds} onToggle={toggleAnswer}
      onCollapseAll={() => setOpenAnswerIds(new Set())} pulse={pulse}
    />
  ) : null

  return (
    <PlannerShell sidebar={
      <CheckChat
        entries={chatEntries} busy={chatBusy} analyzed={Boolean(analysis)} comparing={Boolean(comparison && savedVisible)}
        hasAnswer={id => answers.some(answer => answer.id === id)} onSend={text => void sendChat(text)} onShowAnswer={showAnswer}
      />
    }>
      <div className="ck-page">
        {!(analysis && showAnalysis) && (
          <>
            <section className="ck-card ck-workflow" aria-label="견적 점검 단계">
              {[
                ['견적 올리기', '여러 장 한 번에'], ['인식 결과 확인', '제품명·가격 분리'], ['부품별 비교', '후보와 사양 비교'], ['종합 분석', '호환성·가격·용도'],
              ].map(([title, sub], index) => (
                <div className={`ck-flow-step${workflowStep >= index + 1 ? ' active' : ''}`} key={title}>
                  <span className="ck-step-no">{index + 1}</span><div><b>{title}</b><small>{sub}</small></div>
                </div>
              ))}
            </section>
            <div className="ck-heading">
              <h1>받은 견적 점검</h1>
              <p>견적서가 여러 장이면 한 번에 올려주세요. 제품명을 깔끔하게 정리한 뒤, 부품별 대안을 비교하고 내 질문에 맞춰 평가합니다.</p>
            </div>

            <QuoteUploader
              capabilities={capabilities} tab={tab} onTab={setTab} files={files} onAddFiles={addFiles} onRemoveFile={removeFile}
              text={text} onText={setText} onTextFile={file => void loadTextFile(file)} question={question} onQuestion={setQuestion}
              activeChips={activeChips} onToggleChip={toggleChip} conditions={conditions} onConditions={setConditions}
              busy={busy === 'recognize'} onRecognize={() => void recognize()}
            />

            {error && <div className="pl-alert bad" role="alert">{error}</div>}
            {restoring && <div className="ck-loading"><div className="pl-spin" /><b>지난 견적 점검을 불러오는 중이에요</b><span>저장된 제품·분석 결과를 다시 읽고 있어요.</span></div>}
            {busy === 'analyze' && <div className="ck-loading"><div className="pl-spin" /><b>호환성·가격·밸런스를 분석하고 있어요</b><span>실제 카탈로그 응답을 기다리는 중입니다.</span></div>}

            {draft && (
              <RecognitionResult
                draft={draft} selection={selection} pending={pending} filter={filter} onFilter={setFilter}
                onSelect={(category, itemId) => setSelection(previous => ({ ...previous, [category]: itemId }))}
                onEdit={setEditingId} onCompare={category => void openCompare(category)}
                cart={cart} cartPreview={cartPreview} cartPreviewBusy={cartPreviewBusy}
                onClearCart={() => { setCart({}); showToast('교체 목록을 비웠어요.') }} onApplyCart={() => void applyCart()}
                onCancelEdits={() => { setPending({}); setSelection(effectiveSelection(draft, selection)); showToast('아직 분석하지 않은 수정을 모두 취소했어요.') }}
                onReanalyze={() => void reanalyzeEdits()} onAnalyze={() => void analyze()}
                onReviewOnly={() => { setFilter('review'); scrollTo('ck-results') }}
                busy={busy !== null}
              />
            )}
          </>
        )}

        {analysis && showAnalysis && draft && (
          <div id="ck-analysis">
            {error && <div className="pl-alert bad" role="alert" style={{ marginBottom: 14 }}>{error}</div>}
            <AnalysisView
              analysis={analysis} conditions={draft.conditions} sectionRef={analysisRef}
              onBack={backToResults} onOpenSaved={() => { setPickerError(''); setPickedSetupId(comparison ? pickedSetupId : null); setPickerOpen(true) }}
              savedOpen={Boolean(comparison && savedVisible)} onCart={() => void applyWholeQuote()} cartBusy={busy === 'apply'} onUpgrade={() => setUpgradeOpen(true)}
              savedPanel={savedPanel} liveLookup={liveLookup} onLiveLookup={item => void runLiveLookup(item)}
            />
          </div>
        )}
      </div>

      {upgradeOpen && analysis && (
        <UpgradeDialog
          initialBudget={typeof draft?.conditions.budget_max === 'number' ? draft.conditions.budget_max : null}
          initialQuestion={analysis.question?.trim() || '업그레이드 우선순위를 알려줘'}
          busy={upgradeBusy} onConfirm={(budgetWon, upgradeQuestion) => void startUpgrade(budgetWon, upgradeQuestion)} onClose={() => setUpgradeOpen(false)}
        />
      )}

      {editingItem && (
        <ItemEditDialog item={editingItem} pending={pending[editingItem.id]} onSave={saveEdit} onClose={() => setEditingId(null)} />
      )}

      {compareCategory && draft && (
        <PartCompareDialog
          category={compareCategory} data={compareData} loading={compareLoading} error={compareError} draft={draft}
          selectedItemId={selection[compareCategory]} choice={choice} onChoice={setChoice} onApply={applyChoice} onClose={closeCompare}
        />
      )}

      {pickerOpen && (
        <SavedQuotePicker
          setups={savedSetups as SavedSetup[]} loading={savedSetupsLoading} error={pickerError || savedSetupsError || ''}
          selectedId={pickedSetupId} busy={busy === 'saved'} onSelect={setup => setPickedSetupId(setup.id)}
          onConfirm={() => void confirmSavedComparison()} onClose={() => setPickerOpen(false)}
        />
      )}
    </PlannerShell>
  )
}
