import type { Api, QuoteDraft, QuoteDraftItem, QuoteGuideRef, QuoteSavedComparison, QuoteVisual } from '../types'
import { request, requestForm } from './client'
import { quoteReviewFromWire } from './checks'
import type {
  WireLiveSpecLookup, WireQuoteCapabilities, WireQuoteChatHistoryRich, WireQuoteChatReply, WireQuoteDraft,
  WireQuoteDraftAnalysis, WireQuoteDraftComparison, WireQuoteDraftItem, WireQuoteGuideRef, WireQuoteReplacementPreview,
  WireQuoteSavedComparison,
} from './wire'

const base = (draftId: string) => `/pc/review-drafts/${encodeURIComponent(draftId)}`
const reviewBase = (listId: string) => `/pc/reviews/${encodeURIComponent(listId)}`

function itemFromWire(item: WireQuoteDraftItem): QuoteDraftItem {
  return {
    id: item.id, category: item.category, rawText: item.raw_text, name: item.normalized_name, productCode: item.product_code,
    quantity: item.quantity, unitPrice: item.quote_unit_price, lineTotal: item.quote_line_total, priceType: item.quote_price_type,
    matchedProductId: item.matched_product_id, matchedProductKey: item.matched_product_key, matchedName: item.matched_name,
    imageUrl: item.image_url, matchStatus: item.match_status, candidateCount: item.candidate_count,
    sourceIds: item.source_ids, selectedForAnalysis: item.selected_for_analysis, userEdited: item.user_edited,
  }
}

function draftFromWire(draft: WireQuoteDraft): QuoteDraft {
  return {
    draftId: draft.draft_id, version: draft.version,
    sources: draft.sources.map(source => ({
      id: source.id, type: source.type, fileName: source.file_name, sortOrder: source.sort_order, status: source.status, errorCode: source.error_code,
    })),
    items: draft.items.map(itemFromWire),
    selectedItemByCategory: draft.selected_item_by_category ?? {},
    conditions: draft.conditions ?? {},
    question: draft.question,
    partialSuccess: draft.partial_success,
    groups: (draft.groups ?? []).map(group => ({ id: group.id, name: group.name, sourceIds: group.source_ids, itemIds: group.item_ids })),
    createdAt: draft.created_at,
  }
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const textOrNull = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** 서버가 조립한 자료 중 화면이 아는 형식만 옮긴다. 모르는 형식은 버린다. */
function visualsFromWire(raw: Record<string, unknown>[] | undefined): QuoteVisual[] {
  const visuals: QuoteVisual[] = []
  for (const visual of raw ?? []) {
    const rows = Array.isArray(visual.items) ? (visual.items as Record<string, unknown>[]) : []
    if (visual.type === 'product_comparison') {
      visuals.push({
        type: 'product_comparison', category: textOrNull(visual.category), title: text(visual.title),
        items: rows.map(item => ({
          side: text(item.side), productId: textOrNull(item.product_id), name: text(item.name),
          imageUrl: textOrNull(item.image_url), price: numberOrNull(item.price),
        })),
      })
    } else if (visual.type === 'table') {
      visuals.push({
        type: 'table', category: textOrNull(visual.category), title: text(visual.title),
        columns: Array.isArray(visual.columns) ? visual.columns.map(String) : [],
        rows: Array.isArray(visual.rows) ? (visual.rows as unknown[]).filter(Array.isArray) as unknown[][] : [],
      })
    } else if (visual.type === 'compatibility_check') {
      visuals.push({
        type: 'compatibility_check', title: text(visual.title),
        items: rows.map(item => ({ side: text(item.side), axis: text(item.axis), label: text(item.label), state: text(item.state), detail: text(item.detail) })),
      })
    }
  }
  return visuals
}

function guideRefsFromWire(refs: WireQuoteGuideRef[] | undefined): QuoteGuideRef[] {
  return (refs ?? []).map(ref => ({ id: ref.id, slot: ref.slot, kind: ref.kind, text: ref.text, score: ref.score }))
}

function savedComparisonFromWire(result: WireQuoteSavedComparison): QuoteSavedComparison {
  const product = (item: WireQuoteSavedComparison['rows'][number]['received']) => item ? {
    productId: item.product_id, productKey: item.product_key, name: item.name, imageUrl: item.image_url,
    quantity: item.quantity, lineTotal: item.line_total,
  } : null
  return {
    comparisonId: result.comparison_id, receivedTotal: result.received_total, savedTotal: result.saved_total, totalDiff: result.total_diff,
    comparableCategories: result.comparable_categories ?? [], excludedReceivedCategories: result.excluded_received_categories ?? [],
    rows: result.rows.map(row => ({
      category: row.category, sameProduct: row.same_product, received: product(row.received), saved: product(row.saved), priceDiff: row.price_diff,
    })),
    briefSummary: {
      changedCount: result.brief_summary.changed_count,
      largestPriceDifferenceCategory: result.brief_summary.largest_price_difference_category,
      text: result.brief_summary.text,
    },
    savedName: typeof result.saved?.name === 'string' && result.saved.name ? result.saved.name : (result.labels?.saved ?? '저장한 견적'),
    computedAt: result.computed_at,
  }
}

export const quoteDrafts: Api['quoteDrafts'] = {
  async capabilities() {
    const result = await request<WireQuoteCapabilities>('GET', '/pc/reviews/capabilities')
    return {
      imageExtraction: result.image_extraction, supportedTypes: result.supported_types, maxFiles: result.max_files,
      maxFileBytes: result.max_file_bytes, maxTotalBytes: result.max_total_bytes, textMaxChars: result.text_max_chars,
    }
  },
  async create({ images, text: sourceText, question, conditions }) {
    const form = new FormData()
    for (const image of images) form.append('images', image, image.name)
    if (sourceText?.trim()) form.append('text', sourceText.trim())
    if (question?.trim()) form.append('question', question.trim())
    if (conditions) {
      const body = {
        purpose: conditions.purpose, resolution: conditions.resolution, priority: conditions.priority,
        games: conditions.games ?? [], budget_max: conditions.budgetMax,
      }
      form.append('conditions', JSON.stringify(body))
    }
    return draftFromWire(await requestForm<WireQuoteDraft>('/pc/review-drafts', form))
  },
  async get(draftId) {
    return draftFromWire(await request<WireQuoteDraft>('GET', base(draftId)))
  },
  async patchItems(draftId, expectedVersion, items, selectedItemByCategory) {
    const body = {
      expected_version: expectedVersion,
      items: items.map(item => ({
        id: item.id,
        ...(item.delete ? { delete: true } : {}),
        ...(item.name !== undefined ? { normalized_name: item.name } : {}),
        ...(item.quantity !== undefined ? { quantity: item.quantity } : {}),
        ...(item.lineTotal !== undefined ? { quote_line_total: item.lineTotal } : {}),
      })),
      ...(selectedItemByCategory ? { selected_item_by_category: selectedItemByCategory } : {}),
    }
    return draftFromWire(await request<WireQuoteDraft>('PATCH', `${base(draftId)}/items`, body))
  },
  async analyze(draftId) {
    const result = await request<WireQuoteDraftAnalysis>('POST', `${base(draftId)}/analysis`, {})
    const requirement = (result.balance as { requirement?: { label?: unknown } } | null)?.requirement
    return {
      ...quoteReviewFromWire(result),
      usedItems: result.used_items.map(itemFromWire),
      question: result.question,
      draftVersion: result.draft_version,
      priceExcluded: result.price_excluded.map(row => ({ category: row.category, itemId: row.item_id, reason: row.reason })),
      priceRows: result.price_rows.map(row => ({
        category: row.category, itemId: row.item_id, quantity: row.quantity, quoteUnitPrice: row.quote_unit_price,
        quoteLineTotal: row.quote_line_total, quotePriceType: row.quote_price_type, catalogUnitPrice: row.catalog_unit_price,
        catalogLineTotal: row.catalog_line_total, catalogCheckedAt: row.catalog_checked_at, catalogStatus: row.catalog_status,
        diffLineTotal: row.diff_line_total,
      })),
      requirementLabel: typeof requirement?.label === 'string' && requirement.label ? requirement.label : null,
    }
  },
  async compareCategory(draftId, category, baselineItemId) {
    const query = baselineItemId ? `?baseline_item_id=${encodeURIComponent(baselineItemId)}` : ''
    const result = await request<WireQuoteDraftComparison>('GET', `${base(draftId)}/categories/${encodeURIComponent(category)}/comparison${query}`)
    return {
      category: result.category, baselineItemId: result.baseline_item_id, notes: result.notes ?? [],
      recognized: result.recognized.map(option => ({
        itemId: option.item_id, productId: option.product_id, name: option.name, imageUrl: option.image_url, quantity: option.quantity,
        quoteLineTotal: option.quote_line_total, matchStatus: option.match_status,
        specs: option.specs.map(spec => ({ key: spec.key, label: spec.label, unit: spec.unit, candidate: spec.candidate })),
      })),
      recommended: result.recommended.flatMap(option => option.product_id ? [{
        productId: option.product_id, name: option.name, imageUrl: option.image_url, price: option.price, priceDelta: option.price_delta,
        specs: option.specs, compatChanges: option.compat_changes, incompatible: option.incompatible,
        additionalReplacements: option.additional_replacements, reason: option.reason,
      }] : []),
    }
  },
  async previewReplacements(draftId, replacements) {
    const result = await request<WireQuoteReplacementPreview>('POST', `${base(draftId)}/replacements/preview`, {
      replacements: replacements.map(row => ({ category: row.category, candidate_product_id: row.candidateProductId })),
    })
    return {
      beforeTotal: result.before_total, afterTotal: result.after_total, totalDiff: result.total_diff,
      newIssues: result.new_issues, resolvedIssues: result.resolved_issues, additionalReplacements: result.additional_replacements,
      priceExcluded: result.price_excluded.map(row => ({ category: row.category, itemId: row.item_id, reason: row.reason })),
    }
  },
  async applyReplacements(draftId, expectedVersion, replacements) {
    const result = await request<WireQuoteDraft>('POST', `${base(draftId)}/replacements/apply`, {
      expected_version: expectedVersion,
      replacements: replacements.map(row => ({ category: row.category, candidate_product_id: row.candidateProductId })),
    })
    return draftFromWire(result)
  },
  async liveLookupItem(draftId, itemId) {
    const result = await request<WireLiveSpecLookup>('POST', `${base(draftId)}/items/${encodeURIComponent(itemId)}/live-lookup`)
    return {
      slot: result.slot, query: result.query, relevant: result.relevant, supportedFields: result.supported_fields,
      sourceUrl: result.source_url, fetchedAt: result.fetched_at, reviewStatus: result.status,
      referencePrice: result.reference_price, referencePriceAt: result.reference_price_at,
    }
  },
  async compareSaved(listId, savedListId, savedRevisionNo) {
    const result = await request<WireQuoteSavedComparison>('POST', `${reviewBase(listId)}/saved-comparisons`, {
      saved_list_id: savedListId, ...(savedRevisionNo ? { saved_revision_no: savedRevisionNo } : {}),
    })
    return savedComparisonFromWire(result)
  },
  async getSavedComparison(listId, comparisonId) {
    return savedComparisonFromWire(await request<WireQuoteSavedComparison>('GET', `${reviewBase(listId)}/saved-comparisons/${encodeURIComponent(comparisonId)}`))
  },
  async sendChat(listId, message, options) {
    const result = await request<WireQuoteChatReply>('POST', `${reviewBase(listId)}/messages`, {
      text: message,
      ...(options?.clientMessageId ? { client_message_id: options.clientMessageId } : {}),
      ...(options?.comparisonId ? { context: { type: 'saved_quote_comparison', comparison_id: options.comparisonId } } : {}),
    })
    return {
      messageId: result.message_id, answerId: result.answer_id, reply: result.reply,
      guideRefs: guideRefsFromWire(result.guide_refs), visuals: visualsFromWire(result.visuals),
      displayTarget: result.display_target, duplicateOf: result.duplicate_of, via: result.via, createdAt: result.created_at,
    }
  },
  async chatHistory(listId) {
    const result = await request<WireQuoteChatHistoryRich>('GET', `${reviewBase(listId)}/messages`)
    return result.messages.map(message => ({
      id: message.id, role: message.role, text: message.text, createdAt: message.created_at,
      comparisonId: message.comparison_id, answerId: message.answer_id,
      guideRefs: guideRefsFromWire(message.guide_refs), visuals: visualsFromWire(message.visuals),
      displayTarget: message.display_target, duplicateOf: message.duplicate_of, via: message.via,
    }))
  },
}
