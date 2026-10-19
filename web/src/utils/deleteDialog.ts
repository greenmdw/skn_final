export type DeleteChoice = 'soft' | 'permanent' | null

/** 삭제 확인창 — "삭제"(삭제 표시 후 일정 기간 보관한 뒤 영구 삭제), "완전히 삭제"(지금 바로 영구 삭제, 복구 불가), "취소" 중 고른다.
 *  테마 색 변수가 .pl-root 에 있어서 그 안에 붙인다. 접근성: role=dialog, 첫 버튼 포커스, Esc 로 취소. */
export function askDelete(title: string, message = ''): Promise<DeleteChoice> {
  return new Promise(resolve => {
    const host = document.querySelector('.pl-root') ?? document.body
    const back = document.createElement('div')
    back.style.cssText = 'position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:16px;background:rgba(0,0,0,.45)'
    const box = document.createElement('div')
    box.setAttribute('role', 'dialog')
    box.setAttribute('aria-modal', 'true')
    box.setAttribute('aria-label', title)
    box.style.cssText = 'width:min(420px,100%);background:var(--panel,#fff);color:var(--text,#111);border:1px solid var(--line,#ccc);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:10px;box-shadow:0 12px 40px rgba(0,0,0,.35)'
    const heading = document.createElement('strong')
    heading.textContent = title
    const body = document.createElement('p')
    body.style.cssText = 'margin:0;font-size:13px;line-height:1.6;color:var(--muted,#666);white-space:pre-line'
    body.textContent = `${message ? `${message}\n\n` : ''}삭제하면 일정 기간 보관한 뒤 영구 삭제돼요. "완전히 삭제"는 지금 바로 지우고 되돌릴 수 없어요.`
    const row = document.createElement('div')
    row.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end'

    const finish = (choice: DeleteChoice) => {
      document.removeEventListener('keydown', onKey)
      back.remove()
      resolve(choice)
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') finish(null) }
    const button = (label: string, choice: DeleteChoice, danger = false) => {
      const el = document.createElement('button')
      el.type = 'button'
      el.textContent = label
      el.style.cssText = `border:1px solid ${danger ? '#c2410c' : 'var(--line,#ccc)'};background:transparent;color:${danger ? '#c2410c' : 'inherit'};border-radius:8px;padding:7px 14px;font-size:13px;cursor:pointer`
      el.addEventListener('click', () => finish(choice))
      return el
    }
    const cancel = button('취소', null)
    row.append(cancel, button('삭제', 'soft'), button('완전히 삭제', 'permanent', true))
    box.append(heading, body, row)
    back.append(box)
    back.addEventListener('mousedown', event => { if (event.target === back) finish(null) })
    document.addEventListener('keydown', onKey)
    host.append(back)
    cancel.focus()
  })
}
