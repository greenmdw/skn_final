import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { ChatChoice, ChatMessage, CheckDraft, CurrentPlan, EditingSheet, PartKey, PlanState, SavedSetup, SetupPeripheral } from './types'
import { createCheckDraft } from '../data/checkDraftSeed'
import { parseBudget, planTotal } from './planModel'
import { api, ApiError, errorMessage, SESSION_GONE, type ChatTopic } from '../api'
import { onLogout } from './authStore'
import type { ConditionTurnResult, ItemPatch, LoadedConversation } from '../api/types'
import { readWorkspace, WORKSPACE_KEY } from './storage'
import { wonFmt } from '../utils/format'
import { newId } from '../utils/id'
import { useToast } from './ToastContext'
import { PlanContext, type PlanContextValue } from './PlanContext'
import { useAuthUser } from './authStore'

const INITIAL_GREETING = '안녕하세요! TrueFit입니다.\n어떤 PC가 필요하신가요?\n\n하고 싶은 일과 원하는 성능을 말씀해주세요.'
const initialState: PlanState = {
  stage: 0, mode: 'new', intent: '', performance: '', quiet: '', budget: 2500000,
  currentPlan: null, checkSnapshot: null, selectedPart: 'cpu',
  sessionId: null, fields: [], canRecommend: false, budgetWarning: null,
  deskUnlocked: false, deskWidth: 1400, deskDepth: 700, deskHeight: 740, editingSheet: null, viewOnly: false, peripherals: [],
}
// 서버의 해상도 필드 → 화면 문구. 사용자가 안 정해서 서버가 기본값으로 가정한 값이면 "(기본값)"을 붙인다.
function resolutionText(field: { display: string | null; status: string } | undefined): string | null {
  if (!field?.display) return null
  return field.status === 'assumed' ? field.display + ' (기본값)' : field.display
}
function makeMessage(role: ChatMessage['role'], text: string, choices?: ChatChoice[], tag?: ChatMessage['tag']): ChatMessage {
  return { id: newId(), role, text, choices, tag }
}
// 조건 세션 한 턴(또는 서버에서 읽은 대화)의 값을 화면 상태에 반영한다. GoalPanel의 세 카드(주요 용도·성능 목표·소음 선호)는
// 그대로 두고, 값만 서버가 뽑은 필드로 채운다.
function applyTurn(prev: PlanState, turn: ConditionTurnResult): PlanState {
  const fieldValue = (key: string) => turn.fields.find(f => f.key === key)
  const budgetField = fieldValue('budget_max')
  return {
    ...prev, sessionId: turn.sessionId, fields: turn.fields, canRecommend: turn.canRecommend, budgetWarning: turn.budgetWarning ?? null,
    budget: typeof budgetField?.value === 'number' ? budgetField.value : prev.budget,
    intent: fieldValue('purpose')?.display ?? prev.intent,
    performance: resolutionText(fieldValue('resolution')) ?? prev.performance,
    quiet: fieldValue('priority')?.display ?? prev.quiet,
    stage: prev.stage === 0 ? 1 : prev.stage,
  }
}
// 서버에 저장된 대화 → 말풍선. 칩은 저장되지 않아서, 아직 조건을 정하는 중이면 마지막 질문의 선택지만 다시 붙인다.
function chatFromLoaded(loaded: LoadedConversation, withChoices: boolean): ChatMessage[] {
  const chat = loaded.messages.map(m => makeMessage(m.role, m.text))
  const last = chat[chat.length - 1]
  if (withChoices && last?.role === 'bot' && loaded.turn.choices?.length) last.choices = loaded.turn.choices
  return chat.length ? chat : [makeMessage('bot', INITIAL_GREETING)]
}
export function PlanProvider({ children }: { children: ReactNode }) {
  const { showToast } = useToast()
  const [restored] = useState(readWorkspace)
  // 예전에 저장된 작업(sessionId·fields·canRecommend가 없던 버전)을 복원해도 기본값으로 채워지게 initialState와 합친다.
  const [state, setState] = useState<PlanState>(restored?.state ? { ...initialState, ...restored.state } : initialState)
  const [checkDraft, setCheckDraft] = useState<CheckDraft>(restored?.checkDraft ?? createCheckDraft())
  const [messages, setMessages] = useState<ChatMessage[]>(() => [makeMessage('bot', restored?.state.stage ? '작성 중인 구성을 복원했습니다. 입력한 조건을 확인하고 이어서 진행하세요.' : INITIAL_GREETING)])
  const [busy, setBusy] = useState(false)
  const [analyzingIndex, setAnalyzingIndex] = useState(0)
  const [customHeading, setCustomHeading] = useState<{ title: string; desc: string } | null>(null)
  // 작업을 비운 횟수. 이미 빈 화면(stage 0)에서 "새 견적"을 눌러도 지난 조건 제안을 다시 띄우는 데 쓴다 —
  // stage 가 0 그대로라 stage 만 보면 비웠다는 걸 알 수 없다(비우면서 제안 말풍선도 지워진다).
  const [resetCount, setResetCount] = useState(0)
  const stateRef = useRef(state)
  const timers = useRef(new Set<number>())
  // 취소할 때마다 올려서, 이미 요청한 API 응답이 뒤늦게 도착해도 무시합니다.
  const epoch = useRef(0)
  const storageWarned = useRef(false)
  const updateState = useCallback((update: (previous: PlanState) => PlanState) => {
    const next = update(stateRef.current)
    stateRef.current = next
    setState(next)
  }, [])
  const clearTimers = useCallback(() => {
    timers.current.forEach(id => window.clearTimeout(id))
    timers.current.clear()
  }, [])
  const cancelPending = useCallback(() => {
    clearTimers()
    epoch.current++
  }, [clearTimers])
  const later = useCallback((callback: () => void, delay: number) => {
    const id = window.setTimeout(() => { timers.current.delete(id); callback() }, delay)
    timers.current.add(id)
  }, [])
  useEffect(() => cancelPending, [cancelPending])
  useEffect(() => {
    try {
      localStorage.setItem(WORKSPACE_KEY, JSON.stringify({ state, checkDraft }))
      storageWarned.current = false
    } catch {
      if (!storageWarned.current) showToast('임시 작업을 저장하지 못했습니다. 새로고침하면 최근 변경이 사라질 수 있습니다.')
      storageWarned.current = true
    }
  }, [state, checkDraft, showToast])
  const updateCheckDraft = useCallback((patch: Partial<CheckDraft>) => setCheckDraft(prev => ({ ...prev, ...patch })), [])
  const addMessage = useCallback((role: ChatMessage['role'], text: string, choices?: ChatChoice[]) => {
    setMessages(prev => [...prev, makeMessage(role, text, choices)])
  }, [])

  // 브라우저에 남아 있던 작업의 서버 세션이 없어졌거나 내 것이 아니면(로그아웃 · 다른 계정 · 삭제) 작업을 비우고 새로 시작한다.
  const dropStaleSession = useCallback((notice: string) => {
    cancelPending()
    updateState(() => ({ ...initialState }))
    setCheckDraft(createCheckDraft())
    setMessages([makeMessage('bot', INITIAL_GREETING), makeMessage('bot', notice)])
    setAnalyzingIndex(0)
    setCustomHeading(null)
    setBusy(false)
    setResetCount(n => n + 1)
  }, [cancelPending, updateState])
  // 화면을 열 때 저장된 세션이 아직 유효한지 서버에 물어본다. 알 수 없으면(네트워크 오류) 그대로 둔다.
  // 새로고침으로 브라우저에 남은 작업만 복원한 직후라면(말풍선이 복원 안내 하나뿐) 서버의 대화 기록으로 말풍선을 되살린다
  // — 대화는 브라우저에 저장하지 않고 서버(identity.message)에만 있다.
  const hydrated = useRef(!restored?.state.stage)
  const checkSession = useCallback(() => {
    const id = stateRef.current.sessionId
    if (!id) return
    const mine = epoch.current
    api.conditions.load(id).then(loaded => {
      if (hydrated.current || mine !== epoch.current || stateRef.current.sessionId !== id) return
      hydrated.current = true
      setMessages(chatFromLoaded(loaded, stateRef.current.stage <= 2))
    }).catch(error => {
      if (error instanceof ApiError && error.code === SESSION_GONE && stateRef.current.sessionId === id) dropStaleSession(error.message)
    })
  }, [dropStaleSession])
  useEffect(() => onLogout(() => dropStaleSession('로그아웃해서 작업 중이던 구성을 비웠어요. 새로 시작해 주세요.')), [dropStaleSession])

  // 실서버 인터뷰 한 턴: 조건 세션(에이전트가 있으면 LLM, 없으면 규칙)이 자유 문장에서 예산·용도·우선순위 등을
  // 뽑아 돌려준다. 뽑힌 값(특히 예산)을 그 자리에서 state에 반영해야 GoalPanel이 바로 바뀐다 — 화면이 직접
  // 정규식으로 다시 해석하지 않는다(그러면 서버 판정과 화면 표시가 어긋날 수 있다).
  const runConditionTurn = useCallback((call: () => Promise<ConditionTurnResult>) => {
    const mine = epoch.current
    setBusy(true)
    call()
      .then(turn => {
        if (mine !== epoch.current) return
        updateState(prev => applyTurn(prev, turn))
        addMessage('bot', turn.reply || '조건을 반영했어요.', turn.choices)
      })
      .catch(error => {
        if (mine !== epoch.current) return
        if (error instanceof ApiError && error.code === SESSION_GONE) dropStaleSession(error.message)
        else addMessage('bot', errorMessage(error, '답변을 반영하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      })
      .finally(() => { if (mine === epoch.current) setBusy(false) })
  }, [addMessage, updateState, dropStaleSession])
  const sendConditionTurn = useCallback((text: string) => {
    runConditionTurn(() => api.conditions.send(stateRef.current.sessionId, text))
  }, [runConditionTurn])
  const sendConditionAnswer = useCallback((sessionId: string, questionId: string, value: string) => {
    runConditionTurn(() => api.conditions.answer(sessionId, questionId, [value]))
  }, [runConditionTurn])
  // 새로 시작할 때 같은 사용자의 지난 목록이 있으면 그 조건으로 이어갈지 묻는다(A1). 값은 "이어서 하기"를 눌러야
  // 서버가 복사한다 — 묻기만 하고 자동으로 채우지 않는다. 조회가 실패해도 인사말만 남고 조용히 넘어간다.
  // 가장 나중에 보낸 조회의 답만 쓰고, 앞서 붙인 제안(다른 사용자로 물었던 것)은 지운다.
  const offerSeq = useRef(0)
  const offerPrevious = useCallback(() => {
    const mine = epoch.current
    const seq = ++offerSeq.current
    api.conditions.previous()
      .then(({ previous, preferenceHint: hint }) => {
        if (seq !== offerSeq.current || mine !== epoch.current || stateRef.current.stage !== 0) return
        setMessages(prev => {
          const kept = prev.filter(m => m.tag !== 'offer' && !m.choices?.some(c => c.resumeFrom || c.preferenceHint))
          const offers: ChatMessage[] = []
          if (previous) offers.push(makeMessage('bot', previous.summary, [
            { label: '이어서 하기', value: 'resume', resumeFrom: previous.listId },
            { label: '새로 시작', value: 'fresh', startFresh: true },
          ], 'offer'))
          // 선호 되묻기(B4): 반복 행동에서 추론한 것이라 자동으로 적용하지 않고, "예"를 눌러야 이번 견적에 담긴다.
          // 담기지 않는 신호(actionable=false)는 묻지 않고 알려 주기만 한다.
          if (hint) offers.push(makeMessage('bot', hint.summary, hint.actionable ? [
            { label: '예, 반영해 주세요', value: 'hint-yes', preferenceHint: { signalId: hint.id, accepted: true } },
            { label: '아니요', value: 'hint-no', preferenceHint: { signalId: hint.id, accepted: false } },
          ] : undefined, 'offer'))
          return [...kept, ...offers]
        })
      })
      .catch(() => {})
  }, [])
  // 작업이 비어 있을 때(stage 0)만 묻고, 사용자가 바뀌거나(로그인·로그아웃은 페이지를 새로 읽지 않는다) 작업이
  // 다시 비워지면(새 설계·로그아웃·세션 소실로 dropStaleSession) 다시 묻는다. 앱을 연 순간 한 번만 물으면 로그인한
  // 사용자의 지난 견적을 놓친다. 같은 사용자·같은 빈 작업으로는 한 번만(StrictMode 는 effect 를 두 번 돌린다).
  const authUser = useAuthUser()
  const idle = state.stage === 0
  const offeredFor = useRef<string | null>(null)
  useEffect(() => {
    if (!idle) { offeredFor.current = null; return }
    const who = (authUser?.email ?? '') + '#' + resetCount
    if (offeredFor.current === who) return
    offeredFor.current = who
    offerPrevious()
  }, [authUser, idle, resetCount, offerPrevious])

  const handleInput = useCallback((text: string) => {
    const clean = text.trim()
    if (!clean) return
    addMessage('user', clean)
    const current = stateRef.current
    const askApi = (topic: ChatTopic) => {
      const mine = epoch.current
      api.chat.reply({ topic, text: clean, selectedPart: current.selectedPart, plan: current.currentPlan })
        .then(reply => {
          if (mine !== epoch.current) return
          // 후속 질문으로 부품이 바뀌었으면 그 구성으로 화면을 바꾼다(예산은 화면에서 고친 값을 그대로 둔다)
          if (reply.plan) updateState(prev => ({ ...prev, currentPlan: { ...reply.plan!, budget: prev.currentPlan?.budget ?? reply.plan!.budget } }))
          addMessage('bot', reply.text, reply.choices)
        })
        .catch(error => { if (mine === epoch.current) addMessage('bot', errorMessage(error, '답변을 받지 못했습니다. 잠시 후 다시 시도해주세요.')) })
    }
    if (current.stage <= 2) {
      sendConditionTurn(clean)
    } else if (current.stage === 3) {
      addMessage('bot', '구성을 만드는 중입니다. 완료 후 이어서 질문해주세요.')
    } else askApi('followup')
  }, [addMessage, updateState, sendConditionTurn])
  // 선택지(칩)를 누르면: 서버 질문의 선택지는 화면에 라벨("가성비")을 내 말로 보여 주고, 내부 값("value")은 구조화된 답변으로
  // 보낸다 — 예전에는 값 문자열을 그대로 말풍선에 띄우고 자유 문장으로 보내서 "value" 가 보였다.
  const handleChoice = useCallback((choice: ChatChoice) => {
    const sessionId = stateRef.current.sessionId
    if (choice.resumeFrom) {
      addMessage('user', choice.label)
      const from = choice.resumeFrom
      runConditionTurn(() => api.conditions.resume(stateRef.current.sessionId, from))
      return
    }
    if (choice.preferenceHint) {
      addMessage('user', choice.label)
      const { signalId, accepted } = choice.preferenceHint
      // 답한 뒤에는 칩을 지워 같은 질문에 두 번 답하지 않게 한다.
      setMessages(prev => prev.map(m => (m.choices?.some(c => c.preferenceHint) ? { ...m, choices: undefined } : m)))
      api.conditions.respondPreferenceHint(stateRef.current.sessionId, signalId, accepted)
        .then(({ sessionId: id }) => {
          updateState(prev => ({ ...prev, sessionId: prev.sessionId ?? id }))
          addMessage('bot', accepted ? '알겠어요. 이번 견적에 반영할게요. 하고 싶은 일과 원하는 성능을 말씀해주세요.' : '알겠어요. 이번에는 반영하지 않을게요. 하고 싶은 일과 원하는 성능을 말씀해주세요.')
        })
        .catch(error => addMessage('bot', errorMessage(error, '응답을 저장하지 못했어요. 잠시 후 다시 시도해주세요.')))
      return
    }
    if (choice.startFresh) {
      addMessage('user', choice.label)
      addMessage('bot', '좋아요, 새로 시작할게요. 하고 싶은 일과 원하는 성능을 말씀해주세요.')
      return
    }
    if (choice.questionId && sessionId && stateRef.current.stage <= 2) {
      addMessage('user', choice.label)
      sendConditionAnswer(sessionId, choice.questionId, choice.value)
      return
    }
    handleInput(choice.value)
  }, [addMessage, sendConditionAnswer, handleInput, runConditionTurn, updateState])
  // 현재 조건(예산 포함)으로 서버 추천을 새로 받는다. 처음 시작할 때와, 구성이 나온 뒤 예산을 바꿨을 때 같이 쓴다.
  const runAnalysis = useCallback((intro: string) => {
    const current = stateRef.current
    cancelPending()
    const mine = epoch.current
    updateState(prev => ({ ...prev, stage: 3, currentPlan: null }))
    setAnalyzingIndex(0)
    addMessage('bot', intro)
    // 진행 표시는 화면에서 시간에 맞춰 넘기고, 구성은 API 응답이 오면 바로 보여줍니다.
    for (let index = 1; index <= 3; index++) later(() => setAnalyzingIndex(index), index * 650)
    api.plans.recommend({
      mode: current.mode, budget: current.budget, checkSnapshot: current.checkSnapshot,
      conditions: { intent: current.intent, performance: current.performance, quiet: current.quiet },
      sessionId: current.sessionId,
    }).then(plan => {
      if (mine !== epoch.current) return
      clearTimers()
      updateState(prev => ({ ...prev, stage: 4, currentPlan: plan }))
      addMessage('bot', '구성이 준비됐어요. 부품과 예산을 확인한 뒤 리스트를 확정할 수 있습니다.')
    }).catch(error => {
      if (mine !== epoch.current) return
      clearTimers()
      if (error instanceof ApiError && error.code === SESSION_GONE) { dropStaleSession(error.message); return }
      updateState(prev => ({ ...prev, stage: 2, currentPlan: null }))
      addMessage('bot', errorMessage(error, '구성을 만들지 못했습니다.') + ' 조건을 확인한 뒤 AI 구성 분석 시작 버튼을 다시 눌러주세요.')
    })
  }, [cancelPending, clearTimers, later, addMessage, updateState, dropStaleSession])
  const startAnalysis = useCallback(() => {
    const current = stateRef.current
    // 실서버는 세션이 판정한 can_recommend를 그대로 따른다 — 한 문장에 조건이 다 담겨 있으면 1턴만에 열릴 수 있다.
    const ready = current.canRecommend
    if (!ready) return
    runAnalysis('입력한 조건으로 부품 후보와 가격, 호환성을 분석합니다. 잠시만 기다려주세요.')
  }, [runAnalysis])
  // 결과 화면의 "성능 우선으로 다시 추천받기" — 우선순위만 세션에 바꿔 두고 같은 조건으로 다시 계산한다.
  const retryWithPerformance = useCallback(() => {
    const current = stateRef.current
    if (!current.sessionId || current.mode !== 'new') return
    api.conditions.patch(current.sessionId, 'priority', 'performance').then(turn => {
      updateState(prev => ({ ...prev, fields: turn.fields, canRecommend: turn.canRecommend, budgetWarning: turn.budgetWarning ?? null,
        quiet: turn.fields.find(f => f.key === 'priority')?.display ?? '성능 우선' }))
      runAnalysis('성능 우선으로 바꿔서 남은 예산까지 활용해 구성을 다시 계산합니다.')
    }).catch(error => showToast(errorMessage(error, '우선순위를 바꾸지 못했습니다. 잠시 후 다시 시도해주세요.')))
  }, [updateState, runAnalysis, showToast])
  const refreshPlan = useCallback(() => {
    const plan = stateRef.current.currentPlan
    if (!plan) return
    api.plans.refresh(plan)
      .then(next => updateState(prev => (prev.currentPlan?.id === next.id ? { ...prev, currentPlan: { ...next, budget: prev.currentPlan.budget } } : prev)))
      .catch(() => {})
  }, [updateState])
  // 서버가 돌려준 새 구성으로 화면을 바꾼다. 예산은 화면에서 정한 값을 그대로 둔다.
  const applyPlan = useCallback((next: CurrentPlan) => {
    updateState(prev => (prev.currentPlan?.id === next.id ? { ...prev, currentPlan: { ...next, budget: prev.currentPlan.budget } } : prev))
  }, [updateState])
  const loadAlternatives = useCallback((itemId: string) => {
    const plan = stateRef.current.currentPlan
    return plan ? api.plans.alternatives(plan, itemId) : Promise.resolve([])
  }, [])
  const swapItem = useCallback(async (itemId: string, candidateId: string) => {
    const plan = stateRef.current.currentPlan
    if (!plan) return false
    const before = plan.items.find(item => item.id === itemId)
    try {
      const next = await api.plans.swap(plan, itemId, candidateId)
      applyPlan(next)
      const after = next.items.find(item => item.id === itemId)
      if (before && after) addMessage('bot', `${before.type}를 ${after.name}(으)로 바꿨어요. 가격과 예산, 호환 검사를 다시 계산했어요.`)
      return true
    } catch (error) {
      showToast(errorMessage(error, '부품을 바꾸지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
  }, [applyPlan, addMessage, showToast])
  const updateItem = useCallback(async (itemId: string, patch: ItemPatch) => {
    const plan = stateRef.current.currentPlan
    if (!plan) return false
    try {
      applyPlan(await api.plans.updateItem(plan, itemId, patch))
      return true
    } catch (error) {
      showToast(errorMessage(error, '변경하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
  }, [applyPlan, showToast])
  const selectPart = useCallback((key: PartKey) => updateState(prev => ({ ...prev, selectedPart: key })), [updateState])
  const setBudget = useCallback((budget: number | null) => {
    if (budget !== null && (!Number.isSafeInteger(budget) || budget < 1 || budget > 100000000)) return
    const before = stateRef.current
    updateState(prev => ({ ...prev, budget, currentPlan: prev.currentPlan ? { ...prev.currentPlan, budget } : null }))
    // 예산창에서 직접 고친 값도 조건 세션에 바로 반영해 둔다 — 채팅으로 말한 값과 예산창 값이 다를 때, 다음 대화
    // 턴과 최종 추천이 같은(가장 최근에 정한) 값을 보게 한다. 실패해도 화면 값은 이미 바뀌었고, 추천 시점에 다시 맞춘다.
    if (before.sessionId) {
      api.conditions.patch(before.sessionId, 'budget_max', budget)
        .then(turn => updateState(prev => ({ ...prev, fields: turn.fields, canRecommend: turn.canRecommend, budgetWarning: turn.budgetWarning ?? null })))
        .catch(() => {})
    }
    // 서버는 조건이 바뀌면 그 추천을 낡은 것으로 보고 확정을 거절한다(stale_recommendation). 그래서 서버 추천이 나온 뒤에
    // 예산을 바꾸면 새 예산으로 다시 추천받는다 — 직접 바꾼 부품은 새 구성으로 초기화된다. 목업은 서버가 없어 화면 값만 바꾼다.
    if (before.stage === 4 && before.currentPlan && budget !== before.budget) {
      runAnalysis('예산을 바꿔서 새 예산으로 구성을 다시 계산합니다. 직접 바꾼 부품은 새 구성으로 초기화돼요.')
    }
  }, [updateState, runAnalysis])
  const setDesk = useCallback((width: number, depth: number, height: number) => {
    if (![width, depth, height].every(Number.isFinite) || width < 800 || width > 3000 || depth < 400 || depth > 1500 || height < 500 || height > 1300) return false
    updateState(prev => ({ ...prev, deskWidth: width, deskDepth: depth, deskHeight: height, deskUnlocked: true }))
    showToast('책상 치수를 반영했습니다. 리스트 확정 시 구성과 함께 저장됩니다.')
    return true
  }, [showToast, updateState])
  // 패널 "대화 내역"에서 지난 대화를 연다: 서버의 대화·조건을 읽고, 추천 결과가 있으면 그 구성까지 되살린다.
  // 돌려주는 값은 열린 화면 — 'plan'(추천 결과) · 'conditions'(조건 대화) · null(실패, 안내는 토스트로).
  const openConversation = useCallback(async (listId: string, hasResult: boolean, viewOnly = false): Promise<'plan' | 'conditions' | null> => {
    cancelPending()
    const mine = epoch.current
    try {
      const loaded = await api.conditions.load(listId)
      const base = applyTurn({ ...initialState }, loaded.turn)
      const plan = hasResult
        ? await api.plans.load(listId, { mode: 'new', budget: base.budget,
          conditions: { intent: base.intent, performance: base.performance, quiet: base.quiet }, checkSnapshot: null }).catch(() => null)
        : null
      if (mine !== epoch.current) return null
      updateState(() => ({ ...base, currentPlan: plan, stage: plan ? 4 : 1, viewOnly: viewOnly && !!plan,
        selectedPart: plan?.items.find(p => p.key)?.key ?? 'cpu' }))
      setCheckDraft(createCheckDraft())
      setMessages(chatFromLoaded(loaded, !plan))
      setAnalyzingIndex(0)
      setCustomHeading(null)
      setBusy(false)
      hydrated.current = true
      return plan ? 'plan' : 'conditions'
    } catch (error) {
      if (mine === epoch.current) showToast(errorMessage(error, '대화를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return null
    }
  }, [cancelPending, updateState, showToast])
  // 리포트의 "견적 수정하기": 서버가 확정본의 부품 구성까지 복사한 새 견적서(같은 대화)를 만들어 주면, 그 구성과 이전 채팅 내역을
  // 그대로 열어 추천 결과 화면에서 수정한다. 돌려주는 값은 열린 화면 — 'plan' · 'conditions' · null.
  const reviseSetup = useCallback(async (listId: string, from: EditingSheet): Promise<'plan' | 'conditions' | null> => {
    try {
      await api.setups.newRevision(listId, from.revisionNo)
    } catch (error) {
      showToast(errorMessage(error, '새 견적서를 시작하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return null
    }
    // 저장된 구성을 못 읽으면 조건 대화로 간다 — 조건으로 다시 추천을 돌리지는 않는다(저장 전 구성이 달라지므로).
    const screen = await openConversation(listId, true)
    // 원본 견적서를 기억해 둔다 — 장바구니에서 덮어쓸지 새 견적서로 저장할지 묻는 데 쓴다.
    if (screen) updateState(prev => ({ ...prev, editingSheet: from }))
    return screen
  }, [openConversation, showToast, updateState])
  // sessionId 는 본체 견적 없이 주변기기만 담을 때 넘긴다(그 목록으로 확정). 비우면(빈 배열) 같이 지운다.
  const setPeripherals = useCallback((peripherals: SetupPeripheral[], sessionId?: string | null) => updateState(prev => ({
    ...prev, peripherals, peripheralSessionId: peripherals.length ? (sessionId ?? prev.peripheralSessionId ?? null) : null,
  })), [updateState])
  // 결과가 나온 뒤(stage 4)에는 채팅 입력이 "부품 교체" 후속 질문으로 간다 — "조건 바꾸기"로 /start 에 들어와도 단계가 그대로라
  // "우선순위 성능으로 바꿔줘"가 조건을 못 바꿨다. 단계를 조건 입력(2)으로 되돌려 채팅이 조건 대화로 가게 한다.
  // 이미 나온 구성은 지우지 않는다(추천 받기를 다시 누르면 새 조건으로 계산해 바뀐다).
  const reopenConditions = useCallback(() => {
    const current = stateRef.current
    if (current.viewOnly || current.stage !== 4 || !current.sessionId) return
    updateState(prev => ({ ...prev, stage: 2 }))
    addMessage('bot', '바꾸고 싶은 조건을 말씀해 주세요. 예: "우선순위를 성능으로 바꿔줘", "예산 200만원으로". 다 바꿨으면 오른쪽의 \'추천 받기\'를 눌러 주세요.')
  }, [addMessage, updateState])
  const showResults = useCallback(() => {
    updateState(prev => (prev.stage === 2 && prev.currentPlan && !prev.viewOnly ? { ...prev, stage: 4 } : prev))
  }, [updateState])
  const clearEditingSheet = useCallback(() => updateState(prev => (prev.editingSheet ? { ...prev, editingSheet: null } : prev)), [updateState])
  const resetPlan = useCallback(() => {
    cancelPending()
    updateState(() => ({ ...initialState }))
    setCheckDraft(createCheckDraft())
    setMessages([makeMessage('bot', INITIAL_GREETING)])
    setAnalyzingIndex(0)
    setCustomHeading(null)
    setResetCount(n => n + 1)
    showToast('새로운 설계를 시작합니다.')
  }, [cancelPending, updateState, showToast])
  const loadFromSavedSetup = useCallback((setup: SavedSetup) => {
    cancelPending()
    const plan = structuredClone(setup.plan)
    updateState(() => ({ ...initialState, ...plan.conditions, ...setup.desk, currentPlan: plan,
      mode: plan.mode, budget: plan.budget, checkSnapshot: plan.checkSnapshot,
      selectedPart: plan.items.find(p => p.key)?.key ?? 'cpu', stage: 4 }))
    setCheckDraft(structuredClone(setup.checkDraft))
    setMessages([makeMessage('bot', setup.title + ' 구성을 복원했습니다.\n총 ' + wonFmt(planTotal(plan)))])
    setCustomHeading({ title: setup.title, desc: '확정한 구성' })
    showToast('저장한 구성을 불러왔습니다.')
  }, [cancelPending, updateState, showToast])
  const loadCheckedQuote = useCallback((plan: CurrentPlan, draft: CheckDraft) => {
    cancelPending()
    const nextPlan = structuredClone(plan)
    const nextDraft = structuredClone(draft)
    updateState(prev => ({ ...prev, currentPlan: nextPlan, mode: nextPlan.mode, budget: nextPlan.budget,
      intent: nextPlan.conditions.intent, performance: nextPlan.conditions.performance, quiet: nextPlan.conditions.quiet,
      checkSnapshot: nextDraft, selectedPart: nextPlan.items.find(item => item.key)?.key ?? 'cpu', stage: 4 }))
    setCheckDraft(nextDraft)
    setMessages([makeMessage('bot', `받은 견적 점검 결과를 장바구니에 담았습니다.\n총 ${wonFmt(planTotal(nextPlan))}`)])
    setCustomHeading({ title: '받은 견적 점검', desc: '확인한 구성' })
  }, [cancelPending, updateState])
  // draft 를 주면 그 점검 초안으로 시작한다(받은 견적 점검 화면에서 바로 넘어올 때 — 상태 반영을 기다리지 않는다).
  const startUpgradeMode = useCallback(async (draft?: CheckDraft) => {
    const source = draft ?? checkDraft
    const budget = parseBudget(source.budget)
    if (budget === undefined) { showToast('예산을 원 단위 숫자로 입력해주세요. 예: 800,000원'); return false }
    cancelPending()
    const mine = epoch.current
    const snapshot = structuredClone(source)
    try {
      const plan = await api.plans.recommend({
        mode: 'upgrade', budget, checkSnapshot: snapshot,
        conditions: { intent: snapshot.question, performance: '', quiet: '' },
      })
      if (mine !== epoch.current) return false
      updateState(prev => ({ ...prev, mode: 'upgrade', selectedPart: plan.items.find(p => p.key)?.key ?? 'gpu', stage: 4, budget,
        intent: snapshot.question, performance: '', quiet: '', checkSnapshot: snapshot, currentPlan: plan }))
      setMessages([makeMessage('user', snapshot.question), makeMessage('bot', '입력한 질문·예산·부품을 가져왔습니다. 입력하지 않은 유지 부품 정보는 확인하지 못한 채 추천하니, 구매 전에 호환성을 다시 확인해주세요.')])
      setCustomHeading(null)
      return true
    } catch (error) {
      if (mine === epoch.current) showToast(errorMessage(error, '업그레이드 구성을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
  }, [checkDraft, cancelPending, updateState, showToast])
  const value = useMemo<PlanContextValue>(() => ({
    state, checkDraft, updateCheckDraft, messages, busy, starterHidden: state.stage > 0, analyzingIndex, customHeading,
    handleInput, handleChoice, startAnalysis, retryWithPerformance, refreshPlan, checkSession, loadAlternatives, swapItem, updateItem, selectPart, setBudget, setDesk, resetPlan, loadFromSavedSetup, loadCheckedQuote, startUpgradeMode, setPeripherals,
    openConversation, reviseSetup, clearEditingSheet, reopenConditions, showResults,
  }), [state, checkDraft, updateCheckDraft, messages, busy, analyzingIndex, customHeading,
    handleInput, handleChoice, startAnalysis, retryWithPerformance, refreshPlan, checkSession, loadAlternatives, swapItem, updateItem, selectPart, setBudget, setDesk, resetPlan, loadFromSavedSetup, loadCheckedQuote, startUpgradeMode, setPeripherals,
    openConversation, reviseSetup, clearEditingSheet, reopenConditions, showResults])
  return <PlanContext.Provider value={value}>{children}</PlanContext.Provider>
}
