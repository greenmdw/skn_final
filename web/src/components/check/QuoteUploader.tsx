import { useEffect, useRef, useState, type ChangeEvent, type DragEvent, type MouseEvent } from 'react'
import type { QuoteCapabilities, QuoteConditions } from '../../api'
import { fileSize } from '../../utils/checkReview'
import PhotoPreviewDialog from './PhotoPreviewDialog'

export interface UploadFile { id: string; file: File; url: string }

const PROMPT_CHIPS: { label: string; prompt: string }[] = [
  { label: '호환성', prompt: '호환되지 않는 부품이 있는지 확인해줘.' },
  { label: '가격 적정성', prompt: '시세보다 비싸게 산 부품을 찾아줘.' },
  { label: '성능 밸런스', prompt: '게임 성능에서 병목이 생길지 봐줘.' },
  { label: '업그레이드', prompt: '업그레이드 우선순위를 알려줘.' },
]

const mb = (bytes: number) => `${Math.round(bytes / 1024 / 1024)}MB`

export default function QuoteUploader({
  capabilities, tab, onTab, files, onAddFiles, onRemoveFile, text, onText, onTextFile,
  question, onQuestion, activeChips, onToggleChip, conditions, onConditions, busy, onRecognize,
}: {
  capabilities: QuoteCapabilities | null
  tab: 'image' | 'text'
  onTab: (tab: 'image' | 'text') => void
  files: UploadFile[]
  onAddFiles: (files: File[]) => void
  onRemoveFile: (id: string) => void
  text: string
  onText: (value: string) => void
  onTextFile: (file: File) => void
  question: string
  onQuestion: (value: string) => void
  activeChips: string[]
  onToggleChip: (label: string, prompt: string) => void
  conditions: QuoteConditions
  onConditions: (next: QuoteConditions) => void
  busy: boolean
  onRecognize: () => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const textInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const maxFiles = capabilities?.maxFiles ?? 3
  const imageOn = capabilities?.imageExtraction ?? true
  const textMax = capabilities?.textMaxChars ?? 20_000

  const previewIndex = previewId ? files.findIndex(entry => entry.id === previewId) : -1

  useEffect(() => {
    if (previewId && previewIndex < 0) setPreviewId(null)
  }, [previewId, previewIndex])

  // 영역의 빈 곳을 더블클릭해도 파일 창을 연다(버튼·사진 카드 위에서는 그 동작을 따른다).
  function openFromDoubleClick(event: MouseEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('button, article, a, input')) return
    if (files.length >= maxFiles) return
    fileInput.current?.click()
  }

  function pick(event: ChangeEvent<HTMLInputElement>) {
    onAddFiles([...(event.target.files ?? [])])
    event.target.value = ''
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    onAddFiles([...event.dataTransfer.files])
  }

  function pickText(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) onTextFile(file)
  }

  const textMode = tab === 'text'
  const recognizeLabel = busy
    ? '인식 중…'
    : textMode ? '텍스트 견적 인식하기' : files.length ? `${files.length}장 함께 인식하기` : '사진을 먼저 추가해주세요'
  const disabled = busy || (textMode ? !text.trim() : files.length === 0 || !imageOn)

  return (
    <section className="ck-card ck-upload">
      <div className="ck-upload-top">
        <div className="ck-tabs">
          <button type="button" className={tab === 'image' ? 'on' : ''} onClick={() => onTab('image')}>
            이미지 <span className={`ck-capability${imageOn ? '' : ' off'}`}>{imageOn ? '사용 가능' : '사용 불가'}</span>
          </button>
          <button type="button" className={textMode ? 'on' : ''} onClick={() => onTab('text')}>텍스트·파일</button>
        </div>
        {!textMode && <span className="ck-batch-count">첨부 <b>{files.length}장</b> · 최대 {maxFiles}장</span>}
      </div>

      {!textMode ? (
        <div
          className={`ck-drop${dragging ? ' dragging' : ''}${files.length > 0 ? ' has-files' : ''}`}
          onDragEnter={event => { event.preventDefault(); setDragging(true) }}
          onDragOver={event => { event.preventDefault(); setDragging(true) }}
          onDragLeave={event => { event.preventDefault(); setDragging(false) }}
          onDrop={drop}
          onDoubleClick={openFromDoubleClick}
        >
          <input ref={fileInput} hidden type="file" multiple accept="image/png,image/jpeg,image/webp" onChange={pick} />
          {files.length === 0 ? (
            <>
              <button type="button" className="ck-file-button" onClick={() => fileInput.current?.click()}>사진 선택</button>
              <strong>PNG·JPEG·WebP · 장당 {capabilities ? mb(capabilities.maxFileBytes) : '10MB'} 이하</strong>
              <span className="ck-capability-line">
                <i className={`ck-capability-dot${imageOn ? '' : ' off'}`} />
                {capabilities ? (imageOn ? '현재 서버에서 이미지 인식 가능' : '지금은 이미지 인식을 쓸 수 없어요 · 텍스트로 올려주세요') : '서버 상태를 확인하는 중이에요'}
              </span>
              <small>드래그해서 놓거나 이 영역을 더블클릭해도 돼요. 견적서 앞·뒷면과 상세 페이지를 함께 인식합니다.</small>
            </>
          ) : (
            <>
              <div className="ck-drop-bar">
                <span className="ck-drop-rule">
                  <i className={`ck-capability-dot${imageOn ? '' : ' off'}`} />
                  PNG·JPEG·WebP · 장당 {capabilities ? mb(capabilities.maxFileBytes) : '10MB'} 이하 · 드래그하거나 빈 곳을 더블클릭해도 돼요
                </span>
                <button type="button" className="ck-file-button" onClick={() => fileInput.current?.click()} disabled={files.length >= maxFiles}>사진 선택</button>
              </div>
              <div className="ck-file-grid">
                {files.map((entry, index) => (
                  <article className="ck-file-card" key={entry.id}>
                    <button type="button" className="ck-file-thumb" onClick={() => setPreviewId(entry.id)} aria-label={`${entry.file.name} 크게 보기`} title="클릭하면 크게 볼 수 있어요">
                      <img src={entry.url} alt="" />
                      <span className="ck-file-zoom" aria-hidden="true">⤢</span>
                    </button>
                    <span className="ck-file-order">{index + 1}</span>
                    <button type="button" className="ck-file-remove" onClick={() => onRemoveFile(entry.id)} aria-label={`${entry.file.name} 삭제`}>×</button>
                    <b title={entry.file.name}>{entry.file.name}</b>
                    <small>{fileSize(entry.file.size)} · {index === 0 ? '전체 견적' : '상세 보완'}</small>
                  </article>
                ))}
                {files.length < maxFiles && (
                  <button type="button" className="ck-add-card" onClick={() => fileInput.current?.click()}>＋<br />사진 추가</button>
                )}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="ck-text-source">
          <textarea
            className="ck-source-text" value={text} maxLength={textMax} aria-label="텍스트 견적"
            onChange={event => onText(event.target.value)}
            placeholder={'견적 내용을 붙여넣거나 텍스트 파일을 불러오세요.\n예: CPU: Intel Core i5-14400F 238,000원'}
          />
          <div className="ck-text-tools">
            <input ref={textInput} hidden type="file" accept=".txt,.csv,text/plain,text/csv" onChange={pickText} />
            <button type="button" className="ck-file-button" onClick={() => textInput.current?.click()}>TXT·CSV 불러오기</button>
            <span>{text.length.toLocaleString('ko-KR')} / {textMax.toLocaleString('ko-KR')}자</span>
          </div>
        </div>
      )}

      <div className="ck-question-box">
        <label htmlFor="ck-question">무엇을 평가할까요?<small>질문이 구체적일수록 평가 기준이 선명해져요.</small></label>
        <div className="ck-question-input">
          <textarea id="ck-question" value={question} onChange={event => onQuestion(event.target.value)} placeholder="예: QHD 게임용으로 적당한지, 같은 예산에서 바꿀 부품이 있는지 봐줘." />
          <div className="ck-chips">
            {PROMPT_CHIPS.map(chip => (
              <button type="button" key={chip.label} className={`ck-chip${activeChips.includes(chip.label) ? ' on' : ''}`} onClick={() => onToggleChip(chip.label, chip.prompt)}>{chip.label}</button>
            ))}
          </div>
          <div className="ck-conditions">
            <label>용도
              <select value={conditions.purpose ?? ''} onChange={event => onConditions({ ...conditions, purpose: (event.target.value || undefined) as QuoteConditions['purpose'] })}>
                <option value="">선택 안 함</option><option value="game">게임</option><option value="creation">창작</option><option value="office">사무</option><option value="study">학습</option><option value="other">기타</option>
              </select>
            </label>
            <label>해상도
              <select value={conditions.resolution ?? ''} onChange={event => onConditions({ ...conditions, resolution: (event.target.value || undefined) as QuoteConditions['resolution'] })}>
                <option value="">선택 안 함</option><option value="FHD_144">FHD 144Hz</option><option value="QHD_165">QHD 165Hz</option><option value="4K">4K</option>
              </select>
            </label>
            <label>우선순위
              <select value={conditions.priority ?? ''} onChange={event => onConditions({ ...conditions, priority: (event.target.value || undefined) as QuoteConditions['priority'] })}>
                <option value="">선택 안 함</option><option value="performance">성능 우선</option><option value="value">가성비</option><option value="quiet">저소음</option>
              </select>
            </label>
            <label>예산(만 원)
              <input type="number" min={0} max={10000} step={10} inputMode="numeric" value={conditions.budgetMax ? conditions.budgetMax / 10_000 : ''}
                onChange={event => onConditions({ ...conditions, budgetMax: event.target.value ? Math.round(Number(event.target.value) * 10_000) : undefined })} placeholder="예: 120" />
            </label>
          </div>
          <small className="ck-conditions-note">용도를 고르면 용도 대비 균형과 우리 추천과의 비교가 함께 분석돼요. 고르지 않아도 호환성·가격은 확인합니다.</small>
        </div>
      </div>

      {previewIndex >= 0 && (
        <PhotoPreviewDialog files={files} index={previewIndex} onIndex={index => setPreviewId(files[index].id)} onClose={() => setPreviewId(null)} onRemove={onRemoveFile} />
      )}

      <div className="ck-upload-actions">
        <span className="ck-upload-note">완전히 같은 제품만 중복으로 묶고, 서로 다른 모델은 모두 남겨서 비교할 수 있어요.</span>
        <button type="button" className="ck-primary" disabled={disabled} onClick={onRecognize}>{recognizeLabel}</button>
      </div>
    </section>
  )
}
