"""[3-B] 적합도 · 병목 순위.

[3-A] 통과분을 슬롯별 점수화 → 슬롯별 top-N. LLM·RAG 없음.
score = Σ w_axis·norm_axis − (Pending 이면 0.20).
축: 가격 / 성능 여유 / 밸런스 적합 / 리뷰 신뢰도 / 호환 여유.
병목: balance_profiles 의 ideal_tier 대비 최선 후보가 낮으면 bottleneck_hint 방출.
"""
from __future__ import annotations

from src.config import PENDING_SCORE_PENALTY, REVIEW_AXIS_EXCESS, TOP_N_DEFAULT, TOP_N_IMPACT
from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, Slots
from src.engine import LogFn
from src.engine.stage2_requirement import load_computer_rules
from src.repo.review_repo import (OBS_FLAG_OBSERVED, RISK_STORE_OK, default_risk_store, format_obs_flag,
                                 risk_store_note, risk_store_reason)

# ── 리뷰축: 관계·행동 축의 관측 사실을 랭킹 신호로만 쓴다 (docs/decisions/0001 §3) ──
# 세 단계뿐이다. 관측 없음 0.5(모름) · 관측됨·중앙값의 REVIEW_AXIS_EXCESS 배를 넘는 지표 없음 0.75 ·
# 하나라도 넘음 0.25. 판정이 아니다 — 덜 보여줄 뿐이고 되돌릴 수 있는 자리라 검증 없이 쓴다.
# 넘은 지표는 flags 에 남겨 [5] 설명이 "왜" 를 보여줄 수 있게 한다.
_REVIEW_UNKNOWN, _REVIEW_CLEAR, _REVIEW_FLAGGED = 0.5, 0.75, 0.25


def _review_axis(cand: Candidate) -> tuple[float, list[str]]:
    store = default_risk_store()
    if store is None or store.get(cand.product_key) is None:
        return _REVIEW_UNKNOWN, []
    over = [(k, v, m) for k, v, m in store.excess(cand.product_key) if v >= REVIEW_AXIS_EXCESS * m]
    if over:
        return _REVIEW_FLAGGED, [format_obs_flag(k, v, m, REVIEW_AXIS_EXCESS) for k, v, m in over]
    return _REVIEW_CLEAR, [OBS_FLAG_OBSERVED]


_NOISE = "소음"


def _scaled(value: float, low: float, high: float) -> float:
    """low 이하면 1.0, high 이상이면 0.0, 사이는 선형."""
    return max(0.0, min(1.0, 1 - (value - low) / (high - low)))


def _noise_axis(cand: Candidate, slot: str, proxy: dict) -> float:
    """소음의 물리적 대용값(휴리스틱). 직접 측정값이 없어 CPU/GPU 소비전력과 쿨러 유형으로 본다.
    정보가 없거나 관련 없는 슬롯은 중립 0.5 — 지어내지 않는다."""
    specs = cand.specs
    if slot == "CPU" and specs.get("tdp_w") is not None and "cpu_tdp_w" in proxy:
        return _scaled(float(specs["tdp_w"]), *proxy["cpu_tdp_w"])
    if slot == "GPU" and specs.get("power_w") is not None and "gpu_power_w" in proxy:
        return _scaled(float(specs["power_w"]), *proxy["gpu_power_w"])
    if slot == "쿨러" and specs.get("cooling_type"):
        value = (proxy.get("cooler_type") or {}).get(specs["cooling_type"])
        if value is not None:
            return float(value)
    return 0.5


def _weights_for(values: dict, ranking: dict) -> tuple[dict[str, float], list[str]]:
    """priority(성능/가성비/저소음)와 noise_sensitive 로 이번 요청의 축 가중치를 정한다.
    조건을 안 준 요청은 기본 weights 그대로라 점수가 바뀌지 않는다."""
    weights = dict(ranking["weights"])
    notes: list[str] = []
    priority = values.get("priority")
    chosen = (ranking.get("priority_weights") or {}).get(priority)
    if chosen:
        weights = dict(chosen)
        notes.append(f"우선순위 {priority}: " + " ".join(f"{k} {v:g}" for k, v in weights.items() if v))
    floor = ranking.get("noise_sensitive_min_weight", 0)
    if values.get("noise_sensitive") is True and weights.get(_NOISE, 0.0) < floor:
        old = weights.get(_NOISE, 0.0)
        factor = (1 - floor) / (1 - old)
        weights = {k: (floor if k == _NOISE else v * factor) for k, v in weights.items()}
        weights.setdefault(_NOISE, floor)
        notes.append(f"소음 민감: 소음 가중치 {old:g} → {floor:g}, 나머지 축은 비율대로 축소")
    return weights, notes


def _compat_margin(cand: Candidate, slot: str, target: dict) -> float:
    """[2]가 계산해 둔 슬롯 자체의 전력 예산(tdp_budget_w/tgp_budget_w/wattage_min)
    대비 후보 실측값의 여유. 이 시점엔 다른 슬롯이 뭘 뽑을지 몰라 "최종 상대 부품과의
    여유"는 계산 못 한다 — target이 들고 있는 기준치와의 여유만 본다. 정보가 없으면
    판정하지 않고 중립값 0.5(점수에 영향 없음)로 둔다."""
    if slot in ("CPU", "GPU"):
        budget_w = target.get("tdp_budget_w") if slot == "CPU" else target.get("tgp_budget_w")
        actual_w = cand.specs.get("tdp_w") if slot == "CPU" else cand.specs.get("power_w")
        if not budget_w or actual_w is None:
            return 0.5
        # 예산보다 적게 먹을수록 여유(=다른 부품에 남길 전력 헤드룸)가 크다.
        return max(0.0, min(1.0, 1 - actual_w / max(budget_w, 1)))
    if slot == "파워":
        req_w, actual_w = target.get("wattage_min"), cand.specs.get("wattage_w")
        if not req_w or actual_w is None:
            return 0.5
        # PSU는 반대 방향 — 요구보다 용량이 넉넉할수록 여유가 크다. 넉넉함이 100%를
        # 넘어가면(과대 용량) 더 좋아지진 않게 1.0에서 캡한다.
        return max(0.0, min(1.0, (actual_w - req_w) / max(req_w, 1)))
    return 0.5


def _score(cand: Candidate, ideal_tier: float | None, slot_budget: int, slot: str, target: dict,
           weights: dict[str, float] | None = None) -> Candidate:
    tier = float(cand.specs.get("perf_tier", 5))
    price = cand.price or 1
    review, review_flags = _review_axis(cand)
    b = {
        "가격": max(0.0, 1 - price / max(slot_budget, 1)),
        "성능": min(1.0, tier / 10),
        "밸런스": (1 - abs(tier - ideal_tier) / 4) if ideal_tier else 0.5,
        "리뷰": review,
        "호환여유": _compat_margin(cand, slot, target),
    }
    ranking = load_computer_rules()["ranking"]
    weights = weights if weights is not None else ranking["weights"]
    if weights.get(_NOISE, 0.0) > 0:   # 소음 축은 가중치가 있을 때만 계산·기록한다 — 기본은 breakdown 불변
        b[_NOISE] = _noise_axis(cand, slot, ranking.get("noise_proxy") or {})
    raw = sum(weights.get(k, 0.0) * v for k, v in b.items())
    if cand.verdict == "Pending":
        raw -= PENDING_SCORE_PENALTY
    return cand.model_copy(update={"score": round(raw, 3), "breakdown": {k: round(v, 3) for k, v in b.items()},
                                   "flags": list(cand.flags) + review_flags})


def run(hf: HardFilterResult, spec: RequirementSpec, slots: Slots, log: LogFn) -> RankResult:
    log("[3-B] 적합도 · 병목 순위 ...")
    # 산출물을 못 쓰면 리뷰축이 전 후보에서 0.5(모름) 고정이라 구성이 달라진다.
    # 조용히 지나가면 "리뷰가 적은 상품들" 로 오해하므로 한 번 알린다.
    reason = risk_store_reason()
    if reason != RISK_STORE_OK:
        log(f"      ⚠ 리뷰축 비활성 — {risk_store_note()} (리뷰 관측 0건으로 계산)")
    ranking = load_computer_rules()["ranking"]
    weights, notes = _weights_for(slots.values, ranking)
    rr = RankResult(weights_used=weights, weight_adjustments=notes)
    for note in notes:
        log(f"      가중치 조정 — {note}")
    purpose = slots.values.get("purpose", "game")
    res = slots.values.get("resolution") or load_computer_rules()["requirements"]["default_resolution"]
    by_purpose = ranking["ideal_tiers"].get(purpose) or {}
    ideals = by_purpose.get(res) or by_purpose.get("default") or {}
    alloc = spec.budget.get("alloc", {})
    total = spec.budget.get("total", 0)

    for slot, cands in hf.slots.items():
        ideal = ideals.get(slot)
        slot_budget = int(total * alloc.get(slot, 0.1)) if total else 1
        target = spec.targets.get(slot, {})
        scored = sorted((_score(c, ideal, slot_budget, slot, target, weights) for c in cands),
                        key=lambda c: c.score, reverse=True)
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
        }
        n_obs = sum(1 for c in scored if c.breakdown.get("리뷰") != _REVIEW_UNKNOWN)
        n_flag = sum(1 for c in scored if c.breakdown.get("리뷰") == _REVIEW_FLAGGED)
        log(f"      {slot}: top-{len(top)}  (ideal_tier={ideal})  1위 score={top[0].score if top else '-'}"
            f"  리뷰관측 {n_obs}/{len(scored)}" + (f" (검토필요 {n_flag})" if n_flag else ""))
    return rr

