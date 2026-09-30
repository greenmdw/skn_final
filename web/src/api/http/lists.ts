import type { Api, ConversationSummary, ReportSummary } from '../types'
import { ApiError } from '../types'
import { request } from './client'
import type { WireLists, WireReportSummary } from './wire'

// 패널 "대화 내역"과 견적서 목록(개발요청 10번). 서버 목록(list) 하나 = 대화 하나이고, 그 아래 확정 견적서가 여러 개일 수 있다.

export const reportSummaryFromWire = (r: WireReportSummary): ReportSummary => ({
  revisionNo: r.revision_no, name: r.name, confirmedAt: r.confirmed_at, total: r.total, itemCount: r.item_count,
})

export const lists: Api['lists'] = {
  async list(): Promise<ConversationSummary[]> {
    const { items } = await request<WireLists>('GET', '/lists')
    return items
      .filter(item => item.category === 'computer')
      .map(item => ({
        listId: item.list_id, name: item.name, stage: item.stage, lastActiveAt: item.last_active_at,
        firstMessage: item.first_message, conditionsSummary: item.conditions_summary,
        reports: item.reports.map(reportSummaryFromWire),
      }))
      .sort((a, b) => (b.lastActiveAt ?? '').localeCompare(a.lastActiveAt ?? ''))
  },

  async rename(listId, name) {
    await request<unknown>('PATCH', '/lists/' + listId, { name })
  },

  async remove(listId) {
    try {
      await request<void>('DELETE', '/lists/' + listId)
    } catch (error) {
      if (!(error instanceof ApiError && error.code === 'not_found')) throw error   // 이미 없으면 지운 것과 같다
    }
  },
}
