"""[3-A] 하드 필터 (Pass / Fail / Pending).

규칙으로 확정 판정 가능한 것만. LLM·RAG 없음.
컴퓨터: 슬롯 내부 조건(perf_tier / socket / capacity ...) — 단방향 확정 제약만.
        양방향 조합 제약(link_rules)은 [4]/[3-C]로 넘긴다.
Pending ≠ Fail: 판정 데이터가 없으면 Fail로 단정하지 않고 보류(held)한다. 점수 계산·순위·조합 탐색에는
Pass만 넘긴다 — Pass가 적어도 Pending·Fail을 끌어올리지 않는다. Pending은 `run(enrich=...)`로 받은
보완 함수에 실행당 한 번 맡겨 근거를 얻은 뒤 같은 판정을 다시 거치고, 그래도 Pass가 없는 대상 슬롯이
있으면 CandidateShortage를 던진다(근거 없는 값을 만들어 채우지 않는다).
"""
from __future__ import annotations

from typing import Callable

from src.dto import Candidate, HardFilterResult, RequirementSpec
from src.engine import LogFn
from src.engine.stage2_requirement import load_computer_rules


def _rating_rank(text: str | None) -> int | None:
    """"80+ Gold" 든 "Gold" 든 등급명만 찾아서 순위로. 못 찾으면 None(판정 보류)."""
    if not text:
        return None
    t = text.strip().lower()
    for rank, label in enumerate(load_computer_rules()["verification"]["efficiency_order"]):
        name = label.lower()
        if name in t:
            return rank
    return None


# 보완 함수: (슬롯, Pending 후보들) -> (보완된 후보 사본들, 시도 기록들). 엔진은 DB를 모른다.
EnrichFn = Callable[[str, list[Candidate]], tuple[list[Candidate], list[dict]]]

_PENDING_SPEC_PREFIX = "PENDING_SPEC_MISSING:"
PENDING_PRICE_INVALID = "PENDING_PRICE_INVALID"

# 사유 코드 -> 안내 문구(모르는 코드는 코드 그대로). Pending은 "~후보 N개", Fail은 "~ N개"로 읽힌다.
_PENDING_LABELS = {
    PENDING_PRICE_INVALID: "가격 정보가 유효하지 않은",
    _PENDING_SPEC_PREFIX + "perf_tier": "성능 등급 정보가 없는",
    _PENDING_SPEC_PREFIX + "socket": "소켓 정보가 없는",
    _PENDING_SPEC_PREFIX + "vram_gb": "VRAM 정보가 없는",
    _PENDING_SPEC_PREFIX + "mem_type": "메모리 규격 정보가 없는",
    _PENDING_SPEC_PREFIX + "capacity_gb": "용량 정보가 없는",
    _PENDING_SPEC_PREFIX + "form_factor": "폼팩터 정보가 없는",
    _PENDING_SPEC_PREFIX + "protocol": "저장장치 규격 정보가 없는",
    _PENDING_SPEC_PREFIX + "wattage_w": "정격 출력 정보가 없는",
    _PENDING_SPEC_PREFIX + "efficiency_rating": "효율 등급 정보가 없는",
}
_FAIL_LABELS = {
    "FAIL_PERF_BELOW": "요구 등급 미달",
    "FAIL_SOCKET_NOT_IN": "소켓 불일치",
    "FAIL_VRAM_BELOW": "VRAM 부족",
    "FAIL_MEM_TYPE": "메모리 규격 불일치",
    "FAIL_CAPACITY_BELOW": "용량 부족",
    "FAIL_FORM_NOT_IN": "폼팩터 불일치",
    "FAIL_PROTOCOL": "저장장치 규격 불일치",
    "FAIL_WATTAGE_BELOW": "정격 출력 부족",
    "FAIL_RATING_BELOW": "효율 등급 미달",
}


class CandidateShortage(Exception):
    """보완·재평가 뒤에도 Pass 후보가 0인 대상 슬롯이 있다 — [3-B]로 넘어가지 않는다.

    slots: Pass가 0인 슬롯 -> {"pass", "pending_reasons", "fail_reasons"}(후보 개수 집계, 한 후보가 사유를 여럿 가지면 각각 센다).
    enrichment: 보완 시도 기록(enrich 함수가 돌려준 dict들)."""

    def __init__(self, slots: dict[str, dict], enrichment: list[dict]):
        self.slots = slots
        self.enrichment = enrichment
        super().__init__(self.summary())

    def summary(self) -> str:
        parts = []
        for slot, info in self.slots.items():
            bits = [f"{_PENDING_LABELS.get(code, code)} 후보 {n}개" for code, n in info.get("pending_reasons", {}).items()]
            bits += [f"{_FAIL_LABELS.get(code, code)} {n}개" for code, n in info.get("fail_reasons", {}).items()]
            parts.append(f"{slot} — " + (", ".join(bits) if bits else "후보가 없습니다"))
        return "추천할 수 있는 후보가 부족해요. " + " / ".join(parts)


def missing_keys(cand: Candidate) -> list[str]:
    """Pending 후보의 보완 대상 키 — 스펙 누락은 그 spec 키, 가격 불량은 "price"."""
    keys = [r[len(_PENDING_SPEC_PREFIX):] for r in cand.reasons if r.startswith(_PENDING_SPEC_PREFIX)]
    if PENDING_PRICE_INVALID in cand.reasons:
        keys.append("price")
    return keys


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

    # 가격이 정수가 아니거나 0 이하이면 평가에서 빼고 보완 대상으로 둔다(bool은 int의 하위 타입이라 따로 거른다).
    if isinstance(cand.price, bool) or not isinstance(cand.price, int) or cand.price <= 0:
        checks.append(("Pending", PENDING_PRICE_INVALID))

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


def _tally(reasons: list[list[str]], *, prefix_only: bool) -> dict[str, int]:
    out: dict[str, int] = {}
    for rs in reasons:
        for r in rs:
            code = r.split(":", 1)[0] if prefix_only else r
            out[code] = out.get(code, 0) + 1
    return out


def _enrich_pending(slot: str, pending: list[Candidate], enrich: EnrichFn | None,
                    log: LogFn) -> tuple[list[Candidate], list[dict]]:
    """Pending 후보를 보완 함수에 한 번만 맡긴다. 함수가 없거나 실패해도 근거 없는 값은 채우지 않는다."""
    if enrich is None:
        return pending, [{"slot": slot, "product_key": c.product_key, "missing_keys": missing_keys(c),
                          "source": None, "status": "no_path", "detail": "보완 경로가 없습니다"} for c in pending]
    try:
        enriched, attempts = enrich(slot, pending)
    except Exception as exc:  # noqa: BLE001 — 보완 실패가 추천 전체를 죽이지 않는다. 재시도하지 않는다.
        log(f"      ! {slot}: 정보 보완 실패 ({type(exc).__name__})")
        return pending, [{"slot": slot, "product_key": c.product_key, "missing_keys": missing_keys(c),
                          "source": None, "status": "failed", "detail": type(exc).__name__} for c in pending]
    by_key = {c.product_key: c for c in enriched}
    return [by_key.get(c.product_key, c) for c in pending], list(attempts)


def run(spec: RequirementSpec, by_slot: dict[str, list[Candidate]], log: LogFn, *,
        enrich: EnrichFn | None = None) -> HardFilterResult:
    log("[3-A] 하드 필터 (Pass/Fail/Pending) ...")
    result = HardFilterResult()
    short: dict[str, dict] = {}
    for slot, cands in by_slot.items():
        if spec.mode == "upgrade" and slot not in spec.targets:
            continue   # 업그레이드에서 그대로 쓰는 부품은 후보를 고르지 않는다(예산 배분도 대상 슬롯에만 있다)
        target = spec.targets.get(slot, {})
        judged = [_judge_computer(c, target) for c in cands]
        keep = [c for c in judged if c.verdict == "Pass"]
        fail = [c for c in judged if c.verdict == "Fail"]
        held = [c for c in judged if c.verdict == "Pending"]

        if held:
            # 보완된 후보도 같은 판정을 다시 거친다. Pass로 확인된 것만 keep에 들어간다.
            enriched, attempts = _enrich_pending(slot, held, enrich, log)
            result.enrichment.extend(attempts)
            rejudged = [_judge_computer(c, target) for c in enriched]
            keep += [c for c in rejudged if c.verdict == "Pass"]
            fail += [c for c in rejudged if c.verdict == "Fail"]
            held = [c for c in rejudged if c.verdict == "Pending"]

        pending_reasons = _tally([c.reasons for c in held], prefix_only=False)
        fail_reasons = _tally([c.reasons for c in fail], prefix_only=True)
        result.slots[slot] = keep
        result.held[slot] = held
        result.stats[slot] = {"pool": len(cands), "pass": len(keep), "fail": len(fail), "pending": len(held),
                              "pending_reasons": pending_reasons, "fail_reasons": fail_reasons}
        log(f"      {slot}: {len(cands)} → Pass {len(keep)} / Fail {len(fail)} / Pending {len(held)}")
        if not keep and slot in spec.targets:
            short[slot] = {"pass": 0, "pending_reasons": pending_reasons, "fail_reasons": fail_reasons}
    for slot in spec.targets:
        if slot not in by_slot and slot not in short:
            short[slot] = {"pass": 0, "pending_reasons": {}, "fail_reasons": {}}
    if short:
        raise CandidateShortage(short, result.enrichment)
    return result
