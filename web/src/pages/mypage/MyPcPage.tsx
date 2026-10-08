import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSetups } from '../../state/SetupsContext'
import { wonFmt } from '../../utils/format'
import { Hero } from './parts'
import { PC_FIELDS, PC_PLACEHOLDERS, configKey, dateText, newestFirst, setupToPcParts, setupTotal, type MyPc, type PcParts } from './model'

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

type Tab = 'manual' | 'purchase'

// "내 현재 PC": 직접 입력하거나, 확정한 견적서를 불러와 등록한다. (이미지 인식은 아직 서버 기능이 없어 준비 중)
export default function MyPcPage({ myPc, onRegister, onReset, onUse }: {
  myPc: MyPc | null
  onRegister: (parts: PcParts, source: string, title: string) => boolean
  onReset: () => void
  onUse: () => void
}) {
  const { savedSetups, loading } = useSetups()
  const setups = [...savedSetups].sort(newestFirst)
  const [tab, setTab] = useState<Tab>('manual')
  const [draft, setDraft] = useState<PcParts>({})
  const [selected, setSelected] = useState('')

  const register = (parts: PcParts, source: string, title: string) => {
    if (!onRegister(parts, source, title)) return
    setDraft({}); setSelected('')
  }

  return (
    <>
      <Hero icon="🖥️" title="내 현재 PC" description="지금 쓰는 PC를 직접 적거나, 확정한 견적서를 불러와 등록하세요. 받은 견적 점검의 기준으로 쓸 수 있어요." />
      <section className="mp-section"><CurrentPc myPc={myPc} onUse={onUse} onReset={onReset} /></section>
      <section className="mp-section">
        <div className="pc-tabs">
          <button type="button" className={tab === 'manual' ? 'on' : ''} onClick={() => setTab('manual')}>✍ 직접 입력</button>
          <button type="button" className="mp-pc-tab-soon" disabled title="이미지 인식은 준비 중이에요">📷 이미지로 인식 (준비 중)</button>
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
                    <input className="pc-input" type="text" maxLength={80} value={draft[key] ?? ''} placeholder={`예: ${PC_PLACEHOLDERS[key]}`}
                      onChange={event => setDraft(previous => ({ ...previous, [key]: event.target.value }))} />
                  </label>
                ))}
              </div>
              <div className="pc-actions"><button className="mp-btn primary" type="button" onClick={() => register(draft, '직접 입력', '')}>내 PC로 등록</button></div>
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
