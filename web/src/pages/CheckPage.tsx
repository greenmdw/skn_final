import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import PlannerShell from '../components/PlannerShell'
import { api, errorMessage, type LiveSpecLookupResult, type QuoteApplyResult, type QuoteChatMessage, type QuotePartComparison, type QuoteReviewResult } from '../api'
import type { ReviewRow } from '../state/types'
import { useToast } from '../state/ToastContext'
import { wonFmt } from '../utils/format'
import '../styles/check.css'

type SourceKind = 'image' | 'text'
type BusyKind = 'preview' | 'create' | 'update' | 'apply' | null

const checkReviewClient = api.checks

function fileSize(size: number): string {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    reader.readAsDataURL(file)
  })
}

function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    reader.readAsText(file, 'utf-8')
  })
}

function valueText(value: unknown): string {
  if (value == null) return '정보 없음'
  if (typeof value === 'number') return value.toLocaleString('ko-KR')
  if (typeof value === 'string') return value || '정보 없음'
  return String(value)
}

function reviewText(review: Record<string, unknown> | null): string {
  if (!review) return '리뷰 정보 없음'
  const rating = typeof review.rating === 'number' ? review.rating.toFixed(1) : null
  const count = typeof review.count === 'number' ? review.count.toLocaleString('ko-KR') : null
  return rating ? `★ ${rating}${count ? ` · 리뷰 ${count}건` : ''}` : '리뷰 정보 없음'
}

function CheckSidebar({ listId, messages, busy, onSend }: {
  listId: string | null
  messages: QuoteChatMessage[]
  busy: boolean
  onSend: (text: string) => void
}) {
  const [draft, setDraft] = useState('')
  const logRef = useRef<HTMLDivElement>(null)
  const suggestions = ['호환 문제를 알려줘', '비싼 부품을 알려줘', 'GPU 대안을 비교해줘']

  function submit(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || !listId || busy) return
    setDraft('')
    onSend(text)
  }

  return (
    <aside className="pl-chat ck-chat" aria-label="견적 점검 대화">
      <div className="pl-chat-head"><span className="pl-dot" />견적 점검 대화</div>
      <div className="pl-chat-log" ref={logRef}>
        <div className="pl-msg-bot">
          이미지나 텍스트 견적을 올려주세요. 인식된 부품을 확인한 뒤 호환성, 가격, 용도 대비 균형을 실제 서버 데이터로 분석합니다.
        </div>
        {listId && messages.length === 0 && (
          <div className="pl-msg-bot">분석이 완료됐어요. 결과에서 궁금한 부분을 자유롭게 물어보세요.</div>
        )}
        {messages.map(message => (
          <div key={message.id} className={message.role === 'user' ? 'pl-msg-user' : 'pl-msg-bot'}>{message.text}</div>
        ))}
        {busy && <div className="pl-typing pl-mono">···</div>}
      </div>
      <div className="pl-chat-foot">
        {listId && (
          <div className="pl-choices ck-quick">
            {suggestions.map(text => <button type="button" className="pl-choice" key={text} disabled={busy} onClick={() => onSend(text)}>{text}</button>)}
          </div>
        )}
        <form className="pl-input" onSubmit={submit}>
          <input value={draft} onChange={event => setDraft(event.target.value)}
            placeholder={listId ? '분석 결과에 관해 물어보세요' : '분석을 완료하면 질문할 수 있어요'} disabled={!listId || busy} />
          <button type="submit" className="pl-send" disabled={!listId || busy || !draft.trim()}>보내기</button>
        </form>
      </div>
    </aside>
  )
}

export default function CheckPage() {
  const { showToast } = useToast()
  const fileInput = useRef<HTMLInputElement>(null)
  const analysisRef = useRef<HTMLElement>(null)
  const [sourceKind, setSourceKind] = useState<SourceKind>('image')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [imageDataUrl, setImageDataUrl] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [specs, setSpecs] = useState<Record<string, string>>({})
  const [previewRows, setPreviewRows] = useState<ReviewRow[]>([])
  const [review, setReview] = useState<QuoteReviewResult | null>(null)
  const [editingSlot, setEditingSlot] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [busy, setBusy] = useState<BusyKind>(null)
  const [error, setError] = useState('')
  const [showSavedCompare, setShowSavedCompare] = useState(false)
  const [comparison, setComparison] = useState<QuotePartComparison | null>(null)
  const [selectedCandidate, setSelectedCandidate] = useState('')
  const [compareBusy, setCompareBusy] = useState('')
  const [chatMessages, setChatMessages] = useState<QuoteChatMessage[]>([])
  const [chatBusy, setChatBusy] = useState(false)
  const [applyResult, setApplyResult] = useState<QuoteApplyResult | null>(null)
  // DB 미보유 부품 실시간 검색(docs/미보유부품_실시간스펙검색_설계.md) — 슬롯별 상태. 자동 실행 금지라
  // 사용자가 버튼을 눌렀을 때만 slot별로 채운다.
  const [liveLookup, setLiveLookup] = useState<Record<string, { status: 'loading' | 'done'; result?: LiveSpecLookupResult; error?: string }>>({})

  const priceByPart = useMemo(() => new Map((review?.prices?.rows ?? []).map(row => [row.part, row])), [review])
  const unmatchedParts = useMemo(() => (review?.parts ?? []).filter(row => row.matchStatus === 'unmatched'), [review])
  const comparisonSlots = useMemo(() => (review?.parts ?? previewRows).map(row => row.part), [review, previewRows])
  const comparablePriceRows = useMemo(() => (review?.prices?.rows ?? []).filter(row => row.quoted != null && row.catalog != null && row.diff != null), [review])
  const totalPriceDiff = useMemo(() => comparablePriceRows.reduce((sum, row) => sum + (row.diff ?? 0), 0), [comparablePriceRows])
  const quoteTitle = useMemo(() => selectedFile?.name.replace(/\.[^.]+$/, '') || '받은 견적', [selectedFile])

  useEffect(() => {
    if (!review) return
    const frame = window.requestAnimationFrame(() => analysisRef.current?.scrollIntoView({ block: 'start' }))
    return () => window.cancelAnimationFrame(frame)
  }, [review])

  function resetResult() {
    setReview(null)
    setChatMessages([])
    setShowSavedCompare(false)
    setApplyResult(null)
    setEditingSlot(null)
    setLiveLookup({})
  }

  async function runLiveLookup(slot: string) {
    if (!review) return
    setLiveLookup(previous => ({ ...previous, [slot]: { status: 'loading' } }))
    try {
      const result = await api.checks.liveLookupPart(review.listId, slot)
      setLiveLookup(previous => ({ ...previous, [slot]: { status: 'done', result } }))
    } catch (caught) {
      setLiveLookup(previous => ({ ...previous, [slot]: { status: 'done', error: errorMessage(caught, '실시간 검색에 실패했습니다.') } }))
    }
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setError('')
    resetResult()
    try {
      if (file.type.startsWith('image/')) {
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('PNG·JPEG·WebP 이미지만 올릴 수 있습니다.')
        if (file.size > 5 * 1024 * 1024) throw new Error('이미지는 5MB 이하로 올려주세요.')
        setSourceKind('image')
        setImageDataUrl(await readAsDataUrl(file))
        setSourceText('')
      } else {
        const name = file.name.toLowerCase()
        if (!(file.type.startsWith('text/') || name.endsWith('.txt') || name.endsWith('.csv'))) throw new Error('텍스트 파일은 TXT 또는 CSV 형식만 올릴 수 있습니다.')
        const text = await readAsText(file)
        if (text.length > 20_000) throw new Error('텍스트는 20,000자 이하로 줄여주세요.')
        setSourceKind('text')
        setSourceText(text)
        setImageDataUrl('')
      }
      setSelectedFile(file)
      setPreviewRows([])
      setSpecs({})
    } catch (caught) {
      setSelectedFile(null)
      setError(caught instanceof Error ? caught.message : '파일을 읽지 못했습니다.')
    }
  }

  function currentRequest(currentSpecs = specs) {
    return {
      currentSpecs,
      text: sourceKind === 'text' ? sourceText : undefined,
      imageDataUrl: sourceKind === 'image' ? imageDataUrl : undefined,
    }
  }

  async function preview() {
    if (!imageDataUrl && !sourceText.trim() && Object.values(specs).every(value => !value.trim())) {
      setError('분석할 이미지나 텍스트 파일을 올려주세요.')
      return
    }
    setBusy('preview'); setError('')
    try {
      const rows = await checkReviewClient.previewOwnedParts(currentRequest())
      if (!rows.length) {
        setPreviewRows([])
        setError('부품 정보를 인식하지 못했습니다. 다른 이미지나 텍스트 파일을 올려주세요.')
        return
      }
      setPreviewRows(rows)
      setSpecs(Object.fromEntries(rows.map(row => [row.part, row.original])))
      showToast(`${rows.length}개 부품을 인식했습니다.`)
    } catch (caught) {
      setError(errorMessage(caught, '파일을 인식하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  async function analyze() {
    if (!imageDataUrl && !sourceText.trim() && Object.values(specs).every(value => !value.trim())) {
      setError('분석할 부품 정보를 입력해주세요.')
      return
    }
    setBusy('create'); setError(''); setApplyResult(null)
    try {
      const result = await checkReviewClient.createReview(currentRequest())
      setReview(result)
      setSpecs(result.input.currentSpecs)
      setPreviewRows(result.parts)
      setShowSavedCompare(false)
      setChatMessages(await checkReviewClient.getMessages(result.listId))
      showToast('견적 분석이 완료됐습니다.')
    } catch (caught) {
      setError(errorMessage(caught, '견적을 분석하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  async function updateAnalysis(nextSpecs = specs) {
    if (!review) return
    setBusy('update'); setError('')
    try {
      const result = await checkReviewClient.updateReview(review.listId, currentRequest(nextSpecs))
      setReview(result); setPreviewRows(result.parts); setSpecs(result.input.currentSpecs)
      showToast('수정한 부품으로 다시 분석했습니다.')
    } catch (caught) {
      setError(errorMessage(caught, '수정 내용을 반영하지 못했습니다.'))
    } finally { setBusy(null) }
  }

  function startEdit(row: ReviewRow) {
    setEditingSlot(row.part)
    setEditValue(specs[row.part] ?? row.original)
    setError('')
  }

  async function saveEdit(slot: string) {
    const value = editValue.trim()
    if (!value) {
      setError('제품명을 입력해주세요.')
      return
    }
    const nextSpecs = { ...specs, [slot]: value }
    setSpecs(nextSpecs)
    setEditingSlot(null)
    setApplyResult(null)
    if (review) {
      await updateAnalysis(nextSpecs)
      return
    }
    setPreviewRows(previous => previous.map(row => row.part === slot
      ? { ...row, original: value, matched: '', matchedNote: '비교 분석 시 다시 확인합니다.', state: 'warn', stateLabel: '수정됨' }
      : row))
    showToast(`${slot} 정보를 수정했습니다.`)
  }

  function editableProduct(row: ReviewRow) {
    if (editingSlot !== row.part) {
      return <div className="ck-product-cell"><span>{row.original}</span><button type="button" className="ck-edit-button" onClick={() => startEdit(row)} aria-label={`${row.part} 정보 수정`} title="정보 수정"><span aria-hidden="true">✎</span></button></div>
    }
    return <div className="ck-inline-edit"><input autoFocus value={editValue} onChange={event => setEditValue(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void saveEdit(row.part); if (event.key === 'Escape') setEditingSlot(null) }} aria-label={`${row.part} 제품명`} /><button type="button" className="ck-edit-save" disabled={busy !== null} onClick={() => void saveEdit(row.part)}>저장</button><button type="button" className="ck-edit-cancel" onClick={() => setEditingSlot(null)}>취소</button></div>
  }

  async function comparePart(slot: string) {
    if (!review) return
    setCompareBusy(slot); setError('')
    try {
      setComparison(await checkReviewClient.comparePart(review.listId, slot))
      setSelectedCandidate('')
    }
    catch (caught) { setError(errorMessage(caught, '부품 후보를 비교하지 못했습니다.')) }
    finally { setCompareBusy('') }
  }

  function applyComparedCandidate() {
    if (!comparison || !selectedCandidate) return
    const candidate = comparison.candidates.find(item => item.name === selectedCandidate)
    if (!candidate) return
    const slot = comparison.slot
    const nextSpecs = { ...specs, [slot]: candidate.name }
    setSpecs(nextSpecs)
    setPreviewRows(previous => previous.map(row => row.part === slot
      ? { ...row, original: candidate.name, matched: candidate.name, matchedNote: '', state: 'ok', stateLabel: '선택됨' }
      : row))
    setReview(previous => previous ? {
      ...previous,
      input: { ...previous.input, currentSpecs: nextSpecs },
      parts: previous.parts.map(row => row.part === slot
        ? { ...row, original: candidate.name, matched: candidate.name, matchedNote: '', state: 'ok', stateLabel: '선택됨' }
        : row),
      prices: previous.prices ? {
        ...previous.prices,
        rows: previous.prices.rows.map(row => row.part === slot
          ? { ...row, matched: candidate.name, quoted: candidate.price, diff: candidate.priceDelta }
          : row),
      } : null,
    } : null)
    setComparison(null)
    setSelectedCandidate('')
    showToast(`${slot}을(를) 선택한 후보로 바꿨습니다.`)
  }

  async function sendChat(text: string) {
    if (!review || chatBusy) return
    const user: QuoteChatMessage = { id: `local-${Date.now()}`, role: 'user', text, createdAt: new Date().toISOString() }
    setChatMessages(previous => [...previous, user]); setChatBusy(true)
    try {
      const reply = await checkReviewClient.sendMessage(review.listId, text)
      setChatMessages(previous => [...previous, { id: `reply-${Date.now()}`, role: 'assistant', text: reply.reply, createdAt: new Date().toISOString() }])
    } catch (caught) {
      setError(errorMessage(caught, '질문에 답하지 못했습니다.'))
    } finally { setChatBusy(false) }
  }

  function returnToRecognition() {
    setReview(null)
    setChatMessages([])
    setShowSavedCompare(false)
    setApplyResult(null)
    setError('')
  }

  async function applyWholeQuote() {
    if (!review) return
    const slots = review.parts.map(part => part.part)
    setBusy('apply'); setError('')
    try {
      const result = await checkReviewClient.apply(review.listId, slots)
      setApplyResult(result)
      showToast('이 견적을 장바구니 구성에 반영했습니다.')
    } catch (caught) { setError(errorMessage(caught, '견적을 장바구니에 반영하지 못했습니다.')) }
    finally { setBusy(null) }
  }

  return (
    <PlannerShell sidebar={<CheckSidebar listId={review?.listId ?? null} messages={chatMessages} busy={chatBusy} onSend={sendChat} />}>
      <div className="ck-page">
        <div className="ck-heading">
          <h1>받은 견적 올리기</h1>
          <p>견적 이미지나 텍스트를 올린 뒤 인식 결과를 확인해주세요. 확인한 부품만 실제 카탈로그와 비교합니다.</p>
        </div>

        <section className="ck-upload-card">
          <div className="ck-source-tabs">
            <button type="button" className={sourceKind === 'image' ? 'on' : ''} onClick={() => setSourceKind('image')}>이미지 캡처</button>
            <button type="button" className={sourceKind === 'text' ? 'on' : ''} onClick={() => setSourceKind('text')}>텍스트·파일</button>
          </div>
          <div className="ck-upload-grid">
            <div className="ck-drop">
              <input ref={fileInput} type="file" hidden accept="image/png,image/jpeg,image/webp,.txt,.csv,text/plain,text/csv" onChange={selectFile} />
              <button type="button" className="ck-file-button" onClick={() => fileInput.current?.click()}>파일 선택</button>
              <strong>{sourceKind === 'image' ? 'PNG·JPEG·WebP, 5MB 이하' : 'TXT·CSV, 20,000자 이하'}</strong>
              <span>파일은 분석 요청에만 사용되며 화면에서 임의 결과를 만들지 않습니다.</span>
            </div>
            <div className="ck-file-preview">
              {selectedFile ? (
                <>
                  {imageDataUrl ? <img src={imageDataUrl} alt="선택한 견적 미리보기" /> : <div className="ck-text-icon">TXT</div>}
                  <div><b>{selectedFile.name}</b><span>{fileSize(selectedFile.size)}</span></div>
                </>
              ) : <div className="ck-empty-file">선택한 파일이 없습니다.</div>}
            </div>
          </div>
          {sourceKind === 'text' && (
            <textarea className="ck-source-text" value={sourceText} maxLength={20_000}
              onChange={event => { setSourceText(event.target.value); setSelectedFile(null); resetResult() }}
              placeholder={'견적 내용을 붙여넣거나 텍스트 파일을 선택하세요.\n예: CPU: Intel Core i5-14400F 238,000원'} />
          )}
          <div className="ck-actions">
            <button type="button" className="pl-btn" disabled={busy !== null} onClick={preview}>{busy === 'preview' ? '인식 중…' : '부품 인식하기'}</button>
          </div>
        </section>

        {error && <div className="pl-alert bad" role="alert">{error}</div>}
        {busy === 'create' && <div className="ck-loading"><div className="pl-spin" /><b>호환성·가격·밸런스를 분석하고 있어요</b><span>실제 카탈로그 응답을 기다리는 중입니다.</span></div>}

        {!review && previewRows.length > 0 && (
          <section className="ck-results ck-recognition">
            <div className="ck-result-head"><div><b>인식 결과</b><span>잘못 인식된 제품은 행의 연필 버튼으로 수정해주세요.</span></div></div>
            <div className="ck-table-wrap"><table className="ck-parts-table ck-preview-table"><thead><tr><th>슬롯</th><th>인식한 제품명</th><th>카탈로그 대응</th><th>상태</th></tr></thead><tbody>
              {previewRows.map(row => (
                <tr key={row.part}><td><b>{row.part}</b></td><td>{editableProduct(row)}</td><td>{row.matched || row.matchedNote || '비교 분석 시 확인'}</td><td><span className={`ck-status ${row.state}`}>{row.stateLabel}</span></td></tr>
              ))}
            </tbody></table></div>
            <div className="ck-recognition-action"><span>인식한 부품을 실제 카탈로그와 비교하고 호환성을 분석합니다.</span><button type="button" className="pl-btn" disabled={busy !== null || editingSlot !== null} onClick={analyze}>{busy === 'create' ? '분석 중…' : '비교 분석하기'}</button></div>
          </section>
        )}

        {review && (
          <section className="ck-analysis-view" ref={analysisRef}>
            <header className="ck-analysis-head">
              <div>
                <span className="ck-analysis-kicker">받은 견적 점검 · 비교 분석</span>
                <h1>{quoteTitle} 비교 분석</h1>
              </div>
              <button type="button" className="ck-analysis-outline" onClick={() => setShowSavedCompare(previous => !previous)}>
                {showSavedCompare ? '분석 결과로 돌아가기' : '저장한 견적과 비교'}
              </button>
            </header>

            {!showSavedCompare ? (
              <div className="ck-summary-grid">
                <article className="ck-summary-card">
                  <div className="ck-summary-title"><h2>호환 검사</h2><span>추천엔진 규칙으로 확인한 결과</span></div>
                  {review.compat.checks.length ? (
                    <div className="ck-compat-list">
                      {review.compat.checks.map(check => (
                        <div className="ck-compat-row" key={check.axis}>
                          <span className={`ck-analysis-status ${check.state}`}>{{ ok: '통과', fail: '문제', unknown: '확인하지 못함', skipped: '해당 없음' }[check.state]}</span>
                          <div><b>{check.label}</b><p>{check.detail}</p></div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="pl-empty">서버가 반환한 호환성 검사 항목이 없습니다.</div>}
                </article>

                <article className="ck-summary-card">
                  <div className="ck-summary-title"><h2>가격 비교</h2><span>인식한 가격 vs 카탈로그 가격 · 수량 반영</span></div>
                  {review.prices?.available ? (
                    <>
                      <div className="ck-price-table-wrap">
                        <table className="ck-price-table">
                          <thead><tr><th>슬롯</th><th>수량</th><th>인식한 가격</th><th>카탈로그</th><th>차이</th></tr></thead>
                          <tbody>{review.prices.rows.map(row => (
                            <tr key={row.part}>
                              <td><b>{row.part}</b></td>
                              <td>{row.quantity > 1 ? `×${row.quantity}` : ''}</td>
                              <td>{row.quoted != null ? wonFmt(row.quoted) : '—'}</td>
                              <td>{row.catalog != null ? wonFmt(row.catalog) : '—'}</td>
                              <td className={row.diff == null || row.diff === 0 ? '' : row.diff > 0 ? 'up' : 'down'}>{row.diff == null ? '—' : `${row.diff > 0 ? '+' : ''}${wonFmt(row.diff)}`}</td>
                            </tr>
                          ))}</tbody>
                        </table>
                      </div>
                      <p className="ck-price-summary">
                        가격을 비교할 수 있는 {comparablePriceRows.length}개 품목 기준, 받은 견적이 카탈로그보다
                        <strong className={totalPriceDiff > 0 ? 'up' : totalPriceDiff < 0 ? 'down' : ''}> {totalPriceDiff === 0 ? '같습니다' : `${wonFmt(Math.abs(totalPriceDiff))} ${totalPriceDiff > 0 ? '비쌉니다' : '저렴합니다'}`}</strong>.
                        카탈로그 대응이나 가격이 없는 품목은 합계에서 제외했습니다.
                      </p>
                    </>
                  ) : <div className="pl-empty">{review.prices?.reason ?? '가격 비교 결과가 없습니다.'}</div>}
                </article>
              </div>
            ) : (
              <article className="ck-summary-card ck-saved-compare">
                <div className="ck-summary-title"><h2>저장한 견적과 비교</h2><span>현재 받은 견적과 TrueFit 추천 구성을 비교합니다.</span></div>
                {review.compare?.available ? (
                  <div className="ck-saved-list">{review.compare.rows.map(row => (
                    <div key={row.part}><b>{row.part}</b><span className={`ck-analysis-status ${row.sameProduct ? 'ok' : 'unknown'}`}>{row.sameProduct ? '같은 제품' : '구성 차이'}</span><p>{row.detail}</p></div>
                  ))}</div>
                ) : <div className="pl-empty">{review.compare?.reason ?? '저장한 견적과 비교할 결과가 없습니다.'}</div>}
              </article>
            )}

            {unmatchedParts.length > 0 && (
              <article className="ck-summary-card ck-unmatched-card">
                <div className="ck-summary-title"><h2>카탈로그에 없는 부품</h2><span>신제품이거나 표기가 특이해 대응을 못 찾았어요</span></div>
                <div className="ck-unmatched-list">
                  {unmatchedParts.map(part => {
                    const lookup = liveLookup[part.part]
                    return (
                      <div className="ck-unmatched-row" key={part.part}>
                        <div className="ck-unmatched-head">
                          <div><b>{part.part}</b><span>{part.original}</span></div>
                          {!lookup && (
                            <button type="button" className="ck-compare" onClick={() => runLiveLookup(part.part)}>실시간으로 찾아볼까요?</button>
                          )}
                          {lookup?.status === 'loading' && <span className="ck-unmatched-loading"><span className="pl-spin" />검색 중…</span>}
                        </div>
                        {lookup?.status === 'done' && (
                          <div className="ck-unmatched-result">
                            {lookup.error ? (
                              <p className="bad">{lookup.error}</p>
                            ) : lookup.result && lookup.result.relevant && Object.values(lookup.result.supportedFields).some(v => v != null) ? (
                              <>
                                <dl>
                                  {Object.entries(lookup.result.supportedFields).filter(([, v]) => v != null).map(([key, value]) => (
                                    <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
                                  ))}
                                </dl>
                                {lookup.result.sourceUrl && <p className="ck-unmatched-source">출처: <a href={lookup.result.sourceUrl} target="_blank" rel="noreferrer">{lookup.result.sourceUrl}</a></p>}
                                <p className="ck-unmatched-disclaimer">카탈로그 정식 등재 값이 아니라 실시간 검색 결과예요 — 구매 전 공식 사이트에서 다시 확인하세요.</p>
                              </>
                            ) : (
                              <p className="ck-unmatched-disclaimer">실시간 검색으로도 찾지 못했어요. <button type="button" className="ck-unmatched-retry" onClick={() => runLiveLookup(part.part)}>다시 시도</button></p>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </article>
            )}

            <div className="ck-analysis-actions">
              <button type="button" className="ck-analysis-outline" onClick={returnToRecognition}>인식 결과 고치기</button>
              <button type="button" className="pl-btn" disabled={busy !== null} onClick={applyWholeQuote}>{busy === 'apply' ? '반영 중…' : '이 견적으로 장바구니 담기'}</button>
            </div>
            {applyResult && <div className="pl-alert"><b>견적을 장바구니 구성에 반영했습니다.</b> {applyResult.missing.length ? `추가로 필요한 조건: ${applyResult.missing.join(', ')}` : applyResult.runId ? '추천 계산을 시작했습니다.' : '장바구니에 반영했습니다.'}</div>}
          </section>
        )}
      </div>

      {comparison && (
        <div className="pl-modal-back" onMouseDown={event => { if (event.target === event.currentTarget) { setComparison(null); setSelectedCandidate('') } }}>
          <section className="pl-modal ck-modal ck-compare-modal" role="dialog" aria-modal="true" aria-label={`${comparison.slot} 부품 비교`}>
            <div className="ck-compare-modal-head">
              <div><b>같은 카테고리 부품 비교</b><span>열을 눌러 고르거나 다른 부품 탭을 선택하세요.</span></div>
              <button type="button" className="ck-modal-close" onClick={() => { setComparison(null); setSelectedCandidate('') }} aria-label="비교 창 닫기">×</button>
            </div>
            <div className="ck-category-tabs" aria-label="비교할 부품 카테고리">
              {comparisonSlots.map(slot => <button type="button" key={slot} className={comparison.slot === slot ? 'on' : ''} disabled={compareBusy === slot} onClick={() => comparePart(slot)}>{slot}</button>)}
            </div>
            <div className="ck-compare-modal-body">
              {comparison.note && <div className="ck-compare-note">{comparison.note}</div>}
              <div className="ck-compare-grid">
                <article className="ck-compare-card current">
                  <span className="ck-card-label">받은 견적</span>
                  <h3>{valueText(comparison.baseline.name)}</h3>
                  <strong className="ck-card-price">{(() => {
                    const currentPrice = priceByPart.get(comparison.slot)?.quoted ?? null
                    return currentPrice != null ? wonFmt(currentPrice) : '가격 정보 없음'
                  })()}</strong>
                  <div className="ck-card-section"><span>카탈로그 대응</span><p>현재 견적의 기준 제품</p></div>
                  <div className="ck-card-section"><span>나머지 부품과 호환</span><p><i className="ok">기준</i> 현재 구성</p></div>
                  <div className="ck-card-section"><span>견적 가격 대비</span><p>기준</p></div>
                </article>
                {comparison.candidates.map(candidate => {
                  const selected = selectedCandidate === candidate.name
                  return <button type="button" className={`ck-compare-card${selected ? ' selected' : ''}`} key={candidate.name} onClick={() => setSelectedCandidate(candidate.name)}>
                    {selected && <span className="ck-card-label picked">선택</span>}
                    <h3>{candidate.name}</h3>
                    <strong className="ck-card-price">{wonFmt(candidate.price)}</strong>
                    <div className="ck-card-section"><span>스펙</span><p>{candidate.specs.map(spec => `${spec.label} ${valueText(spec.candidate)}${spec.unit}`).join(' · ')}</p></div>
                    <div className="ck-card-section"><span>리뷰</span><p>{reviewText(candidate.review)}</p></div>
                    <div className="ck-card-section"><span>견적의 나머지 부품과 호환</span>{candidate.incompatible.length ? <p><i className="bad">문제</i> {candidate.incompatible.join(', ')}</p> : <p><i className="ok">통과</i> 현재 구성과 호환</p>}</div>
                    <div className="ck-card-section"><span>견적 가격 대비</span><p className={candidate.priceDelta != null && candidate.priceDelta > 0 ? 'delta-up' : 'delta-down'}>{candidate.priceDelta == null ? '비교 정보 없음' : `${candidate.priceDelta > 0 ? '+' : ''}${wonFmt(candidate.priceDelta)}`}</p></div>
                  </button>
                })}
              </div>
            </div>
            <div className="ck-compare-modal-foot">
              <span>수치는 카탈로그 값과 리뷰 근거를 기준으로 표시됩니다.</span>
              <div><button type="button" className="ck-modal-secondary" onClick={() => { setComparison(null); setSelectedCandidate('') }}>닫기</button><button type="button" className="ck-modal-apply" disabled={!selectedCandidate} onClick={applyComparedCandidate}>이 부품으로 바꾸기</button></div>
            </div>
          </section>
        </div>
      )}
    </PlannerShell>
  )
}
