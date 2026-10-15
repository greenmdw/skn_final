import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage, type QuoteCapabilities } from '../../api'
import { useSetups } from '../../state/SetupsContext'
import { useToast } from '../../state/ToastContext'
import { wonFmt } from '../../utils/format'
import { Hero } from './parts'
import { PC_FIELDS, configKey, dateText, newestFirst, pcKey, setupToPcParts, setupTotal, type MyPc, type PcParts } from './model'

function CurrentPc({ myPc, onUse, onReset }: { myPc: MyPc | null; onUse: () => void; onReset: () => void }) {
  if (!myPc) {
    return (
      <div className="mp-empty-card">
        <b style={{ fontSize: 40 }}>🖥️</b><strong>등록된 현재 PC가 없어요</strong>
        <span>아래 방법으로 지금 쓰는 PC를 등록하면 받은 견적 점검에 바로 활용할 수 있어요.</span>
      </div>
    )
  }
  return (
    <div className="pc-current">
      <div className="pc-current-head">
        <div>
          <h2>내 현재 PC</h2>
          <p><span className="mpx-tag">{myPc.source}</span> {myPc.title ? `${myPc.title} · ` : ''}{dateText(myPc.savedAt)} 등록</p>
        </div>
        <div className="mpx-btns">
          <button className="mp-btn primary" type="button" onClick={onUse}>받은 견적 점검에 적용</button>
          <button className="mp-btn" type="button" onClick={onReset}>삭제</button>
        </div>
      </div>
      <div className="pc-parts">
        {PC_FIELDS.map(([key, label]) => (
          <div className={'pc-part' + (myPc.parts[key] ? '' : ' blank')} key={key}>
            <small>{label}</small><b>{myPc.parts[key] || '미등록'}</b>
          </div>
        ))}
      </div>
    </div>
  )
}

type Tab = 'manual' | 'image' | 'purchase'

// "내 현재 PC": 직접 입력하거나, 받은 견적 점검의 이미지 인식 결과 또는 확정 견적서를 불러와 등록한다.
export default function MyPcPage({ myPc, onRegister, onReset, onUse }: {
  myPc: MyPc | null
  onRegister: (parts: PcParts, source: string, title: string) => boolean
  onReset: () => void
  onUse: () => void
}) {
  const { showToast } = useToast()
  const { savedSetups, loading } = useSetups()
  const setups = [...savedSetups].sort(newestFirst)
  const [tab, setTab] = useState<Tab>('manual')
  const [draft, setDraft] = useState<PcParts>({})
  const [selected, setSelected] = useState('')
  const [capabilities, setCapabilities] = useState<QuoteCapabilities | null>(null)
  const [imageFiles, setImageFiles] = useState<File[]>([])
  const [imageDraft, setImageDraft] = useState<PcParts>({})
  const [imageBusy, setImageBusy] = useState(false)
  const [imageError, setImageError] = useState('')
  const imageInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let alive = true
    api.quoteDrafts.capabilities().then(value => { if (alive) setCapabilities(value) }).catch(() => { if (alive) setImageError('이미지 인식 가능 여부를 확인하지 못했습니다.') })
    return () => { alive = false }
  }, [])

  const register = (parts: PcParts, source: string, title: string) => {
    if (!onRegister(parts, source, title)) return
    setDraft({}); setSelected('')
  }

  const addImages = (incoming: File[]) => {
    const maxFiles = capabilities?.maxFiles ?? 3
    const maxFileBytes = capabilities?.maxFileBytes ?? 10 * 1024 * 1024
    const supported = capabilities?.supportedTypes?.length ? capabilities.supportedTypes : ['image/png', 'image/jpeg', 'image/webp']
    const next = [...imageFiles]
    let skipped = ''
    for (const file of incoming) {
      if (next.length >= maxFiles) { skipped = `이미지는 최대 ${maxFiles}장까지 올릴 수 있어요.`; break }
      if (!supported.includes(file.type)) { skipped = 'PNG, JPEG, WebP 이미지만 올릴 수 있어요.'; continue }
      if (file.size > maxFileBytes) { skipped = `${file.name}은(는) ${Math.round(maxFileBytes / 1024 / 1024)}MB 이하여야 해요.`; continue }
      if (next.some(saved => saved.name === file.name && saved.size === file.size && saved.lastModified === file.lastModified)) continue
      next.push(file)
    }
    setImageFiles(next)
    setImageDraft({})
    setImageError(skipped)
  }
  const pickImages = (event: ChangeEvent<HTMLInputElement>) => {
    addImages([...event.target.files ?? []])
    event.target.value = ''
  }
  const dropImages = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    addImages([...event.dataTransfer.files])
  }
  const recognizeImages = async () => {
    if (!imageFiles.length || imageBusy) return
    setImageBusy(true); setImageError('')
    try {
      const result = await api.quoteDrafts.create({ images: imageFiles })
      const recognized: PcParts = {}
      for (const [category, selectedId] of Object.entries(result.selectedItemByCategory)) {
        const key = pcKey(category)
        const item = result.items.find(candidate => candidate.id === selectedId)
        if (key && item) recognized[key] = item.matchedName || item.name
      }
      for (const item of result.items) {
        const key = pcKey(item.category)
        if (key && !recognized[key]) recognized[key] = item.matchedName || item.name
      }
      setImageDraft(recognized)
      if (Object.keys(recognized).length) showToast(`${Object.keys(recognized).length}개 부품을 인식했어요. 제품명을 확인해 주세요.`)
      else setImageError('인식된 본체 부품이 없습니다. 다른 견적 이미지를 올려주세요.')
    } catch (caught) {
      setImageError(errorMessage(caught, '견적 이미지를 인식하지 못했습니다.'))
    } finally { setImageBusy(false) }
  }

  return (
    <>
      <Hero icon="🖥️" title="내 현재 PC" description="지금 쓰는 PC를 직접 적거나, 확정한 견적서를 불러와 등록하세요. 받은 견적 점검의 기준으로 쓸 수 있어요." />
      <section className="mp-section"><CurrentPc myPc={myPc} onUse={onUse} onReset={onReset} /></section>
      <section className="mp-section">
        <div className="pc-tabs">
          <button type="button" className={tab === 'manual' ? 'on' : ''} onClick={() => setTab('manual')}>✍ 직접 입력</button>
          <button type="button" className={tab === 'image' ? 'on' : ''} onClick={() => setTab('image')}>📷 이미지로 인식</button>
          <button type="button" className={tab === 'purchase' ? 'on' : ''} onClick={() => setTab('purchase')}>🧾 저장한 견적에서 불러오기</button>
        </div>
        <div className="pc-body">
          {tab === 'manual' && (
            <>
              <p className="pc-hint">알고 있는 부품만 적어도 괜찮아요. 비워 둔 항목은 미등록으로 저장돼요. 이 브라우저에만 저장됩니다.</p>
              <div className="pc-form">
                {PC_FIELDS.map(([key, label]) => (
                  <label className="pc-field" key={key}>
                    <span>{label}</span>
                    <input className="pc-input" type="text" maxLength={80} value={draft[key] ?? ''} placeholder={`${label} 제품명을 입력하세요`}
                      onChange={event => setDraft(previous => ({ ...previous, [key]: event.target.value }))} />
                  </label>
                ))}
              </div>
              <div className="pc-actions"><button className="mp-btn primary" type="button" onClick={() => register(draft, '직접 입력', '')}>내 PC로 등록</button></div>
            </>
          )}

          {tab === 'image' && (
            <>
              <p className="pc-hint">받은 견적 점검과 같은 이미지 인식 기능으로 견적서의 본체 부품을 채웁니다. 인식 결과를 확인하고 수정한 뒤 등록해 주세요.</p>
              <div className="pc-image-drop" onDragOver={event => event.preventDefault()} onDrop={dropImages}>
                <input ref={imageInput} hidden type="file" multiple accept="image/png,image/jpeg,image/webp" onChange={pickImages} />
                <button className="mp-btn" type="button" onClick={() => imageInput.current?.click()} disabled={capabilities?.imageExtraction === false}>사진 선택</button>
                <strong>PNG·JPEG·WebP · 최대 {capabilities?.maxFiles ?? 3}장</strong>
                <span>{capabilities === null ? '서버의 이미지 인식 상태를 확인하고 있어요.' : capabilities.imageExtraction ? '견적서 앞·뒷면과 상세 페이지를 함께 올릴 수 있어요.' : '현재 서버에서 이미지 인식을 사용할 수 없습니다.'}</span>
              </div>
              {imageFiles.length > 0 && <div className="pc-image-files">{imageFiles.map((file, index) => <div key={`${file.name}-${file.lastModified}`}><span>{index + 1}</span><b>{file.name}</b><button type="button" aria-label={`${file.name} 삭제`} onClick={() => { setImageFiles(current => current.filter(item => item !== file)); setImageDraft({}) }}>×</button></div>)}</div>}
              {imageError && <p className="pc-image-error" role="alert">{imageError}</p>}
              <div className="pc-actions"><button className="mp-btn primary" type="button" disabled={!imageFiles.length || imageBusy || capabilities?.imageExtraction === false} onClick={() => void recognizeImages()}>{imageBusy ? '인식 중…' : '이미지 인식하기'}</button></div>
              {Object.keys(imageDraft).length > 0 && <>
                <div className="pc-form pc-image-result">
                  {PC_FIELDS.map(([key, label]) => <label className="pc-field" key={key}><span>{label}</span><input className="pc-input" type="text" maxLength={80} value={imageDraft[key] ?? ''} placeholder={`${label} 제품명을 확인하세요`} onChange={event => setImageDraft(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}
                </div>
                <div className="pc-actions"><button className="mp-btn primary" type="button" onClick={() => register(imageDraft, '이미지 인식', '')}>인식 결과를 내 PC로 등록</button></div>
              </>}
            </>
          )}

          {tab === 'purchase' && (
            <>
              <p className="pc-hint">확정해서 저장한 견적서의 본체 부품을 내 현재 PC로 그대로 적용할 수 있어요.</p>
              <div className="pc-src-list">
                {setups.map(setup => {
                  const key = configKey(setup)
                  return (
                    <button key={key} type="button" className={'pc-src' + (selected === key ? ' on' : '')} onClick={() => setSelected(key)}>
                      <span className="pc-radio" />
                      <span className="pc-src-main">
                        <strong>{setup.title}</strong>
                        <small>구성 견적 · {dateText(setup.savedAt)} 확정</small>
                      </span>
                      <span className="pc-src-price">{wonFmt(setupTotal(setup))}</span>
                    </button>
                  )
                })}
                {setups.length === 0 && (
                  <div className="mp-empty-card">
                    <strong>{loading ? '불러오는 중이에요' : '불러올 견적서가 없어요'}</strong>
                    {!loading && <><span>견적을 확정하면 여기서 불러올 수 있어요.</span><Link className="mp-btn primary mp-link-btn" to="/start">새 견적 받기</Link></>}
                  </div>
                )}
              </div>
              <div className="pc-actions">
                <button className="mp-btn primary" type="button" disabled={!selected} onClick={() => {
                  const setup = setups.find(item => configKey(item) === selected)
                  if (setup) register(setupToPcParts(setup), '구성 견적', setup.title)
                }}>선택한 구성 적용하기</button>
              </div>
            </>
          )}
        </div>
      </section>
    </>
  )
}
