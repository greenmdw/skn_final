"""주변기기 [3-A] 하드 필터 · [3-B] 랭킹 · 조합 · 진입점 — 추천엔진 구현계획 §3.3 E11.

PC의 stage3a_hardfilter/stage3b_rank에 대응하는 주변기기 버전이다. 판정 자체는
`src/engine/spec_rules.py`(선언형 평가기)를 재사용하고, 이 모듈은 그 결과를 후보 목록에
적용하는 배선만 한다.

## [3-A] filter_candidates

`requirement.hard`(예: 모니터의 `resolution_class`/`refresh_min_hz`)를 spec_rules가 읽을
pref 목록으로 바꿔 Fail만 제외한다. **조건을 완화하지 않는다** — 남는 후보가 없으면 빈
리스트를 그대로 낸다(계획 §3.3 C6, "빈 결과 처리").

## [3-B] rank_candidates

축 넷(가격/선호적합/데이터충실/리뷰) 중 리뷰 가중치는 계속 0이다. 주변기기 R과 근거는
설명용으로 전달하되 현재 순위 점수에는 반영하지 않는다.

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
from src.engine.peripheral_requirement import build_requirements
from src.engine.peripheral_rules import kind_def, load_peripheral_rules, requested_kinds

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
    kind: str, requirement: PeripheralRequirement, cands: list[Candidate],
) -> tuple[list[Candidate], dict[str, int]]:
    """[3-A]. hard 조건이 없는 종류(키보드·마우스·스피커)는 전부 Pass다."""
    prefs = _hard_prefs(requirement.hard)
    kept: list[Candidate] = []
    counts = {"pool": len(cands), "pass": 0, "fail": 0, "pending": 0}
    for cand in cands:
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


def _preference_axis(cand: Candidate, prefs: list[dict[str, Any]]) -> float:
    """소프트 선호 충족 비율. Pending은 "모름"이지 "틀림"이 아니므로 0.5로 센다(계획 §3.3).
    prefs가 없으면(해당 조건이 없거나 매칭 안 됨) 중립 0.5."""
    if not prefs:
        return 0.5
    values = []
    for pref in prefs:
        verdict, _ = spec_rules.evaluate(pref, cand.specs)
        values.append(1.0 if verdict == "Pass" else 0.5 if verdict == "Pending" else 0.0)
    return sum(values) / len(values)


def _fullness_axis(cand: Candidate, judged_keys: list[str]) -> float:
    """판정에 실제로 쓰인 키(hard ∪ soft) 중 값이 있는 비율. 판정용 키가 아예 없으면
    (하드도 소프트도 매칭 안 됨) 결손을 논할 대상이 없으므로 1.0."""
    if not judged_keys:
        return 1.0
    present = sum(1 for k in judged_keys if cand.specs.get(k) is not None)
    return present / len(judged_keys)


def rank_candidates(
    kind: str, requirement: PeripheralRequirement, kept: list[Candidate], weights: dict[str, float],
    *, budget: int | None = None, require_review_details: bool = False,
) -> list[Candidate]:
    """[3-B]. score/breakdown/rank를 채워 점수 내림차순으로 정렬한다.

    동점 규칙(결정적): 점수 내림차순 → 가격 오름차순 → product_key 오름차순.

    `budget`은 이 함수에서 쓰지 않는다 — 종류별 예산 배분이 없어(계획 §3.3 "예산") 가격
    축은 항상 종류 내 중앙값 대비로만 계산하고, `peripheral_budget_max` 제약은 조합 단계
    (`choose`)가 직접 처리한다. 시그니처에 남긴 건 호출부가 조건값을 그대로 넘길 수 있게
    하기 위해서고(향후 축별 예산 배분이 생기면 이 자리에서 쓴다), 지금은 미사용이다.
    """
    if not kept:
        return []
    if require_review_details and any(c.review_detail is None for c in kept):
        raise ValueError(f"peripheral review score missing for {kind}")
    median_price = statistics.median(c.price for c in kept)
    soft_prefs = spec_rules.dedupe_prefs((requirement.soft or {}).get("preferences") or [])
    hard_spec_keys = (_HARD_KEY_TO_PREF[name][0] for name in requirement.hard)
    judged_keys = sorted({*hard_spec_keys, *(p["key"] for p in soft_prefs)})

    scored: list[Candidate] = []
    for cand in kept:
        breakdown = {
            "가격": round(_price_axis(cand.price, median_price), 3),
            "선호적합": round(_preference_axis(cand, soft_prefs), 3),
            "데이터충실": round(_fullness_axis(cand, judged_keys), 3),
            # R/상세는 표시하되 peripheral_rules가 보장하는 외부 가중치 0을 유지한다.
            "리뷰": cand.review_detail.value if cand.review_detail else 0.5,
        }
        raw = sum(weights.get(axis, 0.0) * value for axis, value in breakdown.items())
        if cand.verdict == "Pending":
            raw -= PENDING_SCORE_PENALTY
        scored.append(cand.model_copy(update={"score": round(raw, 3), "breakdown": breakdown}))

    ranked = sorted(scored, key=lambda c: (-c.score, c.price, c.product_key))
    return [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(ranked)]


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
    counts["considered"] = considered

    if best is not None:
        return best[0], counts
    counts["over_budget"] = 1
    assert cheapest is not None  # pools가 비지 않았으니 최소 한 조합은 반드시 있다
    return cheapest[0], counts


def _empty_reason(kind: str, requirement: PeripheralRequirement, rules: dict, pool: int) -> str:
    """필터 후 0건일 때 화면에 보일 이유 문장(계획 §3.3 C6). 후보 자체가 없는 것과 하드
    조건에 걸려 전부 떨어진 것을 구분한다."""
    label = kind_def(kind, rules)["label"]
    if pool == 0:
        return f"{label} 후보 자체가 카탈로그에 없습니다"
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
        kept, stats = filter_candidates(kind, req, cands)
        counts[kind] = stats
        label = kind_def(kind, rules)["label"]
        if not kept:
            reason = _empty_reason(kind, req, rules, stats["pool"])
            empty.append({"kind": kind, "reason": reason})
            log(f"      [P] {label}: 조건에 맞는 후보 0건 — {reason}")
            continue
        weights = rules["ranking"][kind]["weights"]
        ranked = rank_candidates(
            kind, req, kept, weights, budget=values.get("peripheral_budget_max"),
            require_review_details=require_review_details,
        )
        kinds_ranked[kind] = ranked
        log(f"      [P] {label}: {stats['pool']} → 유지 {len(kept)}"
            f" (Pass {stats['pass']}/Pending {stats['pending']}/Fail {stats['fail']}) · 리뷰 R은 참고값, 가중치 0")

    if not kinds_ranked:
        log("[P] 주변기기: 요청한 종류 전부 조건에 맞는 후보가 없습니다")
        return PeripheralResult(status="empty", empty=empty, counts=counts)

    budget_max = values.get("peripheral_budget_max")
    picks_by_kind, combo_counts = choose(kinds_ranked, budget_max)
    counts.update(combo_counts)

    # E12 — 모니터를 골랐고 PC 쪽 정보(pc_context)가 있으면 교차 검사를 돌린다. 없으면(기본)
    # monitor_checks/extra_issues 둘 다 비워 두어 기존 동작과 완전히 같게 만든다.
    monitor_checks: list[dict] = []
    extra_issues: dict[str, list] | None = None
    if pc_context is not None and "monitor" in picks_by_kind:
        from src.engine import peripheral_cross
        from src.engine.stage2_requirement import load_computer_rules

        default_resolution = load_computer_rules()["requirements"]["default_resolution"]
        pc_resolution = pc_context.get("resolution") or values.get("resolution") or default_resolution
        target_refresh_hz = requirements["monitor"].hard.get("refresh_min_hz")
        monitor_checks = peripheral_cross.monitor_cross_checks(
            picks_by_kind["monitor"], pc_resolution=pc_resolution,
            gpu_specs=pc_context.get("gpu_specs"), target_refresh_hz=target_refresh_hz, rules=rules,
        )
        extra_issues = {"monitor": peripheral_cross.cross_issues(monitor_checks)}
        log(f"      [P][E12] 모니터↔PC 교차 검사: "
            f"{', '.join(c['axis'] + '=' + c['state'] for c in monitor_checks)}")

    picks: list[PeripheralPick] = []
    for kind, cand in picks_by_kind.items():
        ranked = kinds_ranked[kind]
        alternatives = [c for c in ranked if c.product_key != cand.product_key][:2]
        checks = monitor_checks if kind == "monitor" else []
        picks.append(PeripheralPick(kind=kind, candidate=cand, score=cand.score, verdict=cand.verdict,
                                     checks=checks, alternatives=alternatives))

    verification = stage3c_verify.verify_per_item(
        {p.kind: p for p in picks}, requirements, log, extra_issues=extra_issues, rules=rules,
    )

    budget_info: dict[str, Any] | None = None
    if budget_max is not None:
        total = sum(p.candidate.price for p in picks)
        budget_info = {"max": budget_max, "total": total, "over_budget": bool(combo_counts.get("over_budget"))}

    log(f"[P] 주변기기 결과: {len(picks)}건 선정" + (f", 미충족 {len(empty)}건" if empty else ""))
    picked_requirements = {kind: requirements[kind] for kind in picks_by_kind if kind in requirements}
    return PeripheralResult(status="ready", picks=picks, empty=empty, counts=counts,
                             budget=budget_info, verification=verification, requirements=picked_requirements)
