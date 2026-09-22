import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePlan } from '../state/PlanContext'
import { useToast } from '../state/ToastContext'
import { api, errorMessage, isMockApi, type UpgradeSuggestion } from '../api'
import { wonFmt } from '../utils/format'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import type { CheckDraft } from '../state/types'

interface ChatBubble { id: string; role: 'bot' | 'user'; text: string }
interface SuggestResult { draft: CheckDraft; attempt: number; suggestion: UpgradeSuggestion | null; error: string }

function useReviewChat(topic: 'config' | 'answer', seedText: string) {
  const [messages, setMessages] = useState<ChatBubble[]>([{ id: 'seed', role: 'bot', text: seedText }])
  const [value, setValue] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  function addBubble(role: ChatBubble['role'], text: string) {
    setMessages(prev => [...prev, { id: Math.random().toString(36).slice(2), role, text }])
  }

  function send(text: string) {
    const clean = text.trim()
    if (!clean) return
    addBubble('user', clean)
    setValue('')
    api.chat.reviewReply({ topic, text: clean })
      .then(reply => { if (alive.current) addBubble('bot', reply.text) })
      .catch(error => { if (alive.current) addBubble('bot', errorMessage(error, '답변을 받지 못했습니다. 잠시 후 다시 시도해주세요.')) })
  }

  return { messages, value, setValue, send }
}

function ReviewMessages({ messages }: { messages: ChatBubble[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [messages])
  return <div className="review-chat-body" ref={ref}>{messages.map(m => <div key={m.id} className={'review-chat-bubble' + (m.role === 'user' ? ' user' : '')}>{m.text}</div>)}</div>
}

export function ReviewPage() {
  useDocumentTitle('견적 점검 결과')
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { startUpgradeMode, checkDraft, updateCheckDraft } = usePlan()
  const { question, budget, rows } = checkDraft
  const [step, setStep] = useState<'config' | 'answer'>('config')
  const [upgradeSelected, setUpgradeSelected] = useState(false)
  const [suggestTry, setSuggestTry] = useState(0)
  const [suggestResult, setSuggestResult] = useState<SuggestResult | null>(null)
  const [opening, setOpening] = useState(false)

  const configChat = useReviewChat('config', 'RAM 속도와 메인보드의 정확한 제조사 모델이 아직 모호합니다. 알고 있는 항목만 알려주세요.')
  const answerChat = useReviewChat('answer', '이 화면은 샘플 업그레이드 제안입니다. 입력 조건에 대한 실제 분석은 아직 연결되지 않았습니다.')

  useEffect(() => {
    if (step !== 'answer') return
    let active = true
    api.checks.suggestUpgrade(checkDraft)
      .then(suggestion => { if (active) setSuggestResult({ draft: checkDraft, attempt: suggestTry, suggestion, error: '' }) })
      .catch(error => { if (active) setSuggestResult({ draft: checkDraft, attempt: suggestTry, suggestion: null, error: errorMessage(error, '업그레이드 제안을 불러오지 못했습니다.') }) })
    return () => { active = false }
  }, [step, checkDraft, suggestTry])
  // 입력이 바뀌었거나 다시 시도한 뒤에는 이전 결과를 쓰지 않고 새 응답을 기다립니다.
  const latest = suggestResult && suggestResult.draft === checkDraft && suggestResult.attempt === suggestTry ? suggestResult : null
  const suggestion = latest?.suggestion ?? null
  const suggestError = latest?.error ?? ''

  function goToStep(next: 'config' | 'answer') {
    setStep(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function handleRowEdit(index: number) {
    const row = rows[index]
    const replacement = window.prompt(row.part + ' 정보를 수정하세요.', row.original)
    if (!replacement || !replacement.trim()) return
    const value = replacement.trim()
    setUpgradeSelected(false)
    try {
      // 실제 카탈로그와 다시 대조한다 — 백엔드에 대응 슬롯이 없는 항목(모니터 등)은 빈 배열로 온다.
      const [matched] = await api.checks.previewOwnedParts({ currentSpecs: { [row.part]: value } })
      updateCheckDraft({ rows: rows.map((r, i) => i === index ? {
        ...r, original: value, originalNote: '사용자 입력',
        matched: matched?.matched ?? value,
        matchedNote: matched?.matchedNote ?? '이 항목은 서버에서 확인하지 않습니다.',
        state: matched?.state ?? 'warn', stateLabel: matched?.stateLabel ?? '확인 필요',
      } : r) })
      showToast(row.part + ' 정보를 수정했습니다.')
    } catch (error) {
      showToast(errorMessage(error, '수정한 정보를 확인하지 못했습니다.'))
    }
  }

  function handleChooseUpgrade() {
    setUpgradeSelected(true)
    showToast('변경안을 선택했습니다.')
  }

  async function handleOpenPlanner() {
    setOpening(true)
    if (await startUpgradeMode()) navigate('/plan')
    else setOpening(false)
  }

  function submitConfigChat(e: FormEvent) {
    e.preventDefault()
    configChat.send(configChat.value)
  }

  function submitAnswerChat(e: FormEvent) {
    e.preventDefault()
    answerChat.send(answerChat.value)
  }

  return (
    <section className="pc-review" aria-labelledby="reviewTitle">
      <div className="review-shell">
        <div className="review-heading">
          <div>
            <p className="eyebrow">PC CHECK WORKSPACE</p>
            <h1 id="reviewTitle">가져온 PC 정보를 먼저 확인해주세요.</h1>
            <p>제품이 맞아야 호환성과 업그레이드 효과도 정확하게 계산됩니다.</p>
          </div>
          <button type="button" className="review-edit-btn" onClick={() => navigate('/check')}>← 입력 수정</button>
        </div>
        <p className="setup-hint" style={{ whiteSpace: 'pre-line' }}>질문: {question || '미입력'}<br />최대 예산: {budget || '미입력'}</p>
        <div className="review-tabs" role="tablist" aria-label="견적 점검 단계">
          <button type="button" className={'review-tab' + (step === 'config' ? ' active' : '')} role="tab" aria-selected={step === 'config'} onClick={() => goToStep('config')}>확인된 PC 구성</button>
          <button type="button" className={'review-tab' + (step === 'answer' ? ' active' : '')} role="tab" aria-selected={step === 'answer'} onClick={() => goToStep('answer')}>질문 답변 · 업그레이드 제안</button>
        </div>

        {step === 'config' && (
          <div className="review-layout">
            <section className="review-card">
              <div className="review-card-head"><div><h2>점검할 제품 (샘플)</h2><p>원문, 매칭한 제품과 부품 종류를 확인하세요.</p></div><span className="review-count">{rows.length}개 항목</span></div>
              <table className="review-parts"><tbody>
                {rows.map((r, i) => (
                  <tr key={r.part}>
                    <th>{r.part}</th>
                    <td><strong>{r.original}</strong><small>{r.originalNote}</small></td>
                    <td><strong>{r.matched}</strong><small>{r.matchedNote}</small></td>
                    <td className={'review-state' + (r.state === 'warn' ? ' warn' : '')}>{r.stateLabel}</td>
                    <td><button className="row-edit" type="button" onClick={() => handleRowEdit(i)}>수정</button></td>
                  </tr>
                ))}
              </tbody></table>
              <div className="review-card-foot"><span>모호한 항목은 추천 계산에 확정값으로 사용하지 않습니다.</span><button type="button" className="review-primary" onClick={() => goToStep('answer')}>구성 확인 완료 · 답변 보기 →</button></div>
            </section>
            <aside className="review-card review-chat">
              <div className="review-card-head"><div><h2>채팅으로 수정</h2><p>틀린 제품이나 빠진 부품을 말해주세요.</p></div></div>
              <div className="review-chat-note">예: "RAM은 6000MHz 16GB 두 개야" 또는 "파워 750W도 추가해줘"</div>
              <ReviewMessages messages={configChat.messages} />
              <form className="review-chat-form" onSubmit={submitConfigChat}>
                <input value={configChat.value} onChange={e => configChat.setValue(e.target.value)} placeholder="제품 정보 수정 또는 부품 추가" aria-label="제품 정보 수정" />
                <button type="submit">전송</button>
              </form>
            </aside>
          </div>
        )}

        {step === 'answer' && (
          <div className="review-layout">
            <main className="review-card answer-main">
              <section><span className="answer-label">사용자 질문</span><p className="answer-question" style={{ whiteSpace: 'pre-line' }}>{question || '질문이 입력되지 않았습니다.'}</p><p>최대 예산: {budget || '미입력'}</p></section>
              <section>
                <span className="answer-label mint">TRUEFIT ANSWER</span>
                <h2>{suggestion ? suggestion.part + ' ' : ''}업그레이드 {isMockApi ? '샘플을' : '후보를'} 확인하세요.</h2>
                <p className="answer-copy">{isMockApi ? '질문·예산·수정한 부품은 플래너에 전달됩니다. 아래 제품과 성능 수치는 고정된 예시이며 입력 조건에 맞춰 계산된 결과가 아닙니다.' : '질문·예산·수정한 부품은 플래너에 전달됩니다. 아래 후보는 입력한 조건으로 서버가 계산한 추천이며, 점검 표의 부품 정보는 직접 입력한 값을 그대로 씁니다.'}</p>
                <div className="answer-tags">{rows.map(row => <span key={row.part}>{row.part}: {row.matched}</span>)}</div>
                {suggestion ? (
                  <div className="upgrade-box">
                    <div className="upgrade-title"><strong>우선 검토할 업그레이드</strong><span>{suggestion.part} · 조건부 추천</span></div>
                    <div className="upgrade-compare">
                      <div className="upgrade-product"><small>현재 PC</small><strong>{rows.find(row => row.part === suggestion.part)?.matched || '미입력'}</strong><small>{suggestion.currentNote}</small></div>
                      <div className="upgrade-arrow">→</div>
                      <div className="upgrade-product recommended"><small>추천 후보</small><strong>{suggestion.productName}</strong><small>{suggestion.productNote}</small></div>
                    </div>
                    <div className="upgrade-metrics">{suggestion.performance && <div>QHD 게임 성능<strong>{suggestion.performance}</strong></div>}<div>예상 추가 비용<strong>+{wonFmt(suggestion.extraCost)}</strong></div>{suggestion.power && <div>예상 소비전력<strong>{suggestion.power}</strong></div>}</div>
                    <div className="upgrade-action">
                      <span>{suggestion.disclaimer}</span>
                      <button type="button" disabled={upgradeSelected} onClick={handleChooseUpgrade}>{upgradeSelected ? '선택됨 ✓' : '이 변경만 선택'}</button>
                    </div>
                  </div>
                ) : (
                  <p className="setup-hint" role="status">
                    {suggestError || '업그레이드 제안을 불러오는 중입니다...'}
                    {suggestError && <> <button type="button" className="inline-link" onClick={() => setSuggestTry(n => n + 1)}>다시 시도</button></>}
                  </p>
                )}
              </section>
              {suggestion && upgradeSelected && (
                <section className="selected-change" aria-live="polite">
                  <h3>선택한 변경안 요약</h3>
                  <div className="selected-change-grid">
                    <div><span>변경</span><strong>{rows.find(row => row.part === suggestion.part)?.matched || '미입력'} → {suggestion.productName}{isMockApi ? ' (샘플)' : ''}</strong></div>
                    <div><span>가격</span><strong>+{wonFmt(suggestion.extraCost)}</strong></div>
                    <div><span>예상 효과</span><strong>{suggestion.effectSummary}</strong></div>
                    <div><span>확인할 조건</span><strong>{suggestion.checkConditions}</strong></div>
                  </div>
                  <button type="button" className="open-planner-btn" disabled={opening} onClick={handleOpenPlanner}>이 변경으로 플래너 열기</button>
                </section>
              )}
            </main>
            <aside className="review-card review-chat">
              <div className="review-card-head"><div><h2>이 답변에 추가 질문</h2><p>확인된 PC 구성과 질문 문맥을 유지합니다.</p></div><span className="review-status">문맥 유지</span></div>
              <ReviewMessages messages={answerChat.messages} />
              <div className="review-chat-suggestions">
                <button type="button" onClick={() => answerChat.send('파워도 교체해야 해?')}>파워도 교체해야 해?</button>
                <button type="button" onClick={() => answerChat.send('더 저렴한 GPU는?')}>더 저렴한 GPU는?</button>
                <button type="button" onClick={() => answerChat.send('RAM은 언제 늘려?')}>RAM은 언제 늘려?</button>
              </div>
              <form className="review-chat-form" onSubmit={submitAnswerChat}>
                <input value={answerChat.value} onChange={e => answerChat.setValue(e.target.value)} placeholder="이 답변에 이어서 질문" aria-label="추가 질문" />
                <button type="submit">전송</button>
              </form>
            </aside>
          </div>
        )}
      </div>
    </section>
  )
}
