"""PC 견적 점검 — 용도 대비 균형 (CHK-06).

사용자 조건(용도·해상도·게임·예산)으로 추천엔진 2단계(stage2_requirement)가 정하는 요구 기준을 **그대로** 받아,
견적 속 부품이 그 기준에 부족한지 과한지를 짚는다. 기준을 여기서 다시 정하지 않는다 — 추천 결과와 점검 결과가
같은 눈금을 쓴다. 카탈로그와 같은 제품으로 확정된 부품만 판정하고, 못 읽은 항목은 "확인하지 못함"으로 남긴다.

성능 등급(perf_tier)은 제조사 라인업 등급을 옮긴 거친 눈금이라 같은 등급 안의 세대·모델 차이는 구분하지 못한다
(config/computer_verification_rules.yaml 의 lineup_perf_tier 설명). 그래서 등급이 기준보다 낮을 때만 "부족",
기준보다 EXCESS_TIER_GAP 이상 높을 때만 "과함"으로 본다.
"""
from __future__ import annotations

from typing import Any

from src.categories import load_category
from src.dto import Slots
from src.engine import stage2_requirement
from src.engine.stage2_requirement import load_computer_rules

EXCESS_TIER_GAP = 3            # 요구 등급보다 3 이상 높으면 그 용도에는 과한 부품
EXCESS_RAM_FACTOR = 4          # 요구 용량의 4배 이상이면 과함
SHARE_LOW, SHARE_HIGH = 0.5, 1.8   # 예산 비중이 기준 배분의 0.5배 미만이면 부족 투자, 1.8배 초과면 과투자
MIN_PRICED_SLOTS = 5           # 예산 비중은 가격이 적힌 부품이 이만큼은 있어야 본다(일부만 있으면 비중이 왜곡된다)

PURPOSE_LABEL = {"game": "게임", "creation": "창작", "office": "사무", "study": "학습", "other": "기타"}
RESOLUTION_LABEL = {"FHD_144": "FHD 144Hz", "QHD_165": "QHD 165Hz", "4K": "4K"}
TIER_NOTE = "성능 등급은 제조사 라인업 기준의 거친 값이라 같은 등급 안의 세대·모델 차이는 구분하지 못합니다."


def _num(value: Any) -> str:
    return str(int(value)) if isinstance(value, (int, float)) and float(value).is_integer() else str(value)


def _row(part: str, aspect: str, state: str, detail: str, measured: Any = None, target: Any = None) -> dict:
    return {"part": part, "aspect": aspect, "state": state, "detail": detail, "measured": measured, "target": target}


def requirement_spec(conditions: dict):
    """조건 → 추천엔진 2단계가 정한 요구 기준(RequirementSpec)과 기준 설명."""
    purpose = conditions.get("purpose") or "game"
    values = {"purpose": purpose}
    assumed: list[str] = []
    if conditions.get("resolution"):
        values["resolution"] = conditions["resolution"]
    else:
        assumed.append("resolution")
    if conditions.get("games"):
        values["games"] = list(conditions["games"])
    slots = Slots(category="computer", mode="build", objective_text="견적 점검", values=values, assumed_keys=assumed)
    spec = stage2_requirement.run(slots, load_category("computer"), lambda _msg: None)
    rules = load_computer_rules()["requirements"]
    profile = (rules.get("purpose_profiles") or {}).get(purpose)
    resolution = conditions.get("resolution") or rules["default_resolution"]
    label = PURPOSE_LABEL.get(purpose, purpose)
    if not profile:                                   # 게임·미지정은 해상도로 기준이 정해진다
        label += f" · {RESOLUTION_LABEL.get(resolution, resolution)}" + ("(기본값)" if not conditions.get("resolution") else "")
    return spec, label


def _tier_rows(slot: str, info: dict | None, target: dict, label: str) -> list[dict]:
    if info is None or info.get("source") != "catalog":
        return [_row(slot, "성능 등급", "unknown", "카탈로그에서 같은 제품을 찾지 못해 성능 등급을 확인하지 못했습니다.")]
    tier = (info.get("specs") or {}).get("perf_tier")
    need = target["perf_tier_min"]
    if tier is None:
        return [_row(slot, "성능 등급", "unknown", "이 제품의 성능 등급 자료가 없어 확인하지 못했습니다.", None, need)]
    if tier < need:
        state, verb = "short", f"{label} 기준 {_num(need)}보다 낮습니다"
    elif tier - need >= EXCESS_TIER_GAP:
        state, verb = "excess", f"{label} 기준 {_num(need)}보다 {_num(tier - need)}단계 높아 이 용도에는 과합니다"
    else:
        state, verb = "ok", f"{label} 기준 {_num(need)} 이상을 충족합니다"
    rows = [_row(slot, "성능 등급", state, f"{slot} 성능 등급 {_num(tier)} — {verb}.", tier, need)]
    vram_need = target.get("vram_gb_min")
    vram = (info.get("specs") or {}).get("vram_gb")
    if slot == "GPU" and vram_need is not None and vram is not None:
        ok = vram >= vram_need
        rows.append(_row(slot, "VRAM", "ok" if ok else "short",
                         f"GPU VRAM {_num(vram)}GB {'≥' if ok else '<'} 요구 {_num(vram_need)}GB ({label} 기준).", vram, vram_need))
    return rows


def _capacity_row(slot: str, info: dict | None, need: int, key: str, label: str, excess_factor: int | None) -> dict:
    aspect = "용량"
    if info is None:
        return _row(slot, aspect, "unknown", "견적에 이 부품이 없어 확인하지 못했습니다.")
    value = (info.get("specs") or {}).get(key)
    if value is None:
        return _row(slot, aspect, "unknown", "글에서 용량을 읽지 못해 확인하지 못했습니다.", None, need)
    if value < need:
        return _row(slot, aspect, "short", f"{slot} {_num(value)}GB < 요구 {_num(need)}GB ({label} 기준).", value, need)
    if excess_factor and value >= need * excess_factor:
        return _row(slot, aspect, "excess", f"{slot} {_num(value)}GB — 요구 {_num(need)}GB의 {excess_factor}배 이상이라 이 용도에는 과합니다.", value, need)
    return _row(slot, aspect, "ok", f"{slot} {_num(value)}GB ≥ 요구 {_num(need)}GB ({label} 기준).", value, need)


def _budget_rows(spec, prices: dict, budget_max: int | None) -> list[dict]:
    rows: list[dict] = []
    quoted = {r["part"]: r["quoted"] for r in (prices.get("rows") or []) if r.get("quoted") is not None}
    if not quoted:
        return rows
    total = sum(quoted.values())
    complete = bool((prices.get("summary") or {}).get("quote_total_complete"))
    if budget_max:
        if total > budget_max:
            note = "" if complete else " (가격이 없는 부품이 있어 실제 합계는 더 큽니다)"
            rows.append(_row("예산", "예산", "excess", f"견적 합계 {total:,}원 > 예산 {budget_max:,}원{note}.", total, budget_max))
        elif complete:
            rows.append(_row("예산", "예산", "ok", f"견적 합계 {total:,}원 ≤ 예산 {budget_max:,}원.", total, budget_max))
        else:
            rows.append(_row("예산", "예산", "unknown", "가격이 없는 부품이 있어 합계가 예산 안인지 확정하지 못했습니다.", total, budget_max))
    alloc = spec.budget.get("alloc") or {}
    priced = [s for s in quoted if s in alloc]
    if len(priced) >= MIN_PRICED_SLOTS and "GPU" in priced and "CPU" in priced:
        base = sum(alloc[s] for s in priced)
        spent = sum(quoted[s] for s in priced)
        for slot in priced:
            share, target = quoted[slot] / spent, alloc[slot] / base
            ratio = share / target
            if ratio < SHARE_LOW or ratio > SHARE_HIGH:
                state = "short" if ratio < SHARE_LOW else "excess"
                verdict = "기준보다 적게 쓰였습니다" if state == "short" else "기준보다 많이 쓰였습니다"
                rows.append(_row(slot, "예산 비중", state,
                                 f"{slot}에 견적 가격의 {share:.0%}가 쓰였습니다(권장 배분 {target:.0%}) — {verdict}.",
                                 round(share, 3), round(target, 3)))
    return rows


def assess(conditions: dict | None, owned: dict[str, dict], prices: dict) -> dict:
    """견적 속 부품을 사용자 조건의 요구 기준과 견준다. 조건이 없으면 판단하지 않는다."""
    conditions = {k: v for k, v in (conditions or {}).items() if v not in (None, "", [])}
    if not conditions.get("purpose"):
        return {"available": False, "reason": "용도(게임·사무 등)를 알려 주지 않아 용도 대비 균형을 판단하지 않았습니다.",
                "requirement": None, "rows": [], "summary": {}, "notes": []}
    spec, label = requirement_spec(conditions)
    t = spec.targets
    rows: list[dict] = []
    for slot in ("CPU", "GPU"):
        if slot in owned:
            rows += _tier_rows(slot, owned[slot], t[slot], label)
    if "RAM" in owned:
        rows.append(_capacity_row("RAM", owned["RAM"], t["RAM"]["capacity_gb_min"], "capacity_gb", label, EXCESS_RAM_FACTOR))
    if "저장장치" in owned:
        rows.append(_capacity_row("저장장치", owned["저장장치"], t["저장장치"]["capacity_gb_min"], "capacity_gb", label, None))
    rows += _budget_rows(spec, prices, conditions.get("budget_max"))
    counts = {s: sum(r["state"] == s for r in rows) for s in ("short", "excess", "ok", "unknown")}
    notes = [TIER_NOTE]
    if "resolution_assumed" in spec.flags:
        notes.append("해상도를 알려 주지 않아 기본 해상도 기준으로 판단했습니다.")
    for item in spec.unresolved:
        if item.get("key") == "games":
            notes.append(f"'{item['value']}'는 요구사양 표에 없어 해상도 기준으로 판단했습니다.")
    return {
        "available": True, "reason": None,
        "requirement": {"label": label, "purpose": conditions["purpose"], "resolution": conditions.get("resolution"),
                        "gpu_tier_min": t["GPU"]["perf_tier_min"], "cpu_tier_min": t["CPU"]["perf_tier_min"],
                        "ram_gb_min": t["RAM"]["capacity_gb_min"], "vram_gb_min": t["GPU"]["vram_gb_min"]},
        "rows": rows, "summary": counts, "notes": notes,
    }
