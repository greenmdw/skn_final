"""[3-B] 적합도 · 병목 순위.

[3-A] 통과분을 슬롯별 점수화 → 슬롯별 top-N. LLM·RAG 없음.
S_base = clip01(Σ w_axis · s_axis), 축은 가격 / 성능 / 리뷰 세 개(src/engine/score_policy.py).
  가격 = 1 / (1 + (P/B)^α)   (B: 슬롯 참고 예산 = 총예산 × 슬롯 배분, P: 후보 가격,
                              α: config/recommendation_engine.yaml 의 scoring.price_axis.alpha)
  성능 = clip01(perf_tier / 10)   (등급이 없는 CPU·GPU는 오류, 그 밖의 슬롯은 중립 0.5)
  리뷰 = clip01(리뷰 적합도)
점수·breakdown은 반올림하지 않고, 후보 한 개의 점수는 다른 후보와 무관하다.
병목: ideal_tier 대비 최선 후보가 낮으면 bottleneck_hint 방출(점수에는 쓰지 않는다).
"""
from __future__ import annotations

import math

from src.config import TOP_N_DEFAULT, TOP_N_IMPACT
from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, ReviewScoreDetail, Slots
from src.engine import LogFn
from src.engine.score_policy import AXES, ScoreInputError, clip01, price_axis, validate_axis_weights
from src.engine.stage2_requirement import load_computer_rules


def _weights_for(values: dict, ranking: dict) -> tuple[dict[str, float], list[str]]:
    """priority(성능/가성비/저소음)로 이번 요청의 축 가중치 표를 고른다. 조건을 안 준 요청은 기본 weights.
    noise_sensitive 는 바깥 가중치를 바꾸지 않는다 — 정숙성은 리뷰 프로필이 한 번만 반영한다."""
    weights = dict(ranking["weights"])
    notes: list[str] = []
    priority = values.get("priority")
    chosen = (ranking.get("priority_weights") or {}).get(priority)
    if chosen:
        weights = dict(chosen)
        notes.append(f"우선순위 {priority}: " + " ".join(f"{k} {v:g}" for k, v in weights.items() if v))
    validate_axis_weights(weights, "점수 계산 가중치")
    return weights, notes


def _score(cand: Candidate, ref_budget: float, slot: str,
           weights: dict[str, float] | None = None,
           review_detail: ReviewScoreDetail | None = None) -> Candidate:
    notes: list[str] = []
    if "perf_tier" in cand.specs and cand.specs["perf_tier"] is not None:
        performance = clip01(float(cand.specs["perf_tier"]) / 10)
    elif slot in ("CPU", "GPU"):
        raise ScoreInputError(f"{slot} 후보 {cand.product_key}에 perf_tier가 없습니다")
    else:
        performance = 0.5
        notes.append("neutral:성능")
    review_detail = review_detail or cand.review_detail
    # Pure engine unit tests may omit injected review data. Runtime orchestration sets
    # require_review_details=True, so DB paths cannot silently take this neutral branch.
    review = clip01(review_detail.value) if review_detail is not None else 0.5
    b = {"가격": price_axis(cand.price, ref_budget), "성능": performance, "리뷰": review}
    ranking = load_computer_rules()["ranking"]
    weights = weights if weights is not None else ranking["weights"]
    validate_axis_weights(weights, "점수 계산 가중치")
    score = clip01(math.fsum(weights[a] * b[a] for a in AXES))
    return cand.model_copy(update={"score": score, "breakdown": b, "score_notes": notes,
                                   "review_detail": review_detail})


def run(hf: HardFilterResult, spec: RequirementSpec, slots: Slots, log: LogFn, *,
        require_review_details: bool = False) -> RankResult:
    log("[3-B] 적합도 · 병목 순위 ...")
    if require_review_details:
        missing = [c.product_key for cands in hf.slots.values() for c in cands if c.review_detail is None]
        if missing:
            raise ValueError(f"review score is missing for {len(missing)} ranked candidates")
    not_pass = [c.product_key for cands in hf.slots.values() for c in cands if c.verdict != "Pass"]
    if not_pass:
        raise ScoreInputError(f"Pass가 아닌 후보는 점수를 계산하지 않습니다: {', '.join(not_pass[:5])}")
    ranking = load_computer_rules()["ranking"]
    weights, notes = _weights_for(slots.values, ranking)
    rr = RankResult(weights_used=weights, weight_adjustments=notes)
    for note in notes:
        log(f"      가중치 조정 — {note}")
    purpose = slots.values.get("purpose", "game")
    res = slots.values.get("resolution") or load_computer_rules()["requirements"]["default_resolution"]
    by_purpose = ranking["ideal_tiers"].get(purpose) or {}
    ideals = by_purpose.get(res) or by_purpose.get("default") or {}
    alloc = spec.budget.get("alloc") or {}
    total = spec.budget.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or total <= 0:
        raise ScoreInputError(f"총예산이 유한한 양수가 아닙니다: {total!r}")

    for slot, cands in hf.slots.items():
        ideal = ideals.get(slot)
        # games 는 [2]가 targets[slot]["perf_tier_min"](하한)만 올린다. 병목 힌트의 ideal 이
        # 용도·해상도 값에 머물지 않게, 하한이 ideal 보다 높아진 슬롯만 그 하한까지 끌어올린다
        # (낮추지는 않는다). 점수에는 쓰지 않는 힌트용이다. ideal 표에 없는 슬롯(None)은 건드리지 않는다.
        ideal_note = None
        if "games_applied" in spec.flags and ideal is not None:
            perf_min = spec.targets.get(slot, {}).get("perf_tier_min")
            if perf_min is not None and perf_min > ideal:
                note = f"게임 요구 반영: {slot} 이상 등급 {ideal:g}→{perf_min:g}"
                ideal_note = note
                log(f"      병목 기준 조정 — {note}")
                ideal = float(perf_min)
        if slot not in alloc:
            raise ScoreInputError(f"예산 배분(alloc)에 슬롯 {slot}이(가) 없습니다")
        ref_budget = float(total) * alloc[slot]
        scored = sorted((_score(c, ref_budget, slot, weights) for c in cands), key=lambda c: (-c.score, c.price, c.product_key))
        n = TOP_N_IMPACT if slot in ranking["impact_slots"] else TOP_N_DEFAULT
        ranked_all = [c.model_copy(update={"rank": i + 1}) for i, c in enumerate(scored)]
        top = ranked_all[:n]

        hint = None
        if ideal and top and float(top[0].specs.get("perf_tier", 5)) < ideal - 0.5:
            hint = {"slot": slot, "gap": round(ideal - float(top[0].specs.get("perf_tier", 5)), 1),
                    "suggestion": "alloc 상향 또는 tier 하향 수용"}
            log(f"      병목 힌트: {slot} tier {top[0].specs.get('perf_tier')} < ideal {ideal}")

        rr.slots[slot] = {
            "ideal_tier": ideal,
            "ranked": [c.model_dump() for c in top],
            # top-N으로 자르기 전의 전체 순위. [4]가 top-N 안에 호환 조합이 없을 때만 넓혀 쓴다.
            "pool": [c.model_dump() for c in ranked_all],
            "bottleneck_hint": hint,
            "ideal_note": ideal_note,
        }
        observed = sum(
            1 for c in scored if c.review_detail and any(
                item.p + item.n + item.mixed > 0 for item in c.review_detail.contributions
            )
        )
        log(f"      {slot}: top-{len(top)}  (ideal_tier={ideal})  1위 score={top[0].score if top else '-'}"
            f"  리뷰 관측 {observed}/{len(scored)}")
    return rr

