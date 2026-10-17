"""주변기기 [3-A] 하드 필터 · [3-B] 랭킹 · 조합 · 진입점 — 추천엔진 구현계획 §3.3 E11.

PC의 stage3a_hardfilter/stage3b_rank에 대응하는 주변기기 버전이다. 판정 자체는
`src/engine/spec_rules.py`(선언형 평가기)를 재사용하고, 이 모듈은 그 결과를 후보 목록에
적용하는 배선만 한다.

## [3-A] filter_candidates

`requirement.hard`(예: 모니터의 `resolution_class`/`refresh_min_hz`)를 spec_rules가 읽을
pref 목록으로 바꿔 Fail만 제외한다. **조건을 완화하지 않는다** — 남는 후보가 없으면 빈
리스트를 그대로 낸다(계획 §3.3 C6, "빈 결과 처리").

## [3-B] rank_candidates

점수 S = Σ(축 가중치 × 축 값) − Pending 감점 − 스펙 결손 감점 − 근거 부족 감점 (기획 3.1~3.8, `config/peripherals.yaml` `ranking`·`scoring`).
축은 스펙 기준(품목마다 3~4개) · 리뷰 · 가격 · 브랜드 · 무상AS 이다.

- 스펙 기준의 값은 그 기준의 스펙 키를 겨냥한 소프트 조건을 판정한 가중 평균이다(직접 말한 조건 가중 2, 목적에서 풀린 조건 1).
  조건이 없는 기준은 모든 후보가 0.5 라 후보를 가르지 않는다.
- 가중치는 품목별 기본값에서 시작해 ① 강조한 축 ×1.5 ② 직접 말한 소프트 조건이 있는 스펙 기준 ×2 를 곱하고 합 1로 맞춘다.
  하드 조건·예산 필터는 항상 먼저 적용되고(가중은 소프트 조건에만 영향), 점수는 코드가 정한다.
- 가격 값: 종류별 예산이 있으면 `1 - 가격/예산`, 없으면 후보 중앙값 대비 식(`_price_axis`).
- "리뷰" 축의 값은 체감 적합도 R 이다(`peripheral_feel`). 근거가 없으면 외부 리뷰로 계산한 R 이다.
- 근거 부족 감점: 리뷰 관측 n 이 5건 미만이면 `0.10 x (1 - n/5)`. 후보에서 빼지 않고 점수에서만 뺀다.

## 조합(choose)

종류별 예산 배분이 없으므로(계획 §3.3 "예산") `peripheral_budget_max`가 없으면 종류별
1위를 그대로 쓴다. 있으면 종류별 top-N(기본 5)의 곱을 전수 탐색해 예산 이하 중 점수 합이
최댓값인 조합을 고른다. 예산 안 조합이 하나도 없으면 결과를 비우지 않고 **최저가 조합 +
`counts["over_budget"]=1`** 로 낸다(계획 §4 "근사는 근사라고 보고한다").

## run_peripherals — 진입점

`requested_kinds(values)`가 비면 `status="skipped"`(기존 PC 결과 불변 원칙). 요청된
종류를 전부 돌려 하나도 못 골랐으면 `status="empty"`, 하나라도 골랐으면 `status="ready"`.

`pc_context`(선택, E12)를 주고 모니터를 골랐으면 `peripheral_cross`로 모니터↔PC 교차
검사를 돌려 `PeripheralPick.checks`를 채우고 그 쟁점을 `verify_per_item`에 더한다. PC
세트 신뢰도와는 무관하다 — 자세한 규칙은 `src/engine/peripheral_cross.py` 모듈 docstring.
"""
from __future__ import annotations

import itertools
import statistics
from typing import Any

from src.config import PENDING_SCORE_PENALTY
from src.dto import Candidate, PeripheralPick, PeripheralRequirement, PeripheralResult
from src.engine import LogFn, spec_rules
from src.engine.peripheral_feel import attach_feel
from src.engine.peripheral_requirement import build_requirements, monitor_notices
from src.engine.peripheral_rules import kind_def, load_peripheral_rules, ranking_def, requested_kinds, scoring_cfg

# requirement.hard 의 키 이름은 "판정 기준 이름"이지 후보 specs 키와 항상 같지 않다.
# resolution_class는 기준 이름과 specs 키가 같지만(peripheral_catalog.build_peripheral_specs가
# resolution_class를 그대로 채운다), refresh_min_hz는 "문턱값 이름"이고 실제 후보 spec 키는
# columns 매핑이 정한 refresh_hz다(config/peripherals.yaml kinds.monitor.columns.max_refresh_hz
# -> refresh_hz). 그래서 (기준 이름) -> (specs 키, 연산자) 표로 둔다 — 새 hard 키가 추가되면
# 여기 한 줄만 늘리면 된다(계획 §3.3 E11 "새 종류 추가가 파이썬 분기가 아니게"). 지금은
# monitor 하나뿐이라 항목도 둘뿐이다.
_HARD_KEY_TO_PREF: dict[str, tuple[str, str]] = {
    "resolution_class": ("resolution_class", "member_of"),
    "refresh_min_hz": ("refresh_hz", "min"),
}


def _hard_prefs(hard: dict[str, Any]) -> list[dict[str, Any]]:
    prefs = []
    for name, value in hard.items():
        spec_key, op = _HARD_KEY_TO_PREF[name]
        prefs.append({"key": spec_key, "op": op, "value": value})
    return prefs


def filter_candidates(
    kind: str, requirement: PeripheralRequirement, cands: list[Candidate], *, max_price: int | None = None,
    min_price: int | None = None,
) -> tuple[list[Candidate], dict[str, int]]:
    """[3-A]. hard·filters 조건이 없는 종류는 전부 Pass다. `filters`(사용자가 직접 말한 조건)는 hard 와 같이
    판정한다 — 값이 없으면 Pending 이고 탈락시키지 않는다. `max_price`(종류별 예산)를 넘는 후보와
    `min_price`(종류별 최소 가격) 미만인 후보는 뺀다 — 거르기만 하고 점수는 건드리지 않는다."""
    prefs = _hard_prefs(requirement.hard) + list(requirement.filters)
    kept: list[Candidate] = []
    counts = {"pool": len(cands), "pass": 0, "fail": 0, "pending": 0, "over_price": 0}
    if min_price is not None:
        counts["under_price"] = 0
    for cand in cands:
        if min_price is not None and cand.price < min_price:
            counts["under_price"] += 1
            continue
        if max_price is not None and cand.price > max_price:
            counts["over_price"] += 1
            continue
        if not prefs:
            kept.append(cand.model_copy(update={"verdict": "Pass", "reasons": ["PASS"]}))
            counts["pass"] += 1
            continue
        verdict, reasons = spec_rules.evaluate_all(prefs, cand.specs)
        judged = cand.model_copy(update={"verdict": verdict, "reasons": reasons or ["PASS"]})
        if verdict == "Fail":
            counts["fail"] += 1
            continue
        counts["pending" if verdict == "Pending" else "pass"] += 1
        kept.append(judged)
    return kept, counts


def _price_axis(price: int, median_price: float) -> float:
    """가격 축 = 종류 내 가격 중앙값 대비 상대값(예산 배분은 조합 단계가 맡는다, 모듈
    docstring 참고). `clamp(1 - price/(2*median), 0, 1)` — 중앙값에서 0.5, 중앙값의
    2배 이상이면 0, 0원이면 1인 단조 감소식이다. median이 0/미정이면 우열을 가릴 근거가
    없으므로 중립 0.5."""
    if median_price <= 0:
        return 0.5
    return max(0.0, min(1.0, 1 - price / (2 * median_price)))


def _verdict_value(pref: dict[str, Any], specs: dict[str, Any]) -> float:
    """조건 하나의 값: 충족 1 / 미충족 0 / 정보 없음(Pending)은 "모름"이지 "틀림"이 아니므로 0.5."""
    verdict, _ = spec_rules.evaluate(pref, specs)
    return 1.0 if verdict == "Pass" else 0.5 if verdict == "Pending" else 0.0


def _feel_axis(cand: Candidate) -> float:
    """리뷰 축 값. 체감 적합도 R(`feel_detail`)이 있으면 그것을, 없으면 외부 리뷰 점수를 쓴다(근거가 없으면 중립)."""
    if cand.feel_detail is not None:
        return cand.feel_detail.value
    return cand.review_detail.value if cand.review_detail else 0.5


def evidence_count(cand: Candidate) -> int:
    """리뷰 관측 수 n — 점수에 쓰는 등록 속성의 긍정 + 부정 관측 수의 합(혼합 제외, 기획 3.8).

    외부 리뷰는 큰 속성(aspect)마다 한 번씩 센다(`review_detail.contributions` 의 p + n). 체감 속성 여러 개가 같은 외부 속성을
    가리키므로 속성별 표에서 읽으면 같은 관측을 여러 번 세게 된다. 사용기(커뮤니티) 표는 체감 속성별 같은 조건·그 밖의
    긍정·부정 표를 더한다(성향 속성은 세지 않는다). 후보 풀의 다른 상품과 비교하지 않는다 — 후보 풀이 달라져도 같은 값이다."""
    total = 0
    if cand.review_detail is not None:
        total += sum(int(c.p) + int(c.n) for c in cand.review_detail.contributions)
    if cand.feel_detail is not None:
        for a in cand.feel_detail.attributes:
            if a.type == "rating":
                total += a.same_good + a.same_bad + a.rest_good + a.rest_bad
    return total


def evidence_penalty(n: int, cfg: dict[str, Any]) -> float:
    return round(cfg["evidence_penalty"] * max(0.0, 1.0 - n / cfg["evidence_min_n"]), 4)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def review_axis_values(kept: list[Candidate], cfg: dict[str, Any]) -> dict[str, float]:
    """후보별 리뷰 축 값(점수식용). R 자체는 바꾸지 않는다 — 응답의 R 은 그대로이고 여기서는 비교만 다시 한다.
    ① 근거가 0건인 상품은 근거 있는 후보 값의 하위 분위수 이하로 둔다(풀 평균에서 출발해 낙관적이던 것을 막는다).
    ② 후보가 review_spread_min_candidates 이상이고 값이 갈리면 후보 안 중간값 기준으로 편다: 0.5 + (값 − 중간) / max(범위, review_spread_min_span).
    범위가 최소 폭 이상이면 min-max 와 같고, 더 좁으면(0.70~0.82 에 몰린 경우) 최소 폭만큼만 벌려 작은 차이를 과장하지 않는다."""
    raw = {c.product_key: _feel_axis(c) for c in kept}
    evidenced = [raw[c.product_key] for c in kept if evidence_count(c) > 0]
    if evidenced:
        floor = _quantile(evidenced, cfg["review_unevidenced_quantile"])
        for c in kept:
            if evidence_count(c) == 0:
                raw[c.product_key] = min(raw[c.product_key], floor)
    values = list(raw.values())
    lo, hi = min(values), max(values)
    if len(kept) >= cfg["review_spread_min_candidates"] and hi - lo > 1e-9:
        span = max(hi - lo, cfg["review_spread_min_span"])
        mid = (hi + lo) / 2
        return {k: max(0.0, min(1.0, 0.5 + (v - mid) / span)) for k, v in raw.items()}
    return raw


def _brand_key(name: str) -> str:
    return name.strip().lower()


def _brand_keys(names) -> set[str]:
    """브랜드 이름 목록을 비교용 열쇠(앞뒤 공백 제거, 소문자) 집합으로. 빈 이름은 뺀다."""
    return {_brand_key(n) for n in (names or ()) if n and n.strip()}


def _drop_avoided_brands(cands: list[Candidate], avoid: set[str]) -> tuple[list[Candidate], int]:
    """기피 브랜드는 "빼 달라"는 명시 요청이라 후보에서 뺀다(기획 3.7). (남은 후보, 뺀 수)."""
    if not avoid:
        return cands, 0
    kept = [c for c in cands if _brand_key(c.brand) not in avoid]
    return kept, len(cands) - len(kept)


def _drop_excluded(cands: list[Candidate], names: list[str] | None) -> tuple[list[Candidate], int]:
    """채팅에서 "다른 걸로 바꿔줘"로 뺀 제품(이름)을 후보에서 뺀다. (남은 후보, 뺀 수)."""
    if not names:
        return cands, 0
    drop = {n.casefold() for n in names}
    kept = [c for c in cands if c.name.casefold() not in drop]
    return kept, len(cands) - len(kept)


def _brand_axis(cand: Candidate, like: set[str]) -> float:
    """선호 브랜드를 말했으면 그 브랜드 후보는 1, 나머지는 0.5. 말하지 않았으면 모두 0.5(판매량으로 점수를 주지 않는다)."""
    return 1.0 if like and _brand_key(cand.brand) in like else 0.5


def _warranty_axis(cand: Candidate, months: dict[str, float]) -> float:
    """무상 보증 기간(`specs["warranty_months"]`)의 같은 종류 후보 안 상대 위치. 정보가 없거나 값이 하나뿐이면 0.5."""
    value = cand.specs.get("warranty_months")
    if value is None or len(months) < 2:
        return 0.5
    lo, hi = min(months.values()), max(months.values())
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (float(value) - lo) / (hi - lo)))


def effective_weights(
    base: dict[str, float], criteria: dict[str, list[str]], stated_criteria: set[str], emphasis: set[str], cfg: dict[str, Any],
    *, has_budget: bool = True, brand_liked: bool = False,
) -> tuple[dict[str, float], list[str]]:
    """① 품목별 기본 가중치(예산을 말하지 않았으면 가격 ×price_weight_without_budget, 선호 브랜드를 말했으면 브랜드를
    brand_like_weight 로) → ② 강조한 축 ×emphasis_boost → ③ 직접 말한 소프트 조건이 있는 스펙 기준 ×stated_criterion_boost →
    ④ 합 1 정규화. 스펙을 강조하면서 그 조건도 말하면 ×(1.5×2)=×3 이 된다. 적용한 배수의 이유를 문장으로 함께 낸다."""
    raw = dict(base)
    reasons: list[str] = []
    if not has_budget and "가격" in raw and cfg["price_weight_without_budget"] < 1:
        raw["가격"] *= cfg["price_weight_without_budget"]
        reasons.append(f"예산을 말하지 않아 '가격' 축 ×{cfg['price_weight_without_budget']:g}")
    if brand_liked and "브랜드" in raw and cfg["brand_like_weight"] > raw["브랜드"]:
        raw["브랜드"] = cfg["brand_like_weight"]
        reasons.append(f"선호 브랜드를 말해 '브랜드' 축 기본 가중 {cfg['brand_like_weight']:g}")
    for axis in sorted(emphasis & set(raw)):
        raw[axis] *= cfg["emphasis_boost"]
        reasons.append(f"강조한 '{axis}' 축 ×{cfg['emphasis_boost']:g}")
    for name in criteria:
        if name in stated_criteria:
            raw[name] *= cfg["stated_criterion_boost"]
            reasons.append(f"직접 말한 조건이 있는 '{name}' 기준 ×{cfg['stated_criterion_boost']:g}")
    total = sum(raw.values())
    return ({axis: value / total for axis, value in raw.items()} if total > 0 else dict(base)), reasons


def rank_candidates(
    kind: str, requirement: PeripheralRequirement, kept: list[Candidate], weights: dict[str, float] | None = None,
    *, budget: int | None = None, require_review_details: bool = False, kind_budget: int | None = None,
    brand_like: set[str] | None = None, emphasis: set[str] | None = None, rules: dict | None = None,
) -> list[Candidate]:
    """[3-B]. score/breakdown/score_detail/rank를 채워 점수 내림차순으로 정렬한다.

    동점 규칙(결정적): 점수 내림차순 → 가격 오름차순 → product_key 오름차순.

    `weights` 는 품목별 기본 가중치(없으면 설정의 값). `budget`(여러 종류 합계 예산)은 조합 단계(`choose`)가 쓰므로 여기서는
    쓰지 않고, 종류별 예산 `kind_budget` 이 있으면 가격 축이 그 안에서의 위치가 된다. `brand_like`·`emphasis` 는 말한 선호
    브랜드(소문자)와 강조한 축 이름이다.
    """
    if not kept:
        return []
    if require_review_details and any(c.review_detail is None for c in kept):
        raise ValueError(f"peripheral review score missing for {kind}")
    rules = rules or load_peripheral_rules()
    cfg = scoring_cfg(rules)
    rdef = ranking_def(kind, rules)
    criteria: dict[str, list[str]] = rdef["criteria"]
    base = dict(weights if weights is not None else rdef["weights"])
    key_to_criterion = {key: name for name, keys in criteria.items() for key in keys}

    soft = requirement.soft or {}
    preferences: list[dict[str, Any]] = spec_rules.dedupe_prefs(soft.get("preferences") or [])
    stated = list(soft.get("stated") or [])
    by_criterion: dict[str, list[tuple[dict[str, Any], float]]] = {name: [] for name in criteria}
    for pref in preferences:
        name = key_to_criterion.get(pref["key"])
        if name is not None:
            by_criterion[name].append((pref, cfg["stated_pref_weight"] if pref in stated else 1.0))
    stated_criteria = {name for name, items in by_criterion.items() if any(pref in stated for pref, _ in items)}
    like = _brand_keys(brand_like)
    final_weights, reasons = effective_weights(
        base, criteria, stated_criteria, set(emphasis or ()), cfg,
        has_budget=kind_budget is not None or budget is not None, brand_liked=bool(like),
    )
    review_values = review_axis_values(kept, cfg)

    median_price = statistics.median(c.price for c in kept)
    hard_keys = (_HARD_KEY_TO_PREF[name][0] for name in requirement.hard)
    judged_keys = sorted({*hard_keys, *(p["key"] for p in preferences), *(p["key"] for p in requirement.filters)})
    available = {k for k in judged_keys if any(c.specs.get(k) is not None for c in kept)}
    warranty = {c.product_key: float(c.specs["warranty_months"]) for c in kept if c.specs.get("warranty_months") is not None}

    scored: list[Candidate] = []
    for cand in kept:
        values: dict[str, float] = {}
        for name in criteria:
            items = by_criterion[name]
            if not items:
                values[name] = 0.5
            else:
                wsum = sum(w for _, w in items)
                values[name] = sum(w * _verdict_value(p, cand.specs) for p, w in items) / wsum
        values["리뷰"] = review_values[cand.product_key]
        values["가격"] = (max(0.0, min(1.0, 1 - cand.price / kind_budget)) if kind_budget
                         else _price_axis(cand.price, median_price))
        values["브랜드"] = _brand_axis(cand, like)
        values["무상AS"] = _warranty_axis(cand, warranty)

        pending = PENDING_SCORE_PENALTY if cand.verdict == "Pending" else 0.0
        missing = [k for k in judged_keys if k in available and cand.specs.get(k) is None]
        missing_pen = min(cfg["missing_key_penalty"] * len(missing), cfg["missing_key_penalty_max"])
        n = evidence_count(cand)
        evidence_pen = evidence_penalty(n, cfg)
        raw = sum(final_weights[axis] * values[axis] for axis in final_weights) - pending - missing_pen - evidence_pen

        detail = {
            "axes": [{"axis": axis, "value": round(values[axis], 3), "weight": round(final_weights[axis], 4),
                      "points": round(final_weights[axis] * values[axis], 4)} for axis in final_weights],
            "penalties": {"pending": round(pending, 3), "missing_keys": round(missing_pen, 3), "evidence": round(evidence_pen, 3)},
            "missing_keys": missing,
            "evidence_count": n,
            "weights_reason": reasons,
        }
        scored.append(cand.model_copy(update={
            "score": round(raw, 3), "score_detail": detail,
            # 리뷰 값은 체감 적합도 R 그대로(반올림하지 않는다 — 응답의 R 과 같은 값이어야 한다). 나머지 축은 소수 셋째 자리.
            "breakdown": {a: (_feel_axis(cand) if a == "리뷰" else round(v, 3)) for a, v in values.items()}}))

    ranked = sorted(scored, key=lambda c: (-c.score, c.price, c.product_key))
    return [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(ranked)]


def apply_trending(ranked: list[Candidate], margin: float) -> list[Candidate]:
    """"요즘 많이 쓰는"을 말했을 때: 점수는 바꾸지 않고, 1위와의 점수 차가 `margin` 이내인 후보들 안에서만 최근 사용기를
    쓴 작성자 수가 많은 순으로 앞에 놓는다(개발_확정사양 6.6). 최근 글이 하나도 없으면 순서를 그대로 둔다."""
    if len(ranked) < 2:
        return ranked
    top = ranked[0].score
    head = [c for c in ranked if top - c.score <= margin + 1e-9]
    if len(head) < 2:
        return ranked

    def _recent(c: Candidate) -> int:
        return c.feel_detail.recent_authors if c.feel_detail else 0

    if not any(_recent(c) for c in head):
        return ranked
    reordered = sorted(head, key=lambda c: -_recent(c))          # sorted 는 안정 정렬: 같으면 원래 순위
    out = [*reordered, *ranked[len(head):]]
    return [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(out)]


def choose(
    kinds_ranked: dict[str, list[Candidate]], budget_max: int | None, top_n: int = 5,
) -> tuple[dict[str, Candidate], dict[str, Any]]:
    """조합. budget_max가 없으면 종류별 1위. 있으면 top-N의 곱을 전수 탐색한다.

    반환하는 counts는 조합 탐색에 관한 것만 담는다(`truncated`/`considered`/`over_budget`) —
    종류별 pool/pass/fail/pending 통계는 `filter_candidates`가 이미 낸다.
    """
    counts: dict[str, Any] = {}
    pools = {kind: ranked for kind, ranked in kinds_ranked.items() if ranked}
    if not pools:
        return {}, counts
    if budget_max is None:
        return {kind: ranked[0] for kind, ranked in pools.items()}, counts

    if any(len(ranked) > top_n for ranked in pools.values()):
        counts["truncated"] = 1
    limited = {kind: ranked[:top_n] for kind, ranked in pools.items()}
    best, cheapest, considered = _search_combos(limited, budget_max)
    if best is None and counts.get("truncated"):
        # 점수 top-N 끼리는 예산을 못 맞춰도 더 싼 후보로는 맞출 수 있다(4종 30만 원: top-5 최저 346,130원, 전체 최저 224,700원
        # — QA 10/16 #8). 종류마다 가장 싼 top-N 을 더해 한 번 더 찾는다. 그래도 없으면 cheapest 가 전체 최저가 조합이다.
        widened = {kind: list({c.product_key: c for c in [*ranked[:top_n], *sorted(ranked, key=lambda c: (c.price, -c.score))[:top_n]]}.values())
                   for kind, ranked in pools.items()}
        best, cheapest, more = _search_combos(widened, budget_max)
        considered += more
        counts["widened"] = 1
    counts["considered"] = considered

    if best is not None:
        return best[0], counts
    counts["over_budget"] = 1
    assert cheapest is not None  # pools가 비지 않았으니 최소 한 조합은 반드시 있다
    return cheapest[0], counts


def _search_combos(
    limited: dict[str, list[Candidate]], budget_max: int,
) -> tuple[tuple[dict[str, Candidate], int, float] | None, tuple[dict[str, Candidate], int, float] | None, int]:
    """후보 곱 전수 탐색 → (예산 이하 중 점수 합 최대, 최저가 조합, 본 조합 수)."""
    kinds_order = sorted(limited)
    considered = 0
    best: tuple[dict[str, Candidate], int, float] | None = None
    cheapest: tuple[dict[str, Candidate], int, float] | None = None
    for combo in itertools.product(*(limited[k] for k in kinds_order)):
        considered += 1
        picks = dict(zip(kinds_order, combo))
        total_price = sum(c.price for c in combo)
        total_score = sum(c.score for c in combo)
        if cheapest is None or total_price < cheapest[1] or (
            total_price == cheapest[1] and total_score > cheapest[2]
        ):
            cheapest = (picks, total_price, total_score)
        if total_price <= budget_max and (
            best is None or total_score > best[2] or (total_score == best[2] and total_price < best[1])
        ):
            best = (picks, total_price, total_score)
    return best, cheapest, considered


def _over_budget_notice(budget_info: dict[str, Any], labels: list[str]) -> dict[str, str]:
    """예산 안 조합이 없을 때 채팅에 알리는 문장(QA 10/16 #8 — 예산 10만 원에 34만 원 결과가 경고 없이 나왔다).
    결과는 조건에 맞는 것 중 가장 싼 조합이므로, 그 합계가 곧 이 조건으로 가능한 최저 금액이다."""
    total, limit = budget_info["total"], budget_info["max"]
    return {"kind": "budget", "code": "over_budget",
            "text": f"{'·'.join(labels)}를 예산 {limit:,}원 안에서는 고를 수 없어요. 조건에 맞는 것 중 가장 싼 "
                    f"{'조합' if len(labels) > 1 else '제품'}도 {total:,}원이라 {total - limit:,}원 넘어요. "
                    + ("예산을 올리거나 품목을 줄여 주세요." if len(labels) > 1 else "예산을 올리거나 조건을 줄여 주세요.")}


def _mark_close_calls(picks: list[PeripheralPick], rules: dict) -> None:
    """접전 표시: 1·2위 점수 차가 기준 안인 품목 중 차이가 작은 순으로 최대 close_call_max_items 개에만 true.
    기준과 개수는 서버가 정한다 — 화면은 임계값을 알 필요가 없다(요청서 3.4)."""
    cfg = scoring_cfg(rules)
    close = sorted((p for p in picks if p.score_gap is not None and p.score_gap < cfg["close_call_margin"]),
                   key=lambda p: (p.score_gap, p.kind))
    for pick in close[: int(cfg["close_call_max_items"])]:
        pick.close_call = True


def _empty_reason(
    kind: str, requirement: PeripheralRequirement, rules: dict, stats: dict[str, int], max_price: int | None = None,
    min_price: int | None = None,
) -> str:
    """필터 후 0건일 때 화면에 보일 이유 문장(계획 §3.3 C6). 후보 자체가 없는 것, 예산에 걸린 것,
    하드 조건에 걸려 전부 떨어진 것을 구분한다."""
    label = kind_def(kind, rules)["label"]
    pool = stats["pool"]
    if pool == 0:
        return f"{label} 후보 자체가 카탈로그에 없습니다"
    priced_out = stats.get("over_price", 0) + stats.get("under_price", 0)
    if min_price is not None and priced_out == pool:
        if max_price is not None:
            return f"예산 {min_price:,}~{max_price:,}원 사이의 {label}가 카탈로그에 없습니다"
        return f"{min_price:,}원 이상의 {label}가 카탈로그에 없습니다"
    if max_price is not None and stats.get("over_price") == pool:
        return f"예산 {max_price:,}원 안에 드는 {label}가 카탈로그에 없습니다"
    if requirement.filters and not requirement.hard:
        return f"말씀하신 조건에 맞는 {label}가 카탈로그에 없습니다"
    hard = requirement.hard
    if hard:
        classes = hard.get("resolution_class")
        refresh = hard.get("refresh_min_hz")
        parts = []
        if classes:
            parts.append("/".join(str(c) for c in classes))
        if refresh:
            parts.append(f"{int(refresh)}Hz 이상")
        cond = "·".join(parts)
        if cond:
            return f"{cond} 조건에 맞는 {label}가 카탈로그에 없습니다"
    return f"조건에 맞는 {label}가 카탈로그에 없습니다"


def _feel_blocks(picks: list[PeripheralPick], values: dict, rules: dict) -> dict[str, Any]:
    """고른 제품마다 체감 근거 블록(화면에 보여 줄 문구와 인용 문장). 근거가 없으면 그 종류는 넣지 않는다."""
    from src.engine.peripheral_evidence import build_feel_block
    from src.engine.peripheral_intent import Interpretation

    interp = values.get("peripheral_intent") or Interpretation()
    out: dict[str, Any] = {}
    for pick in picks:
        resolved = (values.get("peripheral_resolved") or {}).get(pick.kind)
        block = build_feel_block(pick.candidate.feel_detail, interp, resolved, pick.kind, rules)
        if block is not None:
            out[pick.kind] = block
    return out


def _attach_views(picks: list[PeripheralPick], kinds_ranked: dict[str, list[Candidate]], values: dict, rules: dict) -> None:
    """1위와 대안마다 결과 화면용 표시 값을 채운다: 요청 항목별 근거 연결·가격 순서, 대안은 체감 블록까지.
    점수·순위는 바꾸지 않는다(이미 계산된 체감 상세와 규칙 파일의 display 절만 쓴다)."""
    from src.engine.peripheral_display import price_position, requested_items
    from src.engine.peripheral_evidence import build_feel_block
    from src.engine.peripheral_intent import Interpretation

    interp = values.get("peripheral_intent") or Interpretation()
    pc_purposes = frozenset(values.get("peripheral_pc_purposes") or ())
    for pick in picks:
        resolved = (values.get("peripheral_resolved") or {}).get(pick.kind)
        pool = kinds_ranked.get(pick.kind, [])
        pick.requested = requested_items(pick.kind, pick.candidate.specs, interp, resolved, rules, pc_purposes)
        pick.price_position = price_position(pick.candidate, pool)
        pick.alternative_views = [
            {"feel": build_feel_block(alt.feel_detail, interp, resolved, pick.kind, rules),
             "requested": requested_items(pick.kind, alt.specs, interp, resolved, rules, pc_purposes),
             "price_position": price_position(alt, pool)}
            for alt in pick.alternatives
        ]


def _monitor_cross_check(
    values: dict, pc_context: dict | None, picks_by_kind: dict[str, Candidate], requirements: dict[str, PeripheralRequirement],
    rules: dict, log: LogFn,
) -> tuple[list[dict], dict[str, list] | None]:
    """E12 — 모니터를 골랐고 PC 쪽 정보(pc_context)가 있으면 교차 검사를 돌린다. 없으면(기본)
    (검사 결과, 쟁점) 둘 다 비워 두어 기존 동작과 완전히 같게 만든다."""
    if pc_context is None or "monitor" not in picks_by_kind:
        return [], None
    from src.engine import peripheral_cross
    from src.engine.stage2_requirement import load_computer_rules

    default_resolution = load_computer_rules()["requirements"]["default_resolution"]
    pc_resolution = pc_context.get("resolution") or values.get("resolution") or default_resolution
    target_refresh_hz = requirements["monitor"].hard.get("refresh_min_hz")
    checks = peripheral_cross.monitor_cross_checks(
        picks_by_kind["monitor"], pc_resolution=pc_resolution,
        gpu_specs=pc_context.get("gpu_specs"), target_refresh_hz=target_refresh_hz, rules=rules,
    )
    log(f"      [P][E12] 모니터↔PC 교차 검사: {', '.join(c['axis'] + '=' + c['state'] for c in checks)}")
    return checks, {"monitor": peripheral_cross.cross_issues(checks)}


def run_peripherals(
    values: dict, candidates: dict[str, list[Candidate]], log: LogFn, *, pc_context: dict | None = None,
    require_review_details: bool = False,
) -> PeripheralResult:
    """진입점(계획 §3.3 E11). `peripherals` 조건이 없으면 이 단계 자체를 건너뛴다.

    build_requirements([2]) → 종류별 filter_candidates([3-A]) → rank_candidates([3-B]) →
    choose(조합) → [E12 교차 검사] → stage3c_verify.verify_per_item([3-C]) 순서로 돈다.

    `pc_context`(E12, 선택) — `{"resolution": str | None, "gpu_specs": dict | None}`.
    모니터를 골랐고 `pc_context`가 주어지면 `peripheral_cross.monitor_cross_checks`로
    PC와의 교차 검사를 돌려 그 모니터의 `PeripheralPick.checks`를 채우고, 쟁점을
    `verify_per_item`의 `extra_issues`로 넘긴다. `pc_context`가 없으면(기본값) 이전과
    동작이 완전히 같다 — PC 세트 신뢰도에도 영향을 주지 않는다(계획 §3.3 E12).
    """
    from src.engine import stage3c_verify  # 지연 import — stage3c_verify가 이 모듈을 몰라도 되게

    rules = load_peripheral_rules()
    kinds = requested_kinds(values, rules)
    if not kinds:
        return PeripheralResult(status="skipped")

    log(f"[P] 주변기기 요청: {', '.join(kind_def(k, rules)['label'] for k in kinds)}")
    requirements = build_requirements(values, kinds, rules)

    counts: dict[str, Any] = {}
    kinds_ranked: dict[str, list[Candidate]] = {}
    empty: list[dict[str, str]] = []
    for kind in kinds:
        cands = candidates.get(kind, [])
        req = requirements[kind]
        kind_budget = (values.get("peripheral_kind_budget") or {}).get(kind)
        kind_budget_min = (values.get("peripheral_kind_budget_min") or {}).get(kind)
        cands, avoided = _drop_avoided_brands(cands, _brand_keys((values.get("peripheral_brand_avoid") or {}).get(kind)))
        cands, excluded = _drop_excluded(cands, (values.get("peripheral_exclude") or {}).get(kind))
        kept, stats = filter_candidates(kind, req, cands, max_price=kind_budget, min_price=kind_budget_min)
        if avoided:
            stats["avoided_brand"] = avoided
        if excluded:
            stats["excluded"] = excluded
        counts[kind] = stats
        label = kind_def(kind, rules)["label"]
        if not kept:
            reason = _empty_reason(kind, req, rules, stats, kind_budget, kind_budget_min)
            empty.append({"kind": kind, "reason": reason})
            log(f"      [P] {label}: 조건에 맞는 후보 0건 — {reason}")
            continue
        weights = rules["ranking"][kind]["weights"]
        kept = attach_feel(kind, cands, kept, values, rules)
        ranked = rank_candidates(
            kind, req, kept, weights, budget=values.get("peripheral_budget_max"),
            require_review_details=require_review_details, kind_budget=kind_budget,
            brand_like=(values.get("peripheral_brand_like") or {}).get(kind),
            emphasis=set((values.get("peripheral_emphasis") or {}).get(kind) or []), rules=rules,
        )
        interp = values.get("peripheral_intent")
        if interp is not None and "trending" in interp.situations and rules.get("feel"):
            ranked = apply_trending(ranked, rules["feel"]["trending_margin"])
        kinds_ranked[kind] = ranked
        log(f"      [P] {label}: {stats['pool']} → 유지 {len(kept)}"
            f" (Pass {stats['pass']}/Pending {stats['pending']}/Fail {stats['fail']}) · 체감 R 가중치 {weights.get('리뷰', 0)}")

    if not kinds_ranked:
        log("[P] 주변기기: 요청한 종류 전부 조건에 맞는 후보가 없습니다")
        return PeripheralResult(status="empty", empty=empty, counts=counts)

    budget_max = values.get("peripheral_budget_max")
    picks_by_kind, combo_counts = choose(kinds_ranked, budget_max)
    counts.update(combo_counts)

    monitor_checks, extra_issues = _monitor_cross_check(values, pc_context, picks_by_kind, requirements, rules, log)

    picks: list[PeripheralPick] = []
    for kind, cand in picks_by_kind.items():
        ranked = kinds_ranked[kind]
        alternatives = [c for c in ranked if c.product_key != cand.product_key][:2]
        checks = monitor_checks if kind == "monitor" else []
        gap = round(cand.score - alternatives[0].score, 3) if alternatives else None
        picks.append(PeripheralPick(kind=kind, candidate=cand, score=cand.score, verdict=cand.verdict,
                                     checks=checks, alternatives=alternatives, score_gap=gap))
    _mark_close_calls(picks, rules)
    _attach_views(picks, kinds_ranked, values, rules)

    verification = stage3c_verify.verify_per_item(
        {p.kind: p for p in picks}, requirements, log, extra_issues=extra_issues, rules=rules,
    )

    budget_info: dict[str, Any] | None = None
    if budget_max is not None:
        total = sum(p.candidate.price for p in picks)
        budget_info = {"max": budget_max, "total": total, "over_budget": bool(combo_counts.get("over_budget"))}

    log(f"[P] 주변기기 결과: {len(picks)}건 선정" + (f", 미충족 {len(empty)}건" if empty else ""))
    picked_requirements = {kind: requirements[kind] for kind in picks_by_kind if kind in requirements}
    feel_blocks = _feel_blocks(picks, values, rules)
    notices = [n for p in picks if p.kind == "monitor" for n in monitor_notices(p.candidate, requirements["monitor"], values)]
    if budget_info is not None and budget_info["over_budget"]:
        picked = {p.kind for p in picks}
        notices.insert(0, _over_budget_notice(budget_info, [kind_def(k, rules)["label"] for k in kinds if k in picked]))
    return PeripheralResult(status="ready", picks=picks, empty=empty, counts=counts,
                             budget=budget_info, verification=verification, requirements=picked_requirements,
                             feel=feel_blocks, notices=notices)
