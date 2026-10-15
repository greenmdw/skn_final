import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { PeripheralFeelQuote, PeripheralItem } from '../api'
import { wonFmt } from '../utils/format'
import { aspectLabel, reviewEvidence } from '../utils/peripherals'
import {
  candidateViews, requestedEvidence, specDifferences, topAxes, type CandidateView, type RequestedEvidence,
} from '../utils/peripheralResult'

const COMMUNITY_REVIEW_BOARD = '/community?view=board&board=review'
const HERO_QUOTES = 2
const ALT_QUOTES = 1
const NO_FEEL_QUOTE_LIMIT = 2

/** 요구사양 태그 문구: 값만("144 이상") 보이면 무엇인지 알 수 없다. 예·아니오 값은 라벨만("무선 연결") 쓴다. */
const requirementText = (row: { label: string; value: string }) => (row.value === '예' ? row.label : `${row.label} ${row.value}`)

/** 제품 이미지. 주소가 없거나 불러오지 못하면 브랜드 이름과 "이미지 준비 중"을 같은 크기로 보인다. */
function ProductImage({ url, name, brand }: { url: string | null; name: string; brand: string }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [url])
  if (url && !failed) {
    return <div className="pr-image"><img src={url} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} /></div>
  }
  return <div className="pr-image placeholder" role="img" aria-label={`${name} 이미지 준비 중`}><b>{brand || '제품'}</b><small>이미지 준비 중</small></div>
}

function QuoteLine({ quote }: { quote: PeripheralFeelQuote }) {
  return <div className="pr-quote">
    <p>“{quote.sentence}”{quote.isExample && <em className="pf-example-tag">예시 글</em>}</p>
    <Link to={`/community?view=post&post=${encodeURIComponent(quote.postId)}&quote=${encodeURIComponent(quote.quoteId)}`} state={{ quoteSentence: quote.sentence }}>원문 보기 →</Link>
  </div>
}

/** "요청하신 ○○": 사용자가 말한 항목의 근거. 스펙으로 확인된 것, 사용기 인용, 사용기가 없으면 외부 리뷰 순이다. */
function RequestedBox({ evidence }: { evidence: RequestedEvidence }) {
  return <div className="pr-req">
    <div className="pr-req-head">
      <b>요청하신 “{evidence.label}”</b>
      {evidence.note && <span className={'pr-tag ' + (evidence.note.few ? 'warn' : 'ok')}>{evidence.note.text}</span>}
      {evidence.external && <span className="pr-tag warn">
        외부 리뷰 기준 · {evidence.external.label} {evidence.external.total}건 중 긍정 {evidence.external.positive}건
      </span>}
    </div>
    {evidence.quotes.map(quote => <QuoteLine quote={quote} key={quote.quoteId} />)}
    {evidence.external?.quote && <div className="pr-quote"><p>“{evidence.external.quote}”</p></div>}
    {evidence.specChecks.length > 0 && <div className="pr-checks">
      {evidence.specChecks.map(check => <span className={check.ok ? 'ok' : 'no'} key={check.key}>{check.text} {check.ok ? '✓' : '✕'}</span>)}
    </div>}
  </div>
}

function RequestedBoxes({ view, maxQuotes }: { view: CandidateView; maxQuotes: number }) {
  const blocks = view.requested.map(requested => requestedEvidence(view, requested, maxQuotes)).filter((block): block is RequestedEvidence => block !== null)
  if (!blocks.length) return null
  return <>{blocks.map(block => <RequestedBox evidence={block} key={block.label} />)}</>
}

/** 근거 전체 보기: 사용기 항목 타일(요청한 항목 먼저)과 외부 리뷰 누적 막대 */
function EvidencePanel({ view }: { view: CandidateView }) {
  const requestedCodes = new Set(view.requested.flatMap(requested => requested.feelCodes))
  const attributes = (view.feel?.attributes ?? [])
    .filter(attribute => attribute.state !== 'external_only')
    .sort((a, b) => Number(requestedCodes.has(b.code)) - Number(requestedCodes.has(a.code)))
  const few = attributes.some(attribute => attribute.state === 'few_same_condition')
  const external = reviewEvidence(view.reviewAspects, 8)
  return <div className="pr-evidence">
    {attributes.length === 0 && <div className="pr-empty">
      <span>이 제품의 사용기가 아직 없어요. 아래 외부 리뷰와 스펙을 기준으로 골랐어요.</span>
      <Link to={COMMUNITY_REVIEW_BOARD}>첫 사용기 남기기 →</Link>
    </div>}
    {attributes.length > 0 && <section>
      <div className="pr-sec-head">
        <h5>사용기{view.feel?.basisText ? ` · ${view.feel.basisText}` : ''}</h5>
        {view.feel?.recentAuthors != null && <span>최근 3개월 {view.feel.recentAuthors}명</span>}
        {few && <span className="pr-tag warn">아직 글이 적어 참고용이에요</span>}
      </div>
      <div className="pr-tiles">
        {attributes.map(attribute => <div className={'pr-tile' + (requestedCodes.has(attribute.code) ? ' req' : '')} key={attribute.code}>
          <div className="pr-tile-head"><b>{attribute.label}</b>{requestedCodes.has(attribute.code) && <span className="pr-tag req">요청</span>}</div>
          <span className="pr-tile-text">{attribute.text}</span>
          {attribute.quotes.slice(0, NO_FEEL_QUOTE_LIMIT).map(quote => <div className="pr-tile-quote" key={quote.quoteId}>
            <p>“{quote.sentence}”{quote.isExample && <em className="pf-example-tag">예시 글</em>}</p>
            <Link to={`/community?view=post&post=${encodeURIComponent(quote.postId)}&quote=${encodeURIComponent(quote.quoteId)}`} state={{ quoteSentence: quote.sentence }}>원문 보기 →</Link>
          </div>)}
        </div>)}
      </div>
    </section>}
    {external.length > 0 && <section>
      <div className="pr-sec-head"><h5>외부 리뷰</h5><span>판매처 후기를 평가 기준별로 집계했어요</span></div>
      <div className="pr-ext">
        {external.map(entry => {
          const total = Math.max(entry.total, 1)
          return <div className="pr-ext-row" key={entry.aspectCode}>
            <b>{aspectLabel(entry.aspectCode)}</b>
            <span className="pr-stack" aria-hidden="true">
              <i className="p" style={{ width: `${(entry.positive / total) * 100}%` }} />
              <i className="m" style={{ width: `${(entry.mixed / total) * 100}%` }} />
              <i className="n" style={{ width: `${(entry.negative / total) * 100}%` }} />
            </span>
            <span className="pr-ext-num">{entry.total}건 중 긍정 {entry.positive} · 부정 {entry.negative}{entry.mixed > 0 ? ` · 엇갈림 ${entry.mixed}` : ''}{entry.dissent && <em className="pr-tag warn">의견이 갈려요</em>}</span>
            {entry.quote && <p className="pr-ext-quote">“{entry.quote}”</p>}
          </div>
        })}
      </div>
      <div className="pr-legend"><span><i className="p" />긍정</span><span><i className="m" />엇갈림</span><span><i className="n" />부정</span></div>
    </section>}
  </div>
}

interface Props {
  item: PeripheralItem
  /** 큰 카드에 올린 제품의 이름. null 이면 1위 */
  chosenName: string | null
  picked: boolean
  onChoose: (name: string | null) => void
  onTogglePicked: () => void
}

/** 한 품목의 추천 결과: 지금 보는 제품(큰 카드) + 다른 선택지. "이 제품으로 바꾸기"를 누르면 큰 카드가 그 제품으로 바뀐다. */
export default function PeripheralResultSection({ item, chosenName, picked, onChoose, onTogglePicked }: Props) {
  const views = candidateViews(item)
  const hero = views.find(view => view.name === chosenName) ?? views[0]
  const others = views.filter(view => view !== hero)
  const swapped = hero.rank !== 1
  const [open, setOpen] = useState(false)
  const heroRef = useRef<HTMLElement | null>(null)
  const firstRender = useRef(true)

  // 다른 제품으로 바꾸면 큰 카드 위치로 돌아가 바뀐 모습을 보여 주고, 근거 패널은 접는다.
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return }
    setOpen(false)
    heroRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [hero.name])

  const axes = topAxes(hero.scoreAxes)
  // 사용자가 말한 항목의 근거가 하나도 보이지 않을 때만, 서버가 준 조건 충족 태그(✓)를 대신 보인다.
  const hasRequested = hero.requested.some(requested => requestedEvidence(hero, requested, HERO_QUOTES) !== null)
  const requirementTags = !hasRequested && !swapped ? item.requirement.filter(row => row.key !== 'resolution_assumed') : []
  const assumedNotes = swapped ? [] : item.requirement.filter(row => row.key === 'resolution_assumed')
  const failedChecks = swapped ? [] : item.checks.filter(check => check.state === 'fail')
  const candidateCount = hero.pricePosition?.of ?? null

  return <section className="pf-kind-result pr-section">
    <div className="pf-kind-heading">
      <h2>{item.kindLabel}</h2>
      <span>{candidateCount ? `조건에 맞는 후보 ${candidateCount}개 중 ${hero.rank}위` : '조건과 리뷰 근거에 가장 잘 맞는 제품'}</span>
      <button type="button" className="pr-link-btn" onClick={onTogglePicked}>{picked ? '견적에서 빼기' : '견적에 다시 담기'}</button>
    </div>

    <article className={'pr-hero' + (swapped ? ' swapped' : '')} ref={heroRef}>
      <div className="pr-hero-side">
        <span className={'pr-best' + (swapped ? ' chosen' : '')}>{swapped ? `직접 고른 제품 · 추천 ${hero.rank}위` : '가장 잘 맞아요'}</span>
        <ProductImage url={hero.imageUrl} name={hero.name} brand={hero.brand} />
        <strong className="pr-price pl-mono">{wonFmt(hero.price)}</strong>
        {swapped && <span className="pr-rank-note">1위보다 {wonFmt(Math.abs(hero.price - item.price))} {hero.price < item.price ? '저렴' : hero.price > item.price ? '비쌈' : '같은 가격'}</span>}
      </div>
      <div className="pr-hero-body">
        <div>
          <h3>{hero.name}</h3>
          {hero.brand && <span className="pr-brand">{hero.brand}</span>}
        </div>
        {hero.keySpecs.length > 0 && <div className="pr-specs">{hero.keySpecs.map(spec => <span key={spec.key} title={spec.label}>{spec.value}</span>)}</div>}
        {(requirementTags.length > 0 || failedChecks.length > 0) && <div className="pf-fit-tags">
          {requirementTags.map(row => <span key={row.key}>✓ {requirementText(row)}</span>)}
          {failedChecks.map(check => <span className="no" key={check.axis}>✕ {check.label}</span>)}
        </div>}
        {assumedNotes.map(row => <div className="pf-weak-note" key={row.key}>{row.value}</div>)}
        <RequestedBoxes view={hero} maxQuotes={HERO_QUOTES} />
        {axes.length > 0 && <div className="pr-reasons">
          <h4>이 제품이 뽑힌 이유</h4>
          {axes.map(axis => <div className="pr-reason" key={axis.axis}>
            <b>{axis.label}</b>
            <span className="pr-bar" aria-hidden="true"><i style={{ width: `${Math.round(axis.value * 100)}%` }} /></span>
            <small>
              {axis.axis === '가격' && hero.pricePosition
                ? `후보 ${hero.pricePosition.of}개 중 ${hero.pricePosition.rank}번째로 저렴`
                : `${Math.round(axis.value * 100)}점`} · 비중 {Math.round(axis.weight * 100)}%
            </small>
          </div>)}
        </div>}
        <div className="pr-foot">
          <button type="button" className="pr-toggle" aria-expanded={open} onClick={() => setOpen(previous => !previous)}>근거 전체 보기 {open ? '▴' : '▾'}</button>
          {hero.productUrl && <a className="pr-link" href={hero.productUrl} target="_blank" rel="noreferrer">상품 페이지로 이동 ↗</a>}
        </div>
        {open && <EvidencePanel view={hero} />}
        <div className="pf-card-foot">{item.priceNote && <span>{item.priceNote}</span>}</div>
      </div>
    </article>

    {others.length > 0 && <>
      <div className="pr-alts-head">
        <h4>다른 선택지</h4>
        <span>“이 제품으로 바꾸기”를 누르면 위의 큰 카드가 그 제품으로 바뀌어요</span>
      </div>
      <div className="pr-alts">
        {others.map(view => {
          const diff = view.price - hero.price
          const differences = specDifferences(view, hero)
          const canChoose = Boolean(view.variantId) || view.rank === 1
          return <article className="pr-alt" key={view.name}>
            <div className="pr-alt-top">
              <ProductImage url={view.imageUrl} name={view.name} brand={view.brand} />
              <div className="pr-alt-info">
                <h4><span className="pr-rank">추천 {view.rank}위</span>{view.name}</h4>
                <strong className="pr-alt-price pl-mono">{wonFmt(view.price)}</strong>
                <span className="pr-diff">지금 보는 제품보다 <b className={diff < 0 ? 'cheap' : diff > 0 ? 'pricey' : ''}>{diff === 0 ? '같은 가격' : `${wonFmt(Math.abs(diff))} ${diff < 0 ? '저렴' : '비쌈'}`}</b></span>
              </div>
            </div>
            {view.keySpecs.length > 0 && <div className="pr-specs">{view.keySpecs.map(spec => <span key={spec.key} title={spec.label}>{spec.value}</span>)}</div>}
            {differences.length > 0 && <div className="pr-delta"><b>다른 점</b>
              {differences.map(entry => <span key={entry.key}>{entry.label} {entry.value} <em>(지금 {entry.baseValue})</em></span>)}
            </div>}
            <RequestedBoxes view={view} maxQuotes={ALT_QUOTES} />
            <div className="pr-alt-actions">
              {canChoose
                ? <button type="button" className="pr-swap" onClick={() => onChoose(view.rank === 1 ? null : view.name)}>이 제품으로 바꾸기</button>
                : <button type="button" className="pr-swap" disabled title="서버가 이 제품의 식별 정보를 아직 주지 않아 견적에 담을 수 없어요.">선택 준비 중</button>}
              {view.productUrl && <a className="pr-link sm" href={view.productUrl} target="_blank" rel="noreferrer">상품 보기 ↗</a>}
            </div>
          </article>
        })}
      </div>
    </>}
  </section>
}
