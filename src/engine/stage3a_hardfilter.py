"""[3-A] 하드 필터 (Pass / Fail / Pending).

규칙으로 확정 판정 가능한 것만. LLM·RAG 없음.
컴퓨터: 슬롯 내부 조건(perf_tier / socket / capacity ...) — 단방향 확정 제약만.
        양방향 조합 제약(link_rules)은 [4]/[3-C]로 넘긴다.
Pending ≠ Fail: 판정 데이터가 없으면 후보 유지하고 [3-B]에서 감점.
"""
from __future__ import annotations

from src.config import TOP_N_DEFAULT
from src.dto import Candidate, HardFilterResult, RequirementSpec
from src.engine import LogFn

_RATING_ORDER = {"standard": 0, "bronze": 1, "silver": 2, "gold": 3, "platinum": 4, "titanium": 5}


def _rating_rank(text: str | None) -> int | None:
    """"80+ Gold" 든 "Gold" 든 등급명만 찾아서 순위로. 못 찾으면 None(판정 보류)."""
    if not text:
        return None
    t = text.strip().lower()
    for name, rank in _RATING_ORDER.items():
        if name in t:
            return rank
    return None


def _judge_computer(cand: Candidate, target: dict) -> Candidate:
    """[2]가 계산한 target의 단방향(슬롯 내부) 조건을 후보 specs와 전부 비교한다.
    조건이 여러 개면 Fail > Pending > Pass 순으로 가장 나쁜 것을 verdict로 쓰고,
    그 수준의 이유를 전부 모은다. specs에 값이 없는 조건은 Fail로 단정하지 않고
    Pending(판정 보류)으로 남긴다 — override/실측 표가 일부만 채워져 있어서다.

    케이스의 form(데모 고정값)과 쿨러의 tdp_capacity_w_min은 대응하는 실측 컬럼이
    아직 없어 판정하지 않는다(있지도 않은 정보로 단정하지 않는다는 원칙)."""
    checks: list[tuple[str, str]] = []  # (verdict, reason)

    def add(value_present: bool, ok: bool, missing_reason: str, fail_reason: str) -> None:
        if not value_present:
            checks.append(("Pending", missing_reason))
        elif not ok:
            checks.append(("Fail", fail_reason))
        else:
            checks.append(("Pass", "PASS"))

    tier = cand.specs.get("perf_tier")
    tmin = target.get("perf_tier_min")
    if tmin is not None:
        add(tier is not None, tier is not None and tier >= tmin,
            "PENDING_SPEC_MISSING:perf_tier", f"FAIL_PERF_BELOW:{tier}<{tmin}")

    socket_in = target.get("socket_in")
    if socket_in:
        socket = cand.specs.get("socket")
        add(socket is not None, socket in socket_in,
            "PENDING_SPEC_MISSING:socket", f"FAIL_SOCKET_NOT_IN:{socket} not in {socket_in}")

    vram_min = target.get("vram_gb_min")
    if vram_min is not None:
        vram = cand.specs.get("vram_gb")
        add(vram is not None, vram is not None and vram >= vram_min,
            "PENDING_SPEC_MISSING:vram_gb", f"FAIL_VRAM_BELOW:{vram}<{vram_min}")

    mem_type_target = target.get("mem_type") or target.get("type")
    if mem_type_target:
        mem_type = cand.specs.get("mem_type")
        add(mem_type is not None, mem_type == mem_type_target,
            "PENDING_SPEC_MISSING:mem_type", f"FAIL_MEM_TYPE:{mem_type}!={mem_type_target}")

    capacity_min = target.get("capacity_gb_min")
    if capacity_min is not None:
        capacity = cand.specs.get("capacity_gb")
        add(capacity is not None, capacity is not None and capacity >= capacity_min,
            "PENDING_SPEC_MISSING:capacity_gb", f"FAIL_CAPACITY_BELOW:{capacity}<{capacity_min}")

    form_in = target.get("form_in")
    if form_in:
        form = cand.specs.get("form_factor")
        add(form is not None, form in form_in,
            "PENDING_SPEC_MISSING:form_factor", f"FAIL_FORM_NOT_IN:{form} not in {form_in}")

    # 저장장치 target의 "interface"(예: "NVMe")는 실제로는 프로토콜 실측값과 비교한다
    # — 수집 데이터에서 "인터페이스"(PCIe 세대/레인)와 "프로토콜"(NVMe/SATA)이 분리돼 있어서다.
    interface_target = target.get("interface")
    if interface_target:
        protocol = cand.specs.get("protocol")
        add(protocol is not None, protocol is not None and interface_target.lower() in protocol.lower(),
            "PENDING_SPEC_MISSING:protocol", f"FAIL_PROTOCOL:{protocol}!={interface_target}")

    wattage_min = target.get("wattage_min")
    if wattage_min is not None:
        wattage = cand.specs.get("wattage_w")
        add(wattage is not None, wattage is not None and wattage >= wattage_min,
            "PENDING_SPEC_MISSING:wattage_w", f"FAIL_WATTAGE_BELOW:{wattage}<{wattage_min}")

    rating_min = target.get("plus_rating_min")
    if rating_min:
        rank, min_rank = _rating_rank(cand.specs.get("efficiency_rating")), _rating_rank(rating_min)
        add(rank is not None, rank is not None and min_rank is not None and rank >= min_rank,
            "PENDING_SPEC_MISSING:efficiency_rating",
            f"FAIL_RATING_BELOW:{cand.specs.get('efficiency_rating')}<{rating_min}")

    if not checks:
        return cand.model_copy(update={"verdict": "Pass", "reasons": ["PASS"]})
    order = {"Fail": 0, "Pending": 1, "Pass": 2}
    verdict = min(checks, key=lambda vc: order[vc[0]])[0]
    reasons = [r for v, r in checks if v == verdict] if verdict != "Pass" else ["PASS"]
    return cand.model_copy(update={"verdict": verdict, "reasons": reasons})


def run(spec: RequirementSpec, by_slot: dict[str, list[Candidate]], log: LogFn) -> HardFilterResult:
    log("[3-A] 하드 필터 (Pass/Fail/Pending) ...")
    result = HardFilterResult()
    for slot, cands in by_slot.items():
        target = spec.targets.get(slot, {})
        judged = [_judge_computer(c, target) for c in cands]
        p = [c for c in judged if c.verdict == "Pass"]
        pend = [c for c in judged if c.verdict == "Pending"]
        fail = [c for c in judged if c.verdict == "Fail"]

        # Pass 부족 시에만 Pending 승격 (스코어는 [3-B]에서 -20%)
        keep = p if len(p) >= TOP_N_DEFAULT else p + pend
        if not keep:  # 하드 완화 트리거 자리
            log(f"      ! {slot}: Pass 0 / Pending 0 → 하드 완화 필요 (데모는 목 후보로 진행)")
            keep = judged
        result.slots[slot] = keep
        result.stats[slot] = {"pool": len(cands), "pass": len(p),
                              "fail": len(fail), "pending": len(pend)}
        log(f"      {slot}: {len(cands)} → Pass {len(p)} / Fail {len(fail)} / Pending {len(pend)}")
    return result
