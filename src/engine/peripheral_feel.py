"""주변기기 체감 점수(체감 적합도 R) 계산 — 개발_확정사양.md 4~6장.

이 모듈은 순수 계산이다. DB·언어 모델·네트워크를 모른다. 입력은 (1) 후보와 그 후보에 붙은 외부 리뷰 집계
(`Candidate.review_detail.contributions` 의 긍정·부정 수), (2) 커뮤니티 사용기에서 뽑은 관측 목록
(`FeelObservation`, 구현 순서 5가 채운다), (3) 요청자의 입력(`Interpretation`)과 그 풀이(`ResolvedKind`)이다.
관측이 하나도 없으면 외부 리뷰만으로 계산한다 — 출발값 그대로이고, 목적에 맞춰 속성 가중치(α)만 달라진다.

## 계산(사양 6장)

```
m   = 그 종류·큰 속성의 외부 리뷰 전체 평균(긍정 / (긍정 + 부정))            외부 연결이 없으면 default_m
외부 점수 = (긍정 + k0·m) / (긍정 + 부정 + k0)
B   = (커뮤니티 전체 긍정 + kb·m) / (커뮤니티 전체 평가 수 + kb)
Q0  = B + (외부 점수 − m)                       외부 리뷰가 없는 제품은 Q0 = B

같은 조건 묶음 / 나머지 묶음(속성별 기준 `group`)
Q나머지 = (나머지 긍정 + k·Q0) / (나머지 전체 + k)
Q      = (같은 조건 긍정 + k·Q나머지) / (같은 조건 전체 + k)
성향   = 같은 식, 출발값은 0.5, "긍정" 자리는 요청자가 고른 쪽과 같은 쪽
R      = Σ α·값        α 합 1. 요청자가 취향을 고르지 않은 성향은 빼고 α 를 다시 나눈다
```

## 세는 규칙(사양 5장)

한 작성자 × 한 제품 × 한 속성 = 한 표. 같은 사람의 글이 여럿이면 최근 글을 쓰고, 상황에 따라 다르게 평가했으면
요청자의 목적·상황과 맞는 평가를 쓴다. 맞는 평가가 없고 방향이 갈리면 표로 세지 않는다("상황에 따라 다르다").
실제 사용기가 하나라도 있는 종류는 예시 글을 쓰지 않는다.

내구성의 "사용 기간 6개월 이상" 같은 글감 조건은 추출 단계(구현 순서 5)가 거른다. 여기서는 받은 관측을 센다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from src.dto import Candidate, FeelAttributeDetail, FeelDetail, FeelQuote
from src.engine.peripheral_intent import Interpretation, ResolvedKind
from src.engine.peripheral_rules import feel_attributes, feel_config, load_peripheral_rules, situations


@dataclass(frozen=True)
class FeelObservation:
    """사용기 한 문장에서 뽑은 관측 하나. 저장·추출은 구현 순서 5가 맡고 이 모듈은 읽기만 한다.

    - `direction`: 평가 속성이면 good/bad/mixed(엇갈림), `side`: 성향 축이면 그 축의 쪽 코드.
    - `purposes`·`situations`·`hand_size`: 작성자 조건(글에서 읽은 것, 밝히지 않았으면 비어 있다).
    - `evaluated_in`: 이 평가가 나온 상황 코드(작성자가 상황별로 다르게 평가했을 때 가르는 데 쓴다).
    """

    author_id: str
    product_id: str
    attribute: str
    direction: str | None = None
    side: str | None = None
    purposes: frozenset[str] = frozenset()
    situations: frozenset[str] = frozenset()
    hand_size: str | None = None
    evaluated_in: frozenset[str] = frozenset()
    written_at: datetime | None = None
    is_example: bool = False
    # 근거 표시용(점수 계산에는 쓰지 않는다)
    post_id: str | None = None
    quote_id: str | None = None
    sentence: str | None = None
    photo_url: str | None = None


@dataclass
class _Tally:
    good: int = 0
    bad: int = 0
    mixed: int = 0

    @property
    def total(self) -> int:
        return self.good + self.bad


@dataclass
class _Requester:
    tags: frozenset[str]            # 목적 + 묶는 기준으로 쓰는 상황
    quiet_flags: frozenset[str]     # quiet_place / mic
    bright: bool
    hand_size: str | None
    design: bool
    sides: dict[str, str] = field(default_factory=dict)       # 성향 축 → 요청자가 고른 쪽
    boosted: set[str] = field(default_factory=set)            # 중요도를 올릴 속성 코드


# ── 요청자 ─────────────────────────────────────────────────────────────────
def _requester(kind: str, interp: Interpretation, resolved: ResolvedKind | None, cfg: dict, rules: dict) -> _Requester:
    attrs = feel_attributes(kind, rules)
    sit = situations(rules)
    grouping_situations = {s for s in interp.situations if sit.get(s, {}).get("same_condition_group")}
    tags = frozenset({*interp.purposes, *grouping_situations})
    quiet_flags = frozenset(set(interp.situations) & {"quiet_place", "mic"})
    design = "design" in interp.situations

    boosted: set[str] = set()
    sides: dict[str, str] = {}
    if resolved is not None:
        for label in resolved.feel:
            boosted.update(code for code, e in attrs.items() if label in e["aliases"])
        for label in resolved.taste:
            for code, entry in attrs.items():
                if entry["type"] == "taste" and label in entry["taste_labels"]:
                    sides[code] = entry["taste_labels"][label]
    if quiet_flags:
        boosted.update(code for code, e in attrs.items() if "sound" in e.get("tags", []))
    if design:
        boosted.add("build")
    return _Requester(tags=tags, quiet_flags=quiet_flags, bright="bright_room" in interp.purposes,
                      hand_size=interp.hand_size, design=design, sides=sides, boosted=boosted)


_HAND_PHRASE = {"small": "손이 작은 사용자", "medium": "손 크기가 보통인 사용자", "large": "손이 큰 사용자"}


def feel_group_phrase(group: str, interp: Interpretation, resolved: ResolvedKind | None, rules: dict) -> str | None:
    """요청자가 이 속성의 같은 조건 묶음을 정할 만큼 밝힌 조건을 사람이 읽는 말로. 밝히지 않았으면 None."""
    if group == "hand":
        return _HAND_PHRASE.get(interp.hand_size or "")
    if group == "quiet":
        parts = [text for flag, text in (("quiet_place", "조용한 곳에서 쓰는"), ("mic", "마이크를 쓰는"))
                 if flag in interp.situations]
        return f"{' · '.join(parts)} 사용자" if parts else None
    if group == "bright":
        return "밝은 방에서 쓰는 사용자" if "bright_room" in interp.purposes else None
    if group == "purpose":
        if resolved is not None and resolved.purposes:
            return f"'{resolved.purposes[0]['label']}' 목적의 사용자"
        sit = situations(rules)
        for code in interp.situations:
            if sit.get(code, {}).get("same_condition_group"):
                return f"'{sit[code]['label']}' 상황의 사용자"
    return None


def _alphas(kind: str, req: _Requester, cfg: dict, rules: dict) -> dict[str, float]:
    attrs = feel_attributes(kind, rules)
    raw: dict[str, float] = {}
    for code, entry in attrs.items():
        if entry["type"] == "taste":
            if code not in req.sides:        # 요청자가 취향을 고르지 않은 성향은 뺀다(사양 6.4)
                continue
        elif entry.get("only_when") == "design" and not req.design:
            continue
        raw[code] = cfg["purpose_boost"] if code in req.boosted else 1.0
    total = sum(raw.values())
    return {code: value / total for code, value in raw.items()} if total else {}


# ── 표 세기 ────────────────────────────────────────────────────────────────
def select_corpus(observations: Iterable[FeelObservation]) -> tuple[list[FeelObservation], str]:
    """실제 사용기가 하나라도 있으면 실제만, 아니면 예시 글만 쓴다. 두 번째 값은 근거의 성격."""
    obs = list(observations)
    real = [o for o in obs if not o.is_example]
    if real:
        return real, "community"
    if obs:
        return obs, "example"
    return [], "external_only"


def _vote_key(o: FeelObservation) -> Any:
    return o.direction if o.direction is not None else o.side


def _dedupe(observations: list[FeelObservation], req: _Requester) -> tuple[list[FeelObservation], dict[tuple, int]]:
    """한 작성자 × 한 제품 × 한 속성 = 한 표(사양 5장). 두 번째 값은 "상황에 따라 다르다"고 한 건수."""
    groups: dict[tuple[str, str, str], list[FeelObservation]] = {}
    for o in observations:
        groups.setdefault((o.author_id, o.product_id, o.attribute), []).append(o)

    def _when(o: FeelObservation) -> datetime:
        return o.written_at.replace(tzinfo=None) if o.written_at else datetime.min

    def _latest(items: list[FeelObservation]) -> FeelObservation:
        return max(items, key=_when)

    votes: list[FeelObservation] = []
    situational: dict[tuple, int] = {}
    for key, items in groups.items():
        if len(items) == 1:
            votes.append(items[0])
            continue
        if not any(o.evaluated_in for o in items):
            votes.append(_latest(items))      # 상황 구분 없이 여러 번 쓴 같은 사람 — 최근 글(사양 5장)
            continue
        matching = [o for o in items if o.evaluated_in & req.tags]
        if matching:
            votes.append(_latest(matching))
        elif len({_vote_key(o) for o in items}) == 1:
            votes.append(_latest(items))
        else:
            situational[key[1:]] = situational.get(key[1:], 0) + 1
    return votes, situational


def _applies(group: str, req: _Requester) -> bool:
    """요청자가 이 속성의 같은 조건 묶음을 정할 만큼 조건을 밝혔는가."""
    if group == "hand":
        return req.hand_size is not None
    if group == "quiet":
        return bool(req.quiet_flags)
    if group == "bright":
        return req.bright
    if group == "purpose":
        return bool(req.tags)
    return False


def _same_condition(group: str, o: FeelObservation, req: _Requester) -> bool:
    if group == "hand":
        return o.hand_size == req.hand_size
    if group == "quiet":
        return bool(o.situations & req.quiet_flags)
    if group == "bright":
        return "bright_room" in o.purposes
    return bool((o.purposes | o.situations) & req.tags)


def _blend(start: float, tally: _Tally, k: float) -> float:
    return (tally.good + k * start) / (tally.total + k)


def _split(counts: dict[Any, int], ratio: float) -> bool:
    """두 쪽 이상에 작성자가 있고 적은 쪽이 전체의 ratio 이상이면 갈린다(사양 6.3)."""
    total = sum(counts.values())
    if total == 0 or len([c for c in counts.values() if c > 0]) < 2:
        return False
    return min(c for c in counts.values() if c > 0) / total >= ratio


# ── 외부 리뷰 ──────────────────────────────────────────────────────────────
def _external_counts(cand: Candidate) -> dict[str, tuple[int, int]]:
    detail = cand.review_detail
    if detail is None:
        return {}
    out: dict[str, list[int]] = {}
    for c in detail.contributions:
        acc = out.setdefault(c.aspect_code, [0, 0])
        acc[0] += c.p
        acc[1] += c.n
    return {aspect: (p, n) for aspect, (p, n) in out.items()}


def _pooled_m(pool: list[Candidate], cfg: dict) -> dict[str, float]:
    sums: dict[str, list[int]] = {}
    for cand in pool:
        for aspect, (p, n) in _external_counts(cand).items():
            acc = sums.setdefault(aspect, [0, 0])
            acc[0] += p
            acc[1] += n
    return {a: p / (p + n) for a, (p, n) in sums.items() if p + n > 0}


# ── 계산 ───────────────────────────────────────────────────────────────────
def compute_feel(
    kind: str, pool: list[Candidate], targets: list[Candidate], interp: Interpretation,
    resolved: ResolvedKind | None, observations: Iterable[FeelObservation], rules: dict | None = None,
    *, now: datetime | None = None,
) -> dict[str, FeelDetail]:
    """`targets` 각각의 체감 적합도 {product_key: FeelDetail}. `pool` 은 m(외부 평균)을 구하는 그 종류의 전체 후보다."""
    rules = rules or load_peripheral_rules()
    cfg = feel_config(rules)
    attrs = feel_attributes(kind, rules)
    if cfg is None or not attrs:
        return {}

    req = _requester(kind, interp, resolved, cfg, rules)
    alphas = _alphas(kind, req, cfg, rules)
    corpus, basis = select_corpus(o for o in observations if o.attribute in attrs)
    votes, situational = _dedupe(corpus, req)
    m_by_aspect = _pooled_m(pool, cfg)
    k, kb, ratio = cfg["k"], cfg["kb"], cfg["split_ratio"]
    since = (now or datetime.now()).replace(tzinfo=None) - timedelta(days=30.4375 * cfg["recent_months"])
    recent_authors: dict[str, set[str]] = {}
    for o in corpus:
        if o.written_at is not None and o.written_at.replace(tzinfo=None) >= since:
            recent_authors.setdefault(o.product_id, set()).add(o.author_id)

    def _m(attr: dict) -> float:
        return m_by_aspect.get(attr.get("external") or "", cfg["default_m"])

    # 기준 높이 B: 종류 전체의 커뮤니티 평가(제품 구분 없음)
    totals: dict[str, _Tally] = {}
    for v in votes:
        if v.direction in ("good", "bad"):
            t = totals.setdefault(v.attribute, _Tally())
            t.good += v.direction == "good"
            t.bad += v.direction == "bad"
    by_product: dict[str, list[FeelObservation]] = {}
    for v in votes:
        by_product.setdefault(v.product_id, []).append(v)

    out: dict[str, FeelDetail] = {}
    for cand in targets:
        external = _external_counts(cand)
        mine = by_product.get(cand.product_id or "", [])
        details: list[FeelAttributeDetail] = []
        used_community = False
        shown_posts: set[str] = set()      # 앞선 속성이 이미 인용한 글 — 뒤 속성은 다른 글을 먼저 보여 준다
        for code, alpha in alphas.items():
            entry = attrs[code]
            attr_votes = [v for v in mine if v.attribute == code]
            same, rest = _Tally(), _Tally()
            group = entry["group"]
            use_groups = _applies(group, req)

            if entry["type"] == "taste":
                wanted = req.sides[code]
                counts: dict[str, int] = {}
                for v in attr_votes:
                    if v.side is None:
                        continue
                    counts[v.side] = counts.get(v.side, 0) + 1
                    bucket = same if use_groups and _same_condition(group, v, req) else rest
                    bucket.good += v.side == wanted
                    bucket.bad += v.side != wanted
                start = cfg["neutral_taste"]
                split = _split(counts, ratio)
                top = max(counts, key=counts.get) if counts else None
                mismatch = bool(counts) and not split and top != wanted
                ext_p = ext_n = None
                ext_score = None
            else:
                aspect = entry.get("external")
                ext_p, ext_n = external.get(aspect, (0, 0)) if aspect else (0, 0)
                m = _m(entry)
                t = totals.get(code, _Tally())
                b = (t.good + kb * m) / (t.total + kb)
                if aspect and ext_p + ext_n > 0:
                    k0 = cfg["k0"].get(kind, {}).get(aspect, cfg["k0_default"])
                    ext_score = (ext_p + k0 * m) / (ext_p + ext_n + k0)
                    start = b + (ext_score - m)
                else:
                    ext_score = None
                    start = b
                start = min(1.0, max(0.0, start))
                counts_dir: dict[str, int] = {}
                mixed = 0
                for v in attr_votes:
                    if v.direction == "mixed":
                        mixed += 1
                        continue
                    if v.direction not in ("good", "bad"):
                        continue
                    counts_dir[v.direction] = counts_dir.get(v.direction, 0) + 1
                    bucket = same if use_groups and _same_condition(group, v, req) else rest
                    bucket.good += v.direction == "good"
                    bucket.bad += v.direction == "bad"
                split = _split(counts_dir, ratio)
                mismatch = False

            if use_groups:
                rest_q = _blend(start, rest, k)
                value = _blend(rest_q, same, k)
            else:
                value = _blend(start, _merge(same, rest), k)
            value = min(1.0, max(0.0, value))

            if same.total:
                state = "same_condition"
            elif rest.total:
                state = "other_condition"
            elif entry["type"] == "rating" and ext_p is not None and ext_p + (ext_n or 0) > 0:
                state = "external_only"
            else:
                state = "no_evidence"
            used_community = used_community or bool(same.total or rest.total)
            quotes = _quotes(attr_votes, group, use_groups, req, cfg["quotes_per_attribute"], shown_posts)
            details.append(FeelAttributeDetail(
                code=code, label=entry["label"], type=entry["type"], alpha=round(alpha, 4), value=round(value, 4),
                state=state, same_good=same.good, same_bad=same.bad, rest_good=rest.good, rest_bad=rest.bad,
                external_p=ext_p, external_n=ext_n,
                external_score=None if ext_score is None else round(ext_score, 4),
                split=split, mismatch=mismatch,
                situational=situational.get((cand.product_id or "", code), 0), quotes=quotes,
                side_counts=dict(counts if entry["type"] == "taste" else counts_dir),
            ))
        r_value = sum(d.alpha * d.value for d in details)
        out[cand.product_key] = FeelDetail(
            value=round(min(1.0, max(0.0, r_value)), 4), attributes=details,
            basis=basis if used_community else "external_only",
            recent_authors=len(recent_authors.get(cand.product_id or "", ())),
        )
    return out


def _quotes(votes: list[FeelObservation], group: str, use_groups: bool, req: _Requester, limit: int,
            shown_posts: set[str] | None = None) -> list[FeelQuote]:
    """속성의 표 가운데 문장이 있는 것을 같은 조건 먼저, 최근 순으로 `limit` 개.

    한 글이 여러 속성에 걸쳐 문장을 갖는 경우가 많아서(예시 글 한 편이 제품의 여러 면을 쓴다) 그대로 두면 같은 글이 속성마다
    되풀이해서 인용되고 "원문 보기"도 같은 글로 여러 번 걸린다. 그래서 **한 제품에서 한 글은 한 번만** 인용한다: 이 제품의 앞선
    속성이 이미 인용한 글(`shown_posts`)과 이 속성에서 이미 고른 글은 건너뛴다. 다른 글이 없으면 그 속성은 인용 없이 점수·건수 문구만
    보인다(근거 집계는 그대로다). 고른 글은 `shown_posts` 에 더한다."""
    usable = [o for o in votes if o.sentence and o.quote_id and o.post_id]
    def _recency(o: FeelObservation) -> float:
        return -o.written_at.replace(tzinfo=None).timestamp() if o.written_at else 0.0

    usable.sort(key=lambda o: (not (use_groups and _same_condition(group, o, req)), _recency(o)))
    seen = shown_posts if shown_posts is not None else set()
    picked: list[FeelObservation] = []
    for o in usable:                               # 같은 조건 먼저·최근 순 그대로, 이미 인용한 글은 건너뛴다
        if len(picked) >= limit:
            break
        if o.post_id not in seen:
            picked.append(o)
            seen.add(o.post_id)
    return [FeelQuote(quote_id=o.quote_id, post_id=o.post_id, sentence=o.sentence, is_example=o.is_example,
                      photo_url=o.photo_url) for o in picked]


def _merge(a: _Tally, b: _Tally) -> _Tally:
    return _Tally(good=a.good + b.good, bad=a.bad + b.bad, mixed=a.mixed + b.mixed)


def attach_feel(
    kind: str, pool: list[Candidate], kept: list[Candidate], values: dict, rules: dict | None = None,
) -> list[Candidate]:
    """`values` 의 견적 입력과 관측으로 `kept` 후보마다 `feel_detail` 을 채워 돌려준다.

    값(`values`): `peripheral_intent`(Interpretation), `peripheral_resolved`(종류 → ResolvedKind),
    `peripheral_feel_observations`(종류 → FeelObservation 목록, 없으면 외부 리뷰만으로 계산).
    체감 설정(`feel`)이 없는 규칙 파일이면 아무것도 바꾸지 않는다."""
    rules = rules or load_peripheral_rules()
    if feel_config(rules) is None or not kept:
        return kept
    interp = values.get("peripheral_intent") or Interpretation()
    resolved = (values.get("peripheral_resolved") or {}).get(kind)
    observations = (values.get("peripheral_feel_observations") or {}).get(kind, [])
    details = compute_feel(kind, pool, kept, interp, resolved, observations, rules, now=values.get("peripheral_now"))
    return [c.model_copy(update={"feel_detail": details[c.product_key]}) if c.product_key in details else c
            for c in kept]
