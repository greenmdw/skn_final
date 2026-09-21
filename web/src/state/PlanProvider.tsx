import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { ChatChoice, ChatMessage, CheckDraft, PartKey, PlanState, SavedSetup } from './types'
import { createCheckDraft } from '../data/checkDraftSeed'
import { parseBudget, planTotal } from './planModel'
import { api, errorMessage, isMockApi, type ChatTopic } from '../api'
import { readWorkspace, WORKSPACE_KEY } from './storage'
import { wonFmt } from '../utils/format'
import { newId } from '../utils/id'
import { useToast } from './ToastContext'
import { PlanContext, type PlanContextValue } from './PlanContext'

const INITIAL_GREETING = '안녕하세요! TrueFit입니다.\n어떤 PC가 필요하신가요?\n\n하고 싶은 일과 원하는 성능을 말씀해주세요.' + (isMockApi ? ' 현재 추천은 샘플 데이터로 제공됩니다.' : '')
const initialState: PlanState = {
  stage: 0, mode: 'new', intent: '', performance: '', quiet: '', budget: 2500000,
  currentPlan: null, checkSnapshot: null, selectedPart: 'cpu',
  deskUnlocked: false, deskWidth: 1400, deskDepth: 700, deskHeight: 740,
}
function makeMessage(role: ChatMessage['role'], text: string, choices?: ChatChoice[]): ChatMessage {
  return { id: newId(), role, text, choices }
}
export function PlanProvider({ children }: { children: ReactNode }) {
  const { showToast } = useToast()
  const [restored] = useState(readWorkspace)
  const [state, setState] = useState<PlanState>(restored?.state ?? initialState)
  const [checkDraft, setCheckDraft] = useState<CheckDraft>(restored?.checkDraft ?? createCheckDraft())
  const [messages, setMessages] = useState<ChatMessage[]>(() => [makeMessage('bot', restored?.state.stage ? '작성 중인 구성을 복원했습니다. 입력한 조건을 확인하고 이어서 진행하세요.' : INITIAL_GREETING)])
  const [analyzingIndex, setAnalyzingIndex] = useState(0)
  const [customHeading, setCustomHeading] = useState<{ title: string; desc: string } | null>(null)
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
    if (current.stage === 0) {
      updateState(prev => ({ ...prev, intent: clean, stage: 1 }))
      askApi('intent')
    } else if (current.stage === 1) {
      updateState(prev => ({ ...prev, performance: clean, stage: 2 }))
      askApi('performance')
    } else if (current.stage === 2) {
      updateState(prev => ({ ...prev, quiet: clean }))
      addMessage('bot', '조건을 기록했어요. PC 구성 패널에서 예산을 확인한 뒤 AI 구성 분석 시작 버튼을 눌러주세요.')
    } else if (current.stage === 3) {
      addMessage('bot', isMockApi ? '샘플 구성을 준비 중입니다. 완료 후 이어서 질문해주세요.' : '구성을 만드는 중입니다. 완료 후 이어서 질문해주세요.')
    } else askApi('followup')
  }, [addMessage, updateState])
  const handleChoice = useCallback((value: string) => handleInput(value), [handleInput])
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
    }).then(plan => {
      if (mine !== epoch.current) return
      clearTimers()
      updateState(prev => ({ ...prev, stage: 4, currentPlan: plan }))
      addMessage('bot', isMockApi ? '샘플 구성이 준비됐어요. 부품과 예산을 확인한 뒤 리스트를 저장할 수 있습니다.' : '구성이 준비됐어요. 부품과 예산을 확인한 뒤 리스트를 확정할 수 있습니다.')
    }).catch(error => {
      if (mine !== epoch.current) return
      clearTimers()
      updateState(prev => ({ ...prev, stage: 2, currentPlan: null }))
      addMessage('bot', errorMessage(error, '구성을 만들지 못했습니다.') + ' 조건을 확인한 뒤 AI 구성 분석 시작 버튼을 다시 눌러주세요.')
    })
  }, [cancelPending, clearTimers, later, addMessage, updateState])
  const startAnalysis = useCallback(() => {
    const current = stateRef.current
    if (current.stage !== 2 || !current.quiet) return
    runAnalysis(isMockApi ? '입력 조건을 보관하고 샘플 구성을 준비합니다. 실제 분석은 아직 연결되지 않았습니다.' : '입력한 조건으로 부품 후보와 가격, 호환성을 분석합니다. 잠시만 기다려주세요.')
  }, [runAnalysis])
  const selectPart = useCallback((key: PartKey) => updateState(prev => ({ ...prev, selectedPart: key })), [updateState])
  const setBudget = useCallback((budget: number | null) => {
    if (budget !== null && (!Number.isSafeInteger(budget) || budget < 1 || budget > 100000000)) return
    const before = stateRef.current
    updateState(prev => ({ ...prev, budget, currentPlan: prev.currentPlan ? { ...prev.currentPlan, budget } : null }))
    // 서버는 조건이 바뀌면 그 추천을 낡은 것으로 보고 확정을 거절한다(stale_recommendation). 그래서 서버 추천이 나온 뒤에
    // 예산을 바꾸면 새 예산으로 다시 추천받는다 — 직접 바꾼 부품은 새 구성으로 초기화된다. 목업은 서버가 없어 화면 값만 바꾼다.
    if (!isMockApi && before.stage === 4 && before.currentPlan && budget !== before.budget) {
      runAnalysis('예산을 바꿔서 새 예산으로 구성을 다시 계산합니다. 직접 바꾼 부품은 새 구성으로 초기화돼요.')
    }
  }, [updateState, runAnalysis])
  const setDesk = useCallback((width: number, depth: number, height: number) => {
    if (![width, depth, height].every(Number.isFinite) || width < 800 || width > 3000 || depth < 400 || depth > 1500 || height < 500 || height > 1300) return false
    updateState(prev => ({ ...prev, deskWidth: width, deskDepth: depth, deskHeight: height, deskUnlocked: true }))
    showToast('책상 치수를 반영했습니다. 리스트 확정 시 구성과 함께 저장됩니다.')
    return true
  }, [showToast, updateState])
  const resetPlan = useCallback(() => {
    cancelPending()
    updateState(() => ({ ...initialState }))
    setCheckDraft(createCheckDraft())
    setMessages([makeMessage('bot', INITIAL_GREETING)])
    setAnalyzingIndex(0)
    setCustomHeading(null)
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
    setCustomHeading({ title: setup.title, desc: isMockApi ? '이 브라우저에 임시 저장한 구성' : '확정한 구성' })
    showToast('저장한 구성을 불러왔습니다.')
  }, [cancelPending, updateState, showToast])
  const startUpgradeMode = useCallback(async () => {
    const budget = parseBudget(checkDraft.budget)
    if (budget === undefined) { showToast('예산을 원 단위 숫자로 입력해주세요. 예: 800,000원'); return false }
    cancelPending()
    const mine = epoch.current
    const snapshot = structuredClone(checkDraft)
    try {
      const plan = await api.plans.recommend({
        mode: 'upgrade', budget, checkSnapshot: snapshot,
        conditions: { intent: snapshot.question, performance: '', quiet: '' },
      })
      if (mine !== epoch.current) return false
      updateState(prev => ({ ...prev, mode: 'upgrade', selectedPart: plan.items.find(p => p.key)?.key ?? 'gpu', stage: 4, budget,
        intent: snapshot.question, performance: '', quiet: '', checkSnapshot: snapshot, currentPlan: plan }))
      setMessages([makeMessage('user', snapshot.question), makeMessage('bot', isMockApi ? '입력한 질문·예산·부품을 가져왔습니다. 아래 변경 부품은 샘플이며 실제 추천·호환성 분석은 아직 연결되지 않았습니다.' : '입력한 질문·예산·부품을 가져왔습니다. 입력하지 않은 유지 부품 정보는 확인하지 못한 채 추천하니, 구매 전에 호환성을 다시 확인해주세요.')])
      setCustomHeading(null)
      return true
    } catch (error) {
      if (mine === epoch.current) showToast(errorMessage(error, '업그레이드 구성을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'))
      return false
    }
  }, [checkDraft, cancelPending, updateState, showToast])
  const value = useMemo<PlanContextValue>(() => ({
    state, checkDraft, updateCheckDraft, messages, starterHidden: state.stage > 0, analyzingIndex, customHeading,
    handleInput, handleChoice, startAnalysis, selectPart, setBudget, setDesk, resetPlan, loadFromSavedSetup, startUpgradeMode,
  }), [state, checkDraft, updateCheckDraft, messages, analyzingIndex, customHeading,
    handleInput, handleChoice, startAnalysis, selectPart, setBudget, setDesk, resetPlan, loadFromSavedSetup, startUpgradeMode])
  return <PlanContext.Provider value={value}>{children}</PlanContext.Provider>
}
