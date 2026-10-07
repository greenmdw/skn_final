import { useMemo } from 'react'
import type { QuoteDraft, QuoteRecommendedOption, QuoteReplacementPreview } from '../../api'
import {
  MAX_QUANTITY, groupItems, itemStatus, matchedLine, selectedTotal, signedWon, sourceBadge, withPending, wonText, type PendingEdit,
} from '../../utils/checkReview'

export type ResultFilter = 'all' | 'review' | 'checked'

export default function RecognitionResult({
  draft, selection, pending, filter, onFilter, onSelect, onEdit, onQuantity, onCompare, cart, cartPreview, cartPreviewBusy, onClearCart, onApplyCart,
  onCancelEdits, onReanalyze, onAnalyze, onReviewOnly, busy,
}: {
  draft: QuoteDraft
  selection: Record<string, string>
  pending: Record<string, PendingEdit>
  filter: ResultFilter
  onFilter: (filter: ResultFilter) => void
  onSelect: (category: string, itemId: string) => void
  onEdit: (itemId: string) => void
  onQuantity: (itemId: string, quantity: number) => void
  onCompare: (category: string) => void
  cart: Record<string, QuoteRecommendedOption>
  cartPreview: QuoteReplacementPreview | null
  cartPreviewBusy: boolean
  onClearCart: () => void
  onApplyCart: () => void
  onCancelEdits: () => void
  onReanalyze: () => void
  onAnalyze: () => void
  onReviewOnly: () => void
  busy: boolean
}) {
  const visibleItems = draft.items.filter(item => !pending[item.id]?.delete)
  const statuses = useMemo(() => new Map(visibleItems.map(item => [item.id, itemStatus(item, pending[item.id])])), [visibleItems, pending])
  const checkedCount = visibleItems.filter(item => statuses.get(item.id)?.checked).length
  const reviewCount = visibleItems.length - checkedCount
  const groups = groupItems(visibleItems)
  const shownGroups = groups
    .map(group => ({
      ...group,
      shown: group.items.filter(item => filter === 'all' || (filter === 'review' ? !statuses.get(item.id)?.checked : statuses.get(item.id)?.checked)),
    }))
    .filter(group => group.shown.length > 0)
  const pendingCount = Object.keys(pending).length
  const cartEntries = Object.entries(cart)
  const completedSources = draft.sources.filter(source => source.type === 'image' || source.type === 'text')
  const failedSources = completedSources.filter(source => source.status === 'failed')
  const total = selectedTotal({ ...draft, items: visibleItems }, selection, pending)

  return (
    <section className="ck-card ck-results" id="ck-results">
      <div className="ck-result-head">
        <div>
          <div className="ck-result-title-row">
            <b>인식 결과</b>
            {reviewCount > 0 && <span className="ck-status warn">{reviewCount}개 확인 필요</span>}
            <span className="ck-status-legend">상태 안내
              <button type="button" className="ck-legend-help" title="대응됨: 카탈로그 제품을 찾음 · 확인 필요: 제품이 모호하거나 정보가 부족함 · 사용자 확인: 직접 수정한 항목" aria-label="상태 안내">?</button>
            </span>
          </div>
          <span>부품 종류별로 인식된 모든 제품을 정리했습니다. 같은 종류가 여러 개면 비교한 뒤 분석 기준을 하나 골라주세요.</span>
        </div>
        <div className="ck-result-metrics">
          <span className="ck-metric">인식 제품 <b>{visibleItems.length}개</b></span>
          <span className="ck-metric">부품 종류 <b>{groups.length}종</b></span>
          <span className="ck-metric">출처 <b>{completedSources.length}장</b></span>
          <span className="ck-metric">선택 합계 <b><em>{wonText(total)}</em></b></span>
        </div>
      </div>

      {failedSources.length > 0 && (
        <div className="ck-normalization-note warn">
          <span><b>일부 이미지를 읽지 못했어요</b> · {failedSources.map(source => source.fileName ?? '이미지').join(', ')} — 읽은 나머지 이미지의 결과는 그대로 남겼습니다.</span>
        </div>
      )}
      <div className="ck-normalization-note">
        <span><b>제품명 정리 완료</b> · 가격 문구는 제품명에서 제외하고 별도 금액으로 저장했어요.</span>
        <span>동일 제품 중복만 병합 · 다른 모델은 모두 유지</span>
      </div>

      <div className="ck-result-tools">
        <div className="ck-chips">
          <button type="button" className={`ck-chip${filter === 'all' ? ' on' : ''}`} onClick={() => onFilter('all')}>전체 {visibleItems.length}</button>
          <button type="button" className={`ck-chip${filter === 'review' ? ' on' : ''}`} onClick={() => onFilter('review')}>확인 필요 {reviewCount}</button>
          <button type="button" className={`ck-chip${filter === 'checked' ? ' on' : ''}`} onClick={() => onFilter('checked')}>확인 완료 {checkedCount}</button>
        </div>
        <span className="ck-review-progress">확인 완료 <b>{checkedCount}/{visibleItems.length}</b></span>
      </div>

      <div className="ck-table-wrap">
        <table className="ck-recognition-table">
          <thead><tr><th>분석 기준</th><th>인식한 제품</th><th>가격</th><th>인식 상태</th></tr></thead>
          <tbody>
            {shownGroups.map(group => (
              <GroupRows key={group.category} group={group} all={groups.find(entry => entry.category === group.category)?.items ?? []}
                draft={draft} selection={selection} pending={pending} statuses={statuses} busy={busy} onSelect={onSelect} onEdit={onEdit} onQuantity={onQuantity} onCompare={onCompare} />
            ))}
            {shownGroups.length === 0 && <tr><td colSpan={4} className="ck-table-empty">해당하는 부품이 없어요.</td></tr>}
          </tbody>
        </table>
      </div>

      {pendingCount > 0 && (
        <div className="ck-tray show">
          <strong>수정 {pendingCount}건</strong>
          <span>수정 내용은 아직 분석에 반영되지 않았어요. 여러 항목을 마친 뒤 한 번만 다시 분석할 수 있습니다.</span>
          <i className="ck-spacer" />
          <button type="button" className="ck-text-button" onClick={onCancelEdits} disabled={busy}>수정 취소</button>
          <button type="button" className="ck-small-primary" onClick={onReanalyze} disabled={busy}>수정 내용으로 다시 분석</button>
        </div>
      )}

      {cartEntries.length > 0 && (
        <div className="ck-tray show">
          <strong>교체 목록</strong>
          <div className="ck-tray-items">
            {cartEntries.map(([category, option]) => <span className="ck-tray-chip" key={category}><b>{category}</b> · {option.name}</span>)}
          </div>
          <i className="ck-spacer" />
          <button type="button" className="ck-text-button" onClick={onClearCart} disabled={busy}>비우기</button>
          <button type="button" className="ck-small-primary" onClick={onApplyCart} disabled={busy}>선택한 대로 한 번에 바꾸기</button>
          <div className="ck-tray-preview">
            {cartPreviewBusy && <span>교체 영향을 계산하는 중이에요…</span>}
            {!cartPreviewBusy && cartPreview && (
              <>
                <span>선택 합계 <b>{wonText(cartPreview.beforeTotal)}</b> → <b>{wonText(cartPreview.afterTotal)}</b> ({signedWon(cartPreview.totalDiff)})</span>
                <span>새로 생기는 호환 문제 <b>{cartPreview.newIssues.length}</b> · 해소되는 문제 <b>{cartPreview.resolvedIssues.length}</b></span>
                {cartPreview.additionalReplacements.length > 0 && (
                  <span>함께 바꿔야 할 부품 · {cartPreview.additionalReplacements.map(row => `${row.category}(${row.reason})`).join(', ')}</span>
                )}
                {cartPreview.newIssues.map(issue => <span className="bad" key={`${issue.axis}-${issue.detail}`}>⚠ {issue.label} · {issue.detail}</span>)}
              </>
            )}
          </div>
        </div>
      )}

      <div className="ck-result-actions">
        <div className="ck-readiness">
          <span className="ck-readiness-icon">↔</span>
          <span><strong>인식 제품과 추가 추천 제품을 한 번에 비교할 수 있어요.</strong><br />인식 제품은 분석 기준으로 선택하고, 추천 제품은 교체 목록에 담을 수 있습니다.</span>
        </div>
        <button type="button" className="ck-outline" onClick={onReviewOnly}>확인 필요한 항목 보기</button>
        <button type="button" className="ck-primary" disabled={busy || visibleItems.length === 0} onClick={onAnalyze}>{busy ? '분석 중…' : '선택한 구성 분석하기'}</button>
      </div>
    </section>
  )
}

function GroupRows({ group, all, draft, selection, pending, statuses, busy, onSelect, onEdit, onQuantity, onCompare }: {
  group: { category: string; shown: QuoteDraft['items'] }
  all: QuoteDraft['items']
  draft: QuoteDraft
  selection: Record<string, string>
  pending: Record<string, PendingEdit>
  statuses: Map<string, ReturnType<typeof itemStatus>>
  onSelect: (category: string, itemId: string) => void
  busy: boolean
  onEdit: (itemId: string) => void
  onQuantity: (itemId: string, quantity: number) => void
  onCompare: (category: string) => void
}) {
  return (
    <>
      <tr className="ck-group-row">
        <td colSpan={4}>
          <div className="ck-group-head">
            <div className="ck-group-label"><strong>{group.category}</strong><span>인식 {all.length}개</span></div>
            <button type="button" className="ck-group-compare" onClick={() => onCompare(group.category)}>{group.category} 제품 비교</button>
          </div>
        </td>
      </tr>
      {group.shown.map(item => {
        const shownItem = withPending(item, pending[item.id])
        const status = statuses.get(item.id)!
        const selected = selection[group.category] === item.id
        const variantNo = all.findIndex(entry => entry.id === item.id) + 1
        const matched = matchedLine(item)
        return (
          <tr key={item.id} className={`${status.checked ? '' : 'needs-review'} ${selected ? 'analysis-choice' : ''}`}>
            <td>
              <input className="ck-choice-radio" type="radio" name={`analysis-${group.category}`} checked={selected} onChange={() => onSelect(group.category, item.id)} aria-label={`${group.category} 분석 기준으로 선택`} />
              <span className="ck-choice-label">{selected ? '분석에 사용' : '선택 가능'}</span>
            </td>
            <td>
              <div className="ck-product">
                <div className="ck-product-title">
                  <span className="ck-product-name">{shownItem.name}</span>
                  <button type="button" className="ck-edit" onClick={() => onEdit(item.id)} aria-label={`${group.category} 제품 정보 수정`} title="제품명·수량·가격 수정">✎</button>
                </div>
                <span className="ck-product-meta">
                  <span className="ck-variant-badge">제품 {variantNo}</span>
                  <span className="ck-qty-step" role="group" aria-label={`${group.category} 수량`} title="수량을 바꾸면 품목 금액도 같은 비율로 바뀌어요">
                    <button type="button" disabled={busy || shownItem.quantity <= 1} onClick={() => onQuantity(item.id, shownItem.quantity - 1)} aria-label="수량 줄이기">−</button>
                    <span aria-live="polite">수량 {shownItem.quantity}</span>
                    <button type="button" disabled={busy || shownItem.quantity >= MAX_QUANTITY} onClick={() => onQuantity(item.id, shownItem.quantity + 1)} aria-label="수량 늘리기">+</button>
                  </span>
                  <span className="ck-source-badge">▧ {sourceBadge(item, draft)}</span>
                  {item.productCode && <span className="ck-code-badge" title="견적 원문에서 분리한 상품코드">코드 {item.productCode}</span>}
                  {pending[item.id] && <span className="ck-dirty-badge">수정 대기</span>}
                </span>
              </div>
            </td>
            <td className={`ck-price${shownItem.lineTotal == null ? ' missing' : ''}`}>{wonText(shownItem.lineTotal)}</td>
            <td>
              <div className="ck-recognition-cell">
                <span className={`ck-status ${status.tone}`}>{status.label}</span>
                <span className="ck-matched-name" title={matched}>{matched}</span>
              </div>
            </td>
          </tr>
        )
      })}
    </>
  )
}
