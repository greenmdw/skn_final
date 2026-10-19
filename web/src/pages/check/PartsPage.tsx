import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, errorMessage } from '../../api'
import { checkV2, keySpecsText, LIVE_BATCH_MAX, liveLookupBatch, type Draft, type DraftItem, type MatchReason } from '../../api/checkV2'
import { CATEGORY_ORDER, PURPOSE_LABEL, RESOLUTION_LABEL, wonText } from '../../utils/checkReview'
import CheckLayout, { CHECK2 } from './CheckLayout'
import { useDraft } from './useDraft'

const REASON_CHIP: Record<MatchReason['code'], string> = {
  not_in_catalog: '카탈로그에 없음', variant_mismatch: '비슷하지만 다른 제품', ambiguous: '후보가 여러 개',
  insufficient_info: '정보 부족', uncertain_reading: '글자가 흐림', low_quality_photo: '글자가 흐림',     // 두 이유는 사용자에게 같은 말이라 칩은 합치고 설명 문구만 원인별로 다르다
}

/** 카탈로그에 같은 제품이 표기만 달리(괄호·공백) 두 번 들어 있으면 한 번만 보인다 */
const uniqueCandidates = (candidates: MatchReason['candidates']) => {
  const seen = new Set<string>()
  return candidates.filter(cand => { const key = cand.name.toLowerCase().replace(/[^0-9a-z가-힣]/g, ''); if (seen.has(key)) return false; seen.add(key); return true })
}

function ItemRow({ item, draft, busy, onPick, onDelete, onLookup, lookup }: {
  item: DraftItem; draft: Draft; busy: boolean
  onPick: (item: DraftItem, name: string) => void; onDelete: (item: DraftItem) => void; onLookup: (item: DraftItem) => void
  lookup?: string
}) {
  const [open, setOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState(item.normalized_name || item.raw_text)
  const confirmed = item.match_status === 'confirmed'
  const reason = item.match_reason
  const siblings = draft.items.filter(other => other.category === item.category).length
  return (
    <li className={`c2-item${confirmed ? '' : ' warn'}`}>
      <div className="c2-item-main">
        <div>
          <strong>{item.normalized_name || item.raw_text}</strong>
          {item.matched_name && item.matched_name !== (item.normalized_name || item.raw_text) && <div className="c2-sub">카탈로그: {item.matched_name}</div>}
          <div className="c2-sub">
            수량 {item.quantity}{item.quote_line_total != null ? ` · ${wonText(item.quote_line_total)}` : ' · 가격 정보 없음'}
            {siblings > 1 && item.selected_for_analysis && ' · 분석 기준'}
          </div>
          {lookup && <div className="c2-sub" role="status">검색: {lookup}</div>}
        </div>
        <div className="c2-item-side">
          <span className={`c2-badge ${confirmed ? 'ok' : 'warn'}`}>{confirmed ? '대응됨' : '제품 확인 필요'}</span>
          {reason && <span className="c2-chip" title={reason.message}>{REASON_CHIP[reason.code]}</span>}
          {!confirmed && <button type="button" className="c2-link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? '접기' : '자세히'}</button>}
          <button type="button" className="c2-link danger" disabled={busy} onClick={() => onDelete(item)}>삭제</button>
        </div>
      </div>
      {open && (
        <div className="c2-detail">
          {reason && <p>{reason.message}</p>}
          {reason?.nearest?.name && (
            <p className="c2-sub">가장 가까운 제품: {reason.nearest.name}{reason.nearest.why_not ? ` — ${reason.nearest.why_not}` : ''}{keySpecsText(reason.nearest.key_specs) ? ` (${keySpecsText(reason.nearest.key_specs)})` : ''}</p>
          )}
          {(reason?.candidates.length ?? 0) > 0 && reason && (
            <ul className="c2-cands">
              {uniqueCandidates(reason.candidates).map(cand => (
                <li key={cand.name}>
                  <div><strong>{cand.name}</strong><div className="c2-sub">{keySpecsText(cand.key_specs)}</div></div>
                  <button type="button" className="c2-btn" disabled={busy} onClick={() => onPick(item, cand.name)}>이 제품이에요</button>
                </li>
              ))}
            </ul>
          )}
          {(reason?.code === 'not_in_catalog' || reason?.code === 'insufficient_info') && (
            <div>
              <button type="button" className="c2-btn" disabled={busy} onClick={() => onLookup(item)}>정보 찾아보기</button>
            </div>
          )}
          <form className="c2-rename" onSubmit={event => { event.preventDefault(); const value = nameDraft.trim(); if (value) onPick(item, value) }}>
            <label className="c2-field">이름을 고쳐서 다시 찾기 <small>(오타나 모델명이 틀렸을 때)</small>
              <input value={nameDraft} onChange={event => setNameDraft(event.target.value)} maxLength={120} />
            </label>
            <button type="submit" className="c2-btn" disabled={busy || !nameDraft.trim() || nameDraft.trim() === (item.normalized_name || item.raw_text)}>이 이름으로 다시 찾기</button>
          </form>
        </div>
      )}
    </li>
  )
}

/** ② 인식 확인 — 읽은 부품을 확인하고, 확인 못 한 제품의 이유·후보를 보고, 사진 관계를 확인한 뒤 분석한다. */
export default function PartsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { draft, setDraft, error: loadError, loading, reload } = useDraft(id)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [lookups, setLookups] = useState<Record<string, string>>({})

  async function mutate(run: (current: Draft) => Promise<Draft>) {
    if (!draft) return
    setBusy(true); setError('')
    try { setDraft(await run(draft)) } catch (caught) {
      setError(errorMessage(caught, '저장하지 못했습니다.'))
      if (caught instanceof ApiError) void reload()
    } finally { setBusy(false) }
  }

  async function lookup(item: DraftItem) {
    if (!id) return
    setLookups(prev => ({ ...prev, [item.id]: '찾는 중…' }))
    try {
      const result = await checkV2.liveLookup(id, item.id)
      const found = result.relevant && Object.keys(result.supported_fields).length > 0
      setLookups(prev => ({ ...prev, [item.id]: found ? '사양을 찾았어요(참고용). 점검에 반영돼요.' : '정보를 찾지 못했어요.' }))
      if (found) void reload()
    } catch (caught) { setLookups(prev => ({ ...prev, [item.id]: errorMessage(caught, '검색하지 못했어요.') })) }
  }

  /** 확인하지 못한 제품을 한꺼번에 찾는다(요청 1번). 서버가 동시에 2개씩 처리하고 끝나면 항목별 결과를 한 번에 준다. */
  async function lookupAll() {
    if (!id || !draft) return
    const targets = draft.items.filter(item => ['unmatched', 'inferred', 'candidate'].includes(item.match_status)).slice(0, LIVE_BATCH_MAX)
    if (targets.length === 0) return
    setBusy(true); setError('')
    setLookups(prev => ({ ...prev, ...Object.fromEntries(targets.map(item => [item.id, '검색 중…'])) }))
    try {
      const result = await liveLookupBatch(id, targets.map(item => item.id))
      const label = { found: '사양을 찾았어요(참고용). 점검에 반영돼요.', not_found: '정보를 찾지 못했어요.', skipped: '검색 대상이 아니에요.' } as const
      setLookups(prev => ({ ...prev, ...Object.fromEntries(result.items.map(row => [row.item_id, row.state === 'failed' ? (row.message ?? '검색하지 못했어요.') : label[row.state]])) }))
      await reload()
    } catch (caught) {
      setLookups(prev => ({ ...prev, ...Object.fromEntries(targets.map(item => [item.id, ''])) }))
      setError(errorMessage(caught, '한꺼번에 찾지 못했어요.'))
    } finally { setBusy(false) }
  }

  async function setRelation(mode: 'single' | 'separate') {
    if (!draft || !id) return
    setBusy(true); setError('')
    try {
      setDraft(await checkV2.setSourceRelation(id, draft.version, mode))
      if (mode === 'separate') navigate(`${CHECK2}/${id}/compare`)
    } catch (caught) {
      setError(errorMessage(caught, '저장하지 못했습니다.'))
      void reload()
    } finally { setBusy(false) }
  }

  /** 서로 다른 견적으로 설정돼 있어도(부품을 지워 하나로 만들었을 때 등) 한 번에 한 견적으로 바꾸고 분석한다 */
  async function analyze(asSingle = false) {
    if (!id) return
    setBusy(true); setError('')
    try {
      if (asSingle && draft) setDraft(await checkV2.setSourceRelation(id, draft.version, 'single'))
      const analysis = await checkV2.analyze(id)
      navigate(`${CHECK2}/${id}/review`, { state: { analysis } })
    } catch (caught) {
      setError(errorMessage(caught, '분석하지 못했습니다.'))
      void reload()
    } finally { setBusy(false) }
  }

  if (loading) return <CheckLayout current="parts" draftId={id} reachable={[]} chat><p className="c2-note">불러오는 중…</p></CheckLayout>
  if (!draft) return <CheckLayout current="parts" draftId={id} reachable={[]} chat><p className="c2-error" role="alert">{loadError || '견적을 찾을 수 없습니다.'}</p><Link to={CHECK2}>처음으로</Link></CheckLayout>

  const relation = draft.source_relation
  const unconfirmed = draft.items.filter(item => item.match_status !== 'confirmed')
  const lookupTargets = draft.items.filter(item => ['unmatched', 'inferred', 'candidate'].includes(item.match_status))
  const conditions = draft.conditions as { purpose?: string; resolution?: string }
  const needConditions = !conditions.purpose || (conditions.purpose === 'game' && !conditions.resolution)
  const separateMode = Boolean(relation?.applies && relation.mode === 'separate')
  const confirmedItems = draft.items.filter(item => item.match_status === 'confirmed')
  // CPU·GPU 를 모르면 용도 점검과 게임 요구 비교가 거의 의미 없다 — 분석 전에 눈에 띄게 알린다
  const coreUnknown = ['CPU', 'GPU'].filter(category => {
    const rows = draft.items.filter(item => item.category === category)
    return rows.length > 0 && rows.every(item => item.match_status !== 'confirmed')
  })
  const noBasis = confirmedItems.length === 0
  const blocked = Boolean(relation?.applies && relation.confidence === 'low' && !relation.confirmed)
  const rank = (category: string) => { const index = CATEGORY_ORDER.indexOf(category); return index === -1 ? 99 : index }
  const sorted = [...draft.items].sort((a, b) => rank(a.category) - rank(b.category))
  const warnings = draft.sources.filter(source => source.quality_warning).map(source => `${source.file_name ?? '사진'}: ${source.quality_warning}`)
  const ignored = draft.sources.flatMap(source => source.ignored_lines ?? [])

  return (
    <CheckLayout current="parts" draftId={id} reachable={['parts']} chat onChatAction={() => void reload()}>
      <header className="c2-head"><h1>읽은 부품을 확인해 주세요</h1><p>제품 확인이 필요한 부품은 이유와 후보를 볼 수 있어요. 확인하지 않아도 분석할 수 있어요.</p></header>
      {error && <p className="c2-error" role="alert">{error}</p>}

      {relation?.applies && (
        <section className={`c2-card c2-relation${blocked ? ' warn' : ''}`} aria-label="사진 관계">
          <strong>
            {blocked ? '한 견적인지 서로 다른 견적인지 확실하지 않아요.'
              : relation.mode === 'single' ? '사진을 한 견적을 나눠 찍은 것으로 읽었어요.' : '사진을 서로 다른 견적으로 읽었어요.'}
          </strong>
          {blocked && <p className="c2-sub">확인하기 전에는 분석할 수 없어요.</p>}
          {(blocked ? relation.doubts : relation.reasons).length > 0 && (
            <ul className="c2-reasons">{(blocked ? relation.doubts : relation.reasons).map(text => <li key={text}>{text}</li>)}</ul>
          )}
          {!blocked && relation.mode === 'separate' && <p className="c2-sub">서로 다른 견적은 한 번에 분석하지 않고 기준별로 비교해요.</p>}
          <div className="c2-actions">
            {blocked ? (
              <>
                <button type="button" className="c2-btn" disabled={busy} onClick={() => void setRelation('separate')}>서로 다른 견적이에요</button>
                <button type="button" className="c2-btn" disabled={busy} onClick={() => void setRelation('single')}>한 견적이에요 (합치기)</button>
              </>
            ) : relation.mode === 'separate' ? (
              <>
                <Link className="c2-btn primary" to={`${CHECK2}/${id}/compare`}>두 견적 비교로</Link>
                <button type="button" className="c2-btn" disabled={busy} onClick={() => void setRelation('single')}>한 견적이에요</button>
              </>
            ) : (
              <button type="button" className="c2-btn" disabled={busy} onClick={() => void setRelation('separate')}>서로 다른 견적이에요</button>
            )}
          </div>
        </section>
      )}

      {needConditions && (
        <section className="c2-card warn" aria-label="평가 조건">
          <strong>평가 조건을 골라 주세요</strong>
          <p className="c2-sub">용도를 알아야 바꿀 부품을 추천할 수 있어요. 게임이면 해상도도 필요해요.</p>
          <div className="c2-form">
            <label>용도<select value={conditions.purpose ?? ''} onChange={event => void mutate(current => checkV2.patchConditions(current.draft_id, current.version, { purpose: event.target.value || null }))}>
              <option value="" disabled>선택해 주세요</option>{Object.entries(PURPOSE_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select></label>
            {conditions.purpose === 'game' && (
              <label>해상도<select value={conditions.resolution ?? ''} onChange={event => void mutate(current => checkV2.patchConditions(current.draft_id, current.version, { resolution: event.target.value || null }))}>
                <option value="" disabled>선택해 주세요</option>{Object.entries(RESOLUTION_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select></label>
            )}
          </div>
        </section>
      )}

      {warnings.length > 0 && <section className="c2-card warn">{warnings.map(text => <p key={text} className="c2-sub">{text}</p>)}</section>}

      <section className="c2-card">
        <h2>부품 {draft.items.length}개 · 제품 확인 필요 {unconfirmed.length}개</h2>
        {lookupTargets.length > 0 && (
          <div className="c2-actions">
            <button type="button" className="c2-btn" disabled={busy} onClick={() => void lookupAll()}>
              확인하지 못한 제품 {Math.min(lookupTargets.length, LIVE_BATCH_MAX)}개 한꺼번에 찾기
            </button>
            {lookupTargets.length > LIVE_BATCH_MAX && <span className="c2-sub">한 번에 {LIVE_BATCH_MAX}개까지 찾을 수 있어요.</span>}
          </div>
        )}
        <div className="c2-items">
          {sorted.map(item => (
            <div key={item.id}>
              <span className="c2-cat">{item.category}</span><ul>
              <ItemRow item={item} draft={draft} busy={busy} lookup={lookups[item.id]}
                onPick={(row, name) => void mutate(current => checkV2.patchItems(current.draft_id, current.version, [{ id: row.id, normalized_name: name }]))}
                onDelete={row => void mutate(current => checkV2.patchItems(current.draft_id, current.version, [{ id: row.id, delete: true }]))}
                onLookup={row => void lookup(row)} /></ul>
            </div>
          ))}
        </div>
        {ignored.length > 0 && <details><summary className="c2-sub">분석에서 뺀 줄 {ignored.length}개</summary><ul>{ignored.map((line, index) => <li key={index} className="c2-sub">{line}</li>)}</ul></details>}
      </section>

      {coreUnknown.length > 0 && !noBasis && (
        <section className="c2-card warn" role="status">
          <strong>{coreUnknown.join('·')}을(를) 확인하지 못했어요.</strong>
          <p className="c2-sub">용도 점검과 게임 요구 비교가 제한돼요. 이름을 고치거나 정보를 찾아보면 더 정확해져요. 그대로 분석할 수도 있어요.</p>
        </section>
      )}

      <div className="c2-actions end">
        {noBasis && <span className="c2-sub">확인된 부품이 하나도 없어 분석할 수 없어요. 이름을 고치거나 정보를 찾아 주세요.</span>}
        {!noBasis && unconfirmed.length > 0 && <span className="c2-sub">제품 확인이 남은 부품 {unconfirmed.length}개는 가진 정보로만 점검해요.</span>}
        {separateMode ? (
          <>
            <span className="c2-sub">지금은 서로 다른 견적으로 설정돼 있어서 바로 분석할 수 없어요. 부품을 직접 골라 한 견적으로 만들었다면 오른쪽 버튼을 눌러 주세요.</span>
            <button type="button" className="c2-btn primary" disabled={busy || needConditions || noBasis || draft.items.length === 0} onClick={() => void analyze(true)}>한 견적으로 바꾸고 분석하기</button>
          </>
        ) : (
          <button type="button" className="c2-btn primary" disabled={busy || blocked || needConditions || noBasis || draft.items.length === 0} onClick={() => void analyze()}>이대로 분석하기</button>
        )}
      </div>
    </CheckLayout>
  )
}
