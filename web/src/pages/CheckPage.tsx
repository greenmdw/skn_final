import { usePlan } from '../state/PlanContext'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../state/ToastContext'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function CheckPage() {
  useDocumentTitle('내 PC·견적 점검')
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { checkDraft, updateCheckDraft } = usePlan()
  const { question, budget } = checkDraft

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
            <p className="check-card-sub">견적서나 부품 목록 파일을 업로드하면 자동으로 인식합니다.</p>
            <div className="check-option">
              <div className="check-option-head">
                <span className="check-option-icon" aria-hidden="true">↑</span>
                <div><strong>파일에서 가져오기</strong><span>부품 목록, 견적서, 주문 내역 또는 시스템 보고서</span></div>
              </div>
              <div className="dropzone">
                <p className="dropzone-title">파일을 끌어 놓거나 선택하세요</p>
                <p className="dropzone-sub">여러 형식의 문서와 화면 캡처를 함께 분석합니다.</p>
                <button type="button" className="analyze-btn dropzone-btn" onClick={() => showToast('이 목업에서는 실제 파일 업로드가 동작하지 않습니다.')}>파일 선택</button>
                <p className="dropzone-formats">JPG · PNG · WebP · PDF · DOCX · XLSX · CSV</p>
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
