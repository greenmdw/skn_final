import type { Api, SetupsListResult } from '../types'
import { ApiError } from '../types'
import type { SavedSetup } from '../../state/types'
import { isSetup } from '../../state/validators'

// 목업: 서버 대신 이 브라우저의 localStorage에 저장합니다.
const SETUPS_KEY = 'truefit.setups.v1'
const SETUPS_BACKUP_KEY = 'truefit.setups.v1.backup'

interface Loaded extends SetupsListResult {
  /** false면 원본을 백업하지 못한 상태이므로 덮어쓰기를 막아야 합니다. */
  writable: boolean
}

// 형식이 틀린 저장 데이터는 통째로 버리지 않고, 유효한 항목만 살립니다.
// 걸러낸 항목이 있으면 원본을 백업 키에 먼저 보관하며, 백업에 실패하면 이후 저장(덮어쓰기)을 막습니다.
function load(): Loaded {
  let raw: string | null
  try { raw = localStorage.getItem(SETUPS_KEY) }
  catch { return { data: [], warning: '저장 목록을 읽지 못했습니다. 브라우저 저장소 설정을 확인해주세요.', writable: false } }
  if (!raw) return { data: [], warning: '', writable: true }
  let parsed: unknown = null
  let parseFailed = false
  try { parsed = JSON.parse(raw) } catch { parseFailed = true }
  const items: unknown[] = Array.isArray(parsed) ? parsed : []
  const data = items.filter(isSetup)
  const dropped = parseFailed || !Array.isArray(parsed) ? -1 : items.length - data.length
  if (dropped === 0) return { data, warning: '', writable: true }
  let writable = true
  try { if (localStorage.getItem(SETUPS_BACKUP_KEY) !== raw) localStorage.setItem(SETUPS_BACKUP_KEY, raw) }
  catch { writable = false }
  const lost = dropped === -1 ? '저장 목록의 형식이 올바르지 않아 불러오지 못했습니다.' : `형식이 올바르지 않은 구성 ${dropped}개를 제외했습니다.`
  const tail = writable ? '원본은 브라우저 저장소에 백업해 두었습니다.' : '백업 공간이 부족해 새로 저장할 수 없습니다. 저장 공간을 확보한 뒤 새로고침해주세요.'
  return { data, warning: `${lost} ${tail}`, writable }
}

function write(next: SavedSetup[]) {
  try { localStorage.setItem(SETUPS_KEY, JSON.stringify(next)) }
  catch { throw new ApiError('브라우저에 저장하지 못했습니다. 저장 공간과 브라우저 설정을 확인한 후 다시 시도해주세요.', 'STORAGE_FAILED') }
}

function loadWritable(): SavedSetup[] {
  const { data, warning, writable } = load()
  if (!writable) throw new ApiError(warning, 'STORAGE_UNWRITABLE')
  return data
}

export const setups: Api['setups'] = {
  async list() {
    const { data, warning } = load()
    return { data, warning }
  },
  async save(setup) {
    const saved = structuredClone(setup)
    write([saved, ...loadWritable().filter(s => s.id !== saved.id)])
    return structuredClone(saved)
  },
  async remove(id) {
    write(loadWritable().filter(s => s.id !== id))
  },
}
