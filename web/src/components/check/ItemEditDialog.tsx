import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { QuoteDraftItem } from '../../api'
import { splitNameAndPrice, withPending, type PendingEdit } from '../../utils/checkReview'

export default function ItemEditDialog({ item, pending, onSave, onClose }: {
  item: QuoteDraftItem
  pending?: PendingEdit
  onSave: (edit: PendingEdit) => void
  onClose: () => void
}) {
  const current = withPending(item, pending)
  const [name, setName] = useState(current.name)
  const [quantity, setQuantity] = useState(String(current.quantity))
  const [price, setPrice] = useState(current.lineTotal == null ? '' : String(current.lineTotal))
  const [error, setError] = useState('')
  const nameInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameInput.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function submit(event: FormEvent) {
    event.preventDefault()
    const split = splitNameAndPrice(name.trim())
    if (!split.name) { setError('제품명을 입력해주세요.'); return }
    const count = Number(quantity)
    if (!Number.isInteger(count) || count < 1 || count > 20) { setError('수량은 1~20 사이의 정수로 입력해주세요.'); return }
    let lineTotal: number | null
    if (price.trim() === '') {
      lineTotal = split.price
    } else {
      const parsed = Number(price.replaceAll(',', ''))
      if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100_000_000) { setError('금액은 0원 이상 1억 원 이하로 입력해주세요.'); return }
      lineTotal = Math.round(parsed)
    }
    onSave({ name: split.name, quantity: count, lineTotal })
  }

  return (
    <div className="ck-dialog-back" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <form className="ck-dialog ck-edit-dialog" role="dialog" aria-modal="true" aria-label={`${item.category} 제품 정보 수정`} onSubmit={submit}>
        <div className="ck-modal-head">
          <div><h2>{item.category} 제품 정보 수정</h2><p className="ck-modal-intro">가격을 제품명에 함께 적어도 자동으로 나눠 저장해요. 수정은 목록에 담기만 하고, 한 번에 다시 분석합니다.</p></div>
          <button type="button" className="ck-close" onClick={onClose} aria-label="닫기">×</button>
        </div>
        <div className="ck-edit-body">
          <label>제품명<input ref={nameInput} value={name} maxLength={200} onChange={event => setName(event.target.value)} /></label>
          <div className="ck-edit-row">
            <label>수량<input type="number" min={1} max={20} value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
            <label>품목 금액(원, 수량 반영)<input inputMode="numeric" value={price} placeholder="금액 미인식" onChange={event => setPrice(event.target.value)} /></label>
          </div>
          <small>원문 · {item.rawText}</small>
          {error && <div className="ck-form-error" role="alert">{error}</div>}
        </div>
        <div className="ck-modal-foot">
          <button type="button" className="ck-danger-text" onClick={() => onSave({ delete: true })}>이 항목 삭제</button>
          <span className="ck-spacer" />
          <button type="button" className="ck-text-button" onClick={onClose}>취소</button>
          <button type="submit" className="ck-primary">수정 목록에 담기</button>
        </div>
      </form>
    </div>
  )
}
