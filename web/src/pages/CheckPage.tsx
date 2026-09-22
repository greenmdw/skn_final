import { useRef, useState } from 'react'
import { usePlan } from '../state/PlanContext'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../state/ToastContext'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { api, errorMessage } from '../api'
import {
  isImageFile, readImageAsDataUrl, SPEC_FILE_ACCEPT, SPEC_FILE_MAX_BYTES, SPEC_IMAGE_ACCEPT, SPEC_IMAGE_MAX_BYTES, SPEC_TEXT_MAX_CHARS,
} from '../utils/specFile'

const ACCEPT = [SPEC_FILE_ACCEPT, SPEC_IMAGE_ACCEPT].join(',')

export function CheckPage() {
  useDocumentTitle('내 PC·견적 점검')
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { checkDraft, updateCheckDraft } = usePlan()
  const { question, budget } = checkDraft
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadedName, setUploadedName] = useState('')

  async function applyRows(rows: Awaited<ReturnType<typeof api.checks.previewOwnedParts>>, file: File) {
    if (rows.length === 0) {
      showToast('파일에서 부품 정보를 찾지 못했습니다. "CPU: i5-14400F" 형식의 줄이 있는지 확인해주세요.')
      return
    }
    updateCheckDraft({ rows: rows.map(r => ({ ...r, originalNote: '업로드한 파일에서 읽음' })) })
    setUploadedName(file.name)
    showToast(`${file.name}에서 ${rows.length}개 부품을 인식했습니다. 다음 화면에서 확인해주세요.`)
  }

  async function handleFile(file: File) {
    setUploading(true)
    try {
      if (isImageFile(file)) {
        if (file.size > SPEC_IMAGE_MAX_BYTES) { showToast('이미지가 너무 큽니다(5MB 이하로 올려주세요).'); return }
        // 이미지는 슬롯별로 나눌 규칙이 없다 — 서버의 LLM 추출에만 맡긴다(꺼져 있으면 서버가 이유를 알려준다).
        const imageDataUrl = await readImageAsDataUrl(file)
        await applyRows(await api.checks.previewOwnedParts({ imageDataUrl }), file)
        return
      }
      if (file.size > SPEC_FILE_MAX_BYTES) { showToast('파일이 너무 큽니다(1MB 이하로 올려주세요).'); return }
      const content = (await file.text()).slice(0, SPEC_TEXT_MAX_CHARS)
      if (!content.trim()) { showToast('빈 파일입니다.'); return }
      // 원문을 그대로 보낸다 — 슬롯별로 나누는 건 서버가 한다(LLM 추출이 켜져 있으면 자유 문장도,
      // 아니면 "CPU: i5-14400F" 같은 정해진 줄만).
      await applyRows(await api.checks.previewOwnedParts({ text: content }), file)
    } catch (error) {
      showToast(errorMessage(error, '파일을 확인하지 못했습니다. 잠시 후 다시 시도해주세요.'))
    } finally {
      setUploading(false)
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''   // 같은 파일을 다시 골라도 onChange가 발생하게
    if (file) void handleFile(file)
  }

  return (
    <section className="landing" aria-labelledby="checkTitle">
      <div className="landing-inner check-inner">
        <button type="button" className="back-link" onClick={() => navigate('/start')}>← 처음으로</button>
        <div className="check-headrow">
          <div>
            <h1 className="landing-title" id="checkTitle">내 PC 또는 견적을<br />불러와 점검하세요.</h1>
            <p className="landing-desc">사용 중인 PC 업그레이드와 작성해둔 견적 검토를 모두 지원합니다. 파일이나 시스템 정보 중 편한 방법을 선택하세요.</p>
          </div>
          <span className="live-hint check-live-hint"><i className="live-dot" />분석 전 확인 · 원본 자동 삭제</span>
        </div>
        <div className="check-grid">
          <div className="check-card">
            <div className="check-card-head"><h2>PC 정보 불러오기</h2><span className="demo-badge check-select-badge">선택</span></div>
            <p className="check-card-sub">견적 화면 캡처나 부품 목록 텍스트 파일을 올리면 실제 제품과 대조해 인식합니다. 자유롭게 쓴 문장도 시도하되, 안 되면 "CPU: i5-14400F" 형식이 가장 정확합니다.</p>
            <div className="check-option">
              <div className="check-option-head">
                <span className="check-option-icon" aria-hidden="true">↑</span>
                <div><strong>파일에서 가져오기</strong><span>부품 목록 화면 캡처 또는 텍스트(예: GPU: RTX 4070 SUPER)</span></div>
              </div>
              <div className="dropzone">
                <p className="dropzone-title">{uploadedName ? `불러온 파일: ${uploadedName}` : '파일을 선택하세요'}</p>
                <p className="dropzone-sub">원본 이미지는 인식 후 저장하지 않습니다. PDF·문서 파일 인식은 아직 준비 중입니다.</p>
                <input ref={fileInputRef} type="file" accept={ACCEPT} onChange={onFileChange} style={{ display: 'none' }} />
                <button type="button" className="analyze-btn dropzone-btn" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
                  {uploading ? '확인하는 중...' : uploadedName ? '다른 파일 선택' : '파일 선택'}
                </button>
                <p className="dropzone-formats">PNG · JPG · WebP · TXT · CSV · MD · JSON · LOG · NFO · XML</p>
              </div>
            </div>
          </div>
          <div className="check-card">
            <div className="check-card-head"><h2>하고 싶은 일과 궁금한 점</h2></div>
            <p className="check-card-sub">사용 목적과 질문을 한 번에 적어주세요.</p>
            <label className="check-label" htmlFor="checkQuestion">PC 사용 목적·질문</label>
            <textarea id="checkQuestion" className="check-textarea" value={question} onChange={e => updateCheckDraft({ question: e.target.value })} />
            <p className="check-hint">추천에 꼭 필요한 정보가 부족하면 결과 화면의 대화에서 추가로 질문합니다.</p>
            <label className="check-label" htmlFor="checkBudget">업그레이드 또는 견적 최대 예산(선택)</label>
            <input id="checkBudget" className="check-input" value={budget} onChange={e => updateCheckDraft({ budget: e.target.value })} />
            <div className="check-footrow">
              <span>인식한 제품은 답변 전에 직접 확인하고 수정할 수 있습니다.</span>
              <button type="button" className="analyze-btn check-submit" onClick={() => navigate('/check/review')}>검토 시작 →</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
