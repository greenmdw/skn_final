"""[3-B] 적합도 · 병목 순위.

[3-A] 통과분을 슬롯별 점수화 → 슬롯별 top-N. LLM·RAG 없음.
score = Σ w_axis·norm_axis − (Pending 이면 0.20).
축: 가격 / 성능 여유 / 밸런스 적합 / 리뷰 적합도 / 호환 여유.
병목: balance_profiles 의 ideal_tier 대비 최선 후보가 낮으면 bottleneck_hint 방출.
"""
from __future__ import annotations

from src.config import PENDING_SCORE_PENALTY, TOP_N_DEFAULT, TOP_N_IMPACT
from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, ReviewScoreDetail, Slots
from src.engine import LogFn
from src.engine.stage2_requirement import load_computer_rules


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


def _data_gap_keys(cands: list[Candidate], slot: str, gap: dict) -> list[str]:
    """검사용 스펙 중, 이 슬롯 후보 가운데 하나라도 값이 있는 것. 아무도 값이 없는 열은 "데이터가 아직 없는 것"이지
    후보 간 차이가 아니므로 감점 대상에서 뺀다(빈 카탈로그의 점수가 바뀌지 않게)."""
    return [k for k in (gap.get("specs") or {}).get(slot, []) if any(c.specs.get(k) is not None for c in cands)]


def _data_gap_penalty(cand: Candidate, gap_keys: list[str], gap: dict) -> float:
    missing = sum(1 for k in gap_keys if cand.specs.get(k) is None)
    return min(missing * gap.get("penalty_per_key", 0.0), gap.get("max_penalty", 0.0))


def _ram_dual_channel_bonus(cand: Candidate, slot: str, target: dict, ranking: dict) -> float:
    """개발요청 7번 — RAM은 perf_tier가 없어 성능·밸런스 축이 중립 고정이라 같은 총 용량이면
    가격만으로 갈렸고, 단일 모듈이 듀얼채널(모듈 2개 이상) 키트보다 늘 이겼다. breakdown 축이
    아니라 gap_penalty처럼 최종 점수에만 더한다(우선순위별 weights 표를 새로 만들 필요가 없다).

    딱 필요한 용량(capacity_gb_min)과 같은 후보에만 준다 — 그보다 큰 용량까지 우대하면
    "16GB 듀얼(8GB×2)"이 아니라 "32GB 듀얼(16GB×2)"처럼 필요보다 큰(그래서 훨씬 비싼) 키트가
    가격 축이 0으로 뭉개지는 예산 초과 구간에서 단지 module_count>=2 라는 이유로 이겨버렸다
    (실측: 예산 200만·가성비 우선주에서 33만원 16GB 단일 대신 91만원 32GB 듀얼을 골랐다)."""
    if slot != "RAM":
        return 0.0
    need = target.get("capacity_gb_min")
    capacity = cand.specs.get("capacity_gb")
    if need is None or capacity is None or capacity != need:
        return 0.0
    from src.engine.compat_parse import parse_module_count

    count = parse_module_count(cand.specs.get("module_config"))
    return float(ranking.get("ram_dual_channel_bonus", 0.0)) if count is not None and count >= 2 else 0.0


def _score(cand: Candidate, ideal_tier: float | None, slot_budget: int, slot: str, target: dict,
           weights: dict[str, float] | None = None, gap_penalty: float = 0.0,
           review_detail: ReviewScoreDetail | None = None) -> Candidate:
    tier = float(cand.specs.get("perf_tier", 5))
    price = cand.price or 1
    review_detail = review_detail or cand.review_detail
    # Pure engine unit tests may omit injected review data. Runtime orchestration sets
    # require_review_details=True, so DB paths cannot silently take this neutral branch.
    review = review_detail.value if review_detail is not None else 0.5
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
    raw -= gap_penalty
    raw += _ram_dual_channel_bonus(cand, slot, target, ranking)
    rounded_breakdown = {k: (v if k == "리뷰" else round(v, 3)) for k, v in b.items()}
    return cand.model_copy(update={"score": round(raw, 3), "breakdown": rounded_breakdown,
                                   "review_detail": review_detail})


def run(hf: HardFilterResult, spec: RequirementSpec, slots: Slots, log: LogFn, *,
        require_review_details: bool = False) -> RankResult:
    log("[3-B] 적합도 · 병목 순위 ...")
    if require_review_details:
        missing = [c.product_key for cands in hf.slots.values() for c in cands if c.review_detail is None]
        if missing:
            raise ValueError(f"review score is missing for {len(missing)} ranked candidates")
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
        # games 는 [2]가 targets[slot]["perf_tier_min"](하한)만 올려서, 무거운 게임을
        # 골라도 밸런스 축의 ideal_tier 는 용도·해상도로만 정해진 값에 그대로 머물렀다.
        # 하한이 ideal 보다 높아진 슬롯만 ideal 을 그 하한까지 끌어올린다(낮추지는 않는다).
        # ideal 표에 없는 슬롯(ideal=None)은 밸런스 축이 중립 0.5 로 빠지는 자리라 그 의미를
        # 바꾸지 않으려고 건드리지 않는다 — None 그대로 둔다.
        if "games_applied" in spec.flags and ideal is not None:
            perf_min = spec.targets.get(slot, {}).get("perf_tier_min")
            if perf_min is not None and perf_min > ideal:
                note = f"게임 요구 반영: {slot} 이상 등급 {ideal:g}→{perf_min:g}"
                rr.weight_adjustments.append(note)
                log(f"      가중치 조정 — {note}")
                ideal = float(perf_min)
        slot_budget = int(total * alloc.get(slot, 0.1)) if total else 1
        target = spec.targets.get(slot, {})
        gap = ranking.get("data_gap") or {}
        gap_keys = _data_gap_keys(cands, slot, gap)
        penalties = {c.product_key: _data_gap_penalty(c, gap_keys, gap) for c in cands} if gap_keys else {}
        scored = sorted((_score(c, ideal, slot_budget, slot, target, weights, penalties.get(c.product_key, 0.0))
                         for c in cands), key=lambda c: c.score, reverse=True)
        if any(penalties.values()):
            log(f"      {slot}: 검사용 스펙({', '.join(gap_keys)})이 빈 후보 {sum(1 for v in penalties.values() if v)}/{len(cands)}개 감점")
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
        observed = sum(
            1 for c in scored if c.review_detail and any(
                item.p + item.n + item.mixed > 0 for item in c.review_detail.contributions
            )
        )
        log(f"      {slot}: top-{len(top)}  (ideal_tier={ideal})  1위 score={top[0].score if top else '-'}"
            f"  리뷰 관측 {observed}/{len(scored)}")
    return rr

