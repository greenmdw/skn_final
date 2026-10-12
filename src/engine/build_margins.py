"""조합의 전력·냉각·크기 여유 평가 — 선택된 구매 부품과 유지 부품(업그레이드)으로 계산한 기록 (정책 §2.3, 구현계획 4단계).

여유는 **기록**이다. 부품 추천 점수·검증 신뢰도·적격성·탐색 순서를 바꾸지 않고, 새 종합 점수·감점·가산점도 만들지 않는다.
이미 확인된 음수 여유·장착 불가는 기존 호환 검사가 탈락시키며, 여기서는 판정을 다시 하지 않고 값을 그대로 적는다(진단 세트의 음수 값 포함).
정보가 없으면 `unavailable`(빠진 슬롯·키 명시), 이번 견적에서 바뀌지 않는 부품끼리면 `not_applicable`(4a 의 skipped 와 같은 규칙).
값은 필수 정보 판정(stage4_optimize._req_value)과 같은 경로 — 구매 후보 → 유지 부품 — 로 읽고, 수치는 반올림하지 않는다.
DB·LLM 없는 순수 함수다.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.dto import Candidate, RequirementSpec
from src.engine.compat_parse import parse_size_list, slots_needed
from src.engine.stage4_optimize import _blank, _is_liquid, _is_number, _req_value, pc_compat_details

MARGINS_STEP = "조합 여유"
MARGINS_VERSION = 1

AVAILABLE, UNAVAILABLE, NOT_APPLICABLE = "available", "unavailable", "not_applicable"

# 사유 코드
NO_PURCHASED_PART = "no_purchased_part"
INPUTS_MISSING = "inputs_missing"
OTHER_LOAD_BASIS_MISSING = "other_load_basis_missing"
NO_COMPARABLE_THERMAL_TEST = "no_comparable_thermal_test"
LIQUID_COOLER, AIR_COOLER = "liquid_cooler", "air_cooler"
POWER_NOT_IN_SCOPE = "power_not_in_scope"
REQUIREMENT_NOT_RECORDED = "requirement_not_recorded"

_CASE_RADIATOR_KEYS = (("front", "radiator_front_mm"), ("top", "radiator_top_mm"), ("rear", "radiator_rear_mm"))


# ── 입력 읽기 ───────────────────────────────────────────────────────────────────────────────────

def _side(chosen: dict[str, Candidate], slot: str) -> str:
    return "purchase" if slot in chosen else "owned"


def _read(chosen, spec, slot: str, key: str):
    """값 읽기 — 필수 정보 판정(4a)과 같은 경로. 비어 있으면 None."""
    value = _req_value(chosen, spec, slot, key)
    return None if _blank(value) else value


def _input(chosen, spec, slot: str, key: str, value: Any, unit: str | None) -> dict:
    """입력 한 건 — 구매 부품이면 카탈로그 출처(키별 → 제품 페이지)·확인일, 유지 부품이면 출처 종류(catalog/live/…)를 그대로."""
    cand = chosen.get(slot)
    if cand is not None:
        prov = cand.provenance or {}
        return {"slot": slot, "side": "purchase", "name": cand.name, "key": key, "value": value, "unit": unit,
                "source": (prov.get("by_key") or {}).get(key) or prov.get("spec_url") or None,
                "source_kind": "catalog", "checked_at": prov.get("checked_at")}
    info = spec.owned.get(slot) or {}
    return {"slot": slot, "side": "owned", "name": info.get("name"), "key": key, "value": value, "unit": unit,
            "source": info.get("source_url"), "source_kind": info.get("source"), "checked_at": None}


def _missing(chosen, slot: str, key: str, **extra) -> dict:
    return {"slot": slot, "key": key, "side": _side(chosen, slot), **extra}


def _item(status: str, unit: str | None, formula: str, *, value=None, inputs=(), missing=(), reason: str | None = None,
          note: str | None = None, **extra) -> dict:
    return {"status": status, "unit": unit, "value": value if status == AVAILABLE else None, "formula": formula,
            "inputs": list(inputs), "missing": list(missing) if status == UNAVAILABLE else [], "reason": reason,
            "note": note, **extra}


def _not_applicable(unit: str | None, formula: str, reason: str, note: str) -> dict:
    return _item(NOT_APPLICABLE, unit, formula, reason=reason, note=note)


def _no_purchase(chosen, *slots: str) -> bool:
    """이번 견적에서 바뀌는 부품이 이 축에 하나도 없다(4a pc_compat_details 의 skipped 와 같은 기준)."""
    return not any(s in chosen for s in slots)


_NO_PURCHASE_NOTE = "이번 견적에서 바뀌는 부품이 아니라 평가하지 않았습니다."


# ── 크기 ────────────────────────────────────────────────────────────────────────────────────────

def _size_margin(chosen, spec, rules: dict, *, rule: str, formula: str, allowed: tuple[str, str], actual: tuple[str, str]) -> dict:
    """허용치 − 실제 값(mm). rule 은 호환 규칙 절(gpu_length 등)로, allowed/actual 은 (슬롯, 규칙 속 spec 키 항목)."""
    r = rules[rule]
    allowed_slot, allowed_key = allowed[0], r[allowed[1]]
    actual_slot, actual_key = actual[0], r[actual[1]]
    if _no_purchase(chosen, allowed_slot, actual_slot):
        return _not_applicable("mm", formula, NO_PURCHASED_PART, _NO_PURCHASE_NOTE)
    limit, used = _read(chosen, spec, allowed_slot, allowed_key), _read(chosen, spec, actual_slot, actual_key)
    inputs, missing = [], []
    for slot, key, value in ((actual_slot, actual_key, used), (allowed_slot, allowed_key, limit)):
        if _is_number(value):
            inputs.append(_input(chosen, spec, slot, key, value, "mm"))
        else:
            missing.append(_missing(chosen, slot, key))
    if missing:
        return _item(UNAVAILABLE, "mm", formula, inputs=inputs, missing=missing, reason=INPUTS_MISSING,
                     note="값이 없어 여유를 계산하지 못했습니다(충분한 공간으로 간주하지 않음).")
    return _item(AVAILABLE, "mm", formula, value=limit - used, inputs=inputs)


def _cooling_kind(chosen, spec) -> tuple[str, dict | None]:
    """쿨러 종류 -> ("air"|"liquid"|"unknown", 종류를 몰라 생기는 누락 항목)."""
    cooling = _read(chosen, spec, "쿨러", "cooling_type")
    if cooling is None:
        return "unknown", _missing(chosen, "쿨러", "cooling_type")
    return ("liquid" if _is_liquid(cooling) else "air"), None


def _cooler_height(chosen, spec, rules: dict) -> dict:
    formula = "케이스 허용 쿨러 높이 − 쿨러 높이"
    if _no_purchase(chosen, "쿨러", "케이스"):
        return _not_applicable("mm", formula, NO_PURCHASED_PART, _NO_PURCHASE_NOTE)
    kind, gap = _cooling_kind(chosen, spec)
    if kind == "liquid":
        return _not_applicable("mm", formula, LIQUID_COOLER, "수랭 쿨러는 라디에이터 항목이 대신합니다.")
    if kind == "unknown":
        return _item(UNAVAILABLE, "mm", formula, missing=[gap], reason=INPUTS_MISSING,
                     note="쿨러 종류(공랭/수랭)를 몰라 높이 여유를 계산하지 못했습니다.")
    return _size_margin(chosen, spec, rules, rule="cooler_height", formula=formula,
                        allowed=("케이스", "case_spec"), actual=("쿨러", "cooler_spec"))


def _gpu_slots(chosen, spec, rules: dict) -> dict:
    r = rules["gpu_slots"]
    formula = "케이스 확장 슬롯 − 올림(GPU 두께)"
    if _no_purchase(chosen, "GPU", "케이스"):
        return _not_applicable("slot", formula, NO_PURCHASED_PART, _NO_PURCHASE_NOTE)
    thick, expansion = _read(chosen, spec, "GPU", r["gpu_spec"]), _read(chosen, spec, "케이스", r["case_spec"])
    need = slots_needed(thick) if thick is not None else None
    inputs, missing = [], []
    if need is not None:
        inputs.append(_input(chosen, spec, "GPU", r["gpu_spec"], thick, "slot"))
    else:
        missing.append(_missing(chosen, "GPU", r["gpu_spec"]))
    if _is_number(expansion):
        inputs.append(_input(chosen, spec, "케이스", r["case_spec"], expansion, "slot"))
    else:
        missing.append(_missing(chosen, "케이스", r["case_spec"]))
    if missing:
        return _item(UNAVAILABLE, "slot", formula, inputs=inputs, missing=missing, reason=INPUTS_MISSING,
                     note="값이 없어 슬롯 여유를 계산하지 못했습니다(충분한 공간으로 간주하지 않음).")
    return _item(AVAILABLE, "slot", formula, value=expansion - need, inputs=inputs, required_slots=need,
                 note="GPU 두께는 올림한 칸 수로 비교합니다(기존 호환 검사와 같은 기준).")


def _radiator(chosen, spec, rules: dict) -> dict:
    r = rules["radiator"]
    formula = "라디에이터 크기가 케이스 전면·상단·후면 지원 크기에 있는 위치"
    if _no_purchase(chosen, "쿨러", "케이스"):
        return _not_applicable("position", formula, NO_PURCHASED_PART, _NO_PURCHASE_NOTE)
    kind, gap = _cooling_kind(chosen, spec)
    if kind == "air":
        return _not_applicable("position", formula, AIR_COOLER, "공랭 쿨러는 라디에이터를 쓰지 않습니다.")
    if kind == "unknown":
        return _item(UNAVAILABLE, "position", formula, missing=[gap], reason=INPUTS_MISSING,
                     note="쿨러 종류(공랭/수랭)를 몰라 라디에이터 장착 위치를 평가하지 못했습니다.")
    rad = _read(chosen, spec, "쿨러", r["cooler_spec"])
    inputs, missing = [], []
    if _is_number(rad):
        inputs.append(_input(chosen, spec, "쿨러", r["cooler_spec"], rad, "mm"))
    else:
        missing.append(_missing(chosen, "쿨러", r["cooler_spec"]))
    places: dict[str, tuple[int, ...]] = {}
    for (name, _), key in zip(_CASE_RADIATOR_KEYS, r["case_specs"]):
        raw = _read(chosen, spec, "케이스", key)
        places[name] = parse_size_list(raw)
        if places[name]:
            inputs.append(_input(chosen, spec, "케이스", key, raw, "mm"))
    if not any(places.values()):
        missing += [_missing(chosen, "케이스", key, any_of="placement") for key in r["case_specs"]]
    if missing:
        return _item(UNAVAILABLE, "position", formula, inputs=inputs, missing=missing, reason=INPUTS_MISSING,
                     note="값이 없어 라디에이터 장착 위치를 평가하지 못했습니다.")
    fits = [name for name, sizes in places.items() if int(rad) in sizes]
    return _item(AVAILABLE, "position", formula, value=len(fits), inputs=inputs, fits_positions=fits,
                 supported_sizes={name: list(sizes) for name, sizes in places.items()},
                 note=None if fits else "케이스가 지원하는 위치가 없습니다(호환 검사가 탈락 처리).")


# ── 전력 ────────────────────────────────────────────────────────────────────────────────────────

def _power_inputs(chosen, spec, r: dict) -> dict:
    """전력 계산에 쓸 값 — CPU 는 최대 전력, 없으면 TDP(TDP 대체는 누락이 아니다)."""
    peak_key, tdp_key = r.get("cpu_peak_spec", ""), r["cpu_spec"]
    peak, tdp = _read(chosen, spec, "CPU", peak_key), _read(chosen, spec, "CPU", tdp_key)
    if _is_number(peak):
        cpu, cpu_key, basis = peak, peak_key, "max_power"
    elif _is_number(tdp):
        cpu, cpu_key, basis = tdp, tdp_key, "tdp_fallback"
    else:
        cpu, cpu_key, basis = None, None, None
    gpu, psu = _read(chosen, spec, "GPU", r["gpu_spec"]), _read(chosen, spec, "파워", r["psu_spec"])
    inputs, missing = [], []
    if cpu is not None:
        inputs.append(_input(chosen, spec, "CPU", cpu_key, cpu, "W"))
    else:
        missing += [_missing(chosen, "CPU", peak_key, any_of="cpu_power"), _missing(chosen, "CPU", tdp_key, any_of="cpu_power")]
    for slot, key, value in (("GPU", r["gpu_spec"], gpu), ("파워", r["psu_spec"], psu)):
        if _is_number(value):
            inputs.append(_input(chosen, spec, slot, key, value, "W"))
        else:
            missing.append(_missing(chosen, slot, key))
    return {"cpu": cpu, "gpu": gpu if _is_number(gpu) else None, "psu": psu if _is_number(psu) else None,
            "basis": basis, "inputs": inputs, "missing": missing}


def _compat_check(chosen, spec, r: dict, p: dict) -> dict:
    """기존 호환 검사와 같은 범위(CPU + GPU)·같은 계수(psu_capacity_factor)."""
    factor = r["psu_capacity_factor"]
    formula = "파워 정격 × 0.9 − (CPU + GPU)" if factor == 0.9 else f"파워 정격 × {factor:g} − (CPU + GPU)"
    common = {"scope": "cpu_gpu", "factor": factor, "purpose": "기존 호환 검사와 같은 범위·계수"}
    if p["cpu"] is not None and p["gpu"] is not None and p["psu"] is not None:
        extra = {"cpu_basis": p["basis"], "load_w": p["cpu"] + p["gpu"], "usable_w": p["psu"] * factor}
        if p["basis"] == "tdp_fallback":
            extra["limits"] = ["TDP는 최대 패키지 전력보다 낮을 수 있음"]
        return _item(AVAILABLE, "W", formula, value=p["psu"] * factor - (p["cpu"] + p["gpu"]), inputs=p["inputs"], **common, **extra)
    recommended = _read(chosen, spec, "GPU", "recommended_psu_w")
    one_side = ("GPU" in chosen) != ("파워" in chosen)
    if r.get("use_gpu_recommended_psu", True) and one_side and _is_number(recommended) and p["psu"] is not None:
        # 기존 검사가 CPU 전력을 모를 때 쓰는 경로 — 같은 입력(GPU 제조사 권장 파워 · 파워 정격)을 적는다.
        inputs = [i for i in p["inputs"] if i["slot"] == "파워"] + [_input(chosen, spec, "GPU", "recommended_psu_w", recommended, "W")]
        return _item(AVAILABLE, "W", "파워 정격 − GPU 제조사 권장 파워", value=p["psu"] - recommended, inputs=inputs,
                     scope="gpu_recommended_psu", factor=None, purpose="CPU 전력을 몰라 기존 검사가 쓰는 권장 파워 비교",
                     limits=["CPU 전력을 몰라 전체 소비전력은 확인하지 못함"])
    return _item(UNAVAILABLE, "W", formula, inputs=p["inputs"], missing=p["missing"], reason=INPUTS_MISSING,
                 note="전력 값이 없어 여유를 계산하지 못했습니다.", **common)


def _requirement_sizing(spec) -> dict:
    """2단계 요구 산정(프로필 추정치 × 헤드룸 계수 → 표준 용량 올림)이 한 일의 기록 — 다시 계산하지 않는다."""
    formula = "(CPU 추정 + GPU 추정 + 기타 추정) × 헤드룸 계수 → 표준 용량 올림"
    common = {"purpose": "파워 최소 용량 요구 산정", "basis": "profile_estimate"}
    if "파워" not in spec.targets:
        if spec.mode == "upgrade":
            return _item(NOT_APPLICABLE, "W", formula, reason=POWER_NOT_IN_SCOPE,
                         note="이번 업그레이드는 파워를 바꾸지 않아 최소 용량을 산정하지 않았습니다.", **common)
        return _item(UNAVAILABLE, "W", formula, reason=REQUIREMENT_NOT_RECORDED, note="요구 산정 기록이 없습니다.", **common)
    wattage_min = spec.targets["파워"].get("wattage_min")
    if not _is_number(wattage_min):
        return _item(UNAVAILABLE, "W", formula, reason=REQUIREMENT_NOT_RECORDED, note="요구 산정 기록이 없습니다.", **common)
    sizing = spec.power_sizing or {}
    return _item(AVAILABLE, "W", formula, value=wattage_min, **common,
                 estimated_power_w=sizing.get("estimated_power_w"), headroom_multiplier=sizing.get("headroom_multiplier"),
                 required_w=sizing.get("required_w"),
                 limits=["기타 구성품 추정치(other)는 요구 산정용이며 근거 출처가 문서화되어 있지 않음"])


def _total(chosen, spec, rules: dict, p: dict) -> dict:
    """전체 예상 부하 대비 정격 여유 — 기타 구성품 부하의 근거가 설정에 있을 때만. 0.9·1.5 계수는 곱하지 않는다."""
    formula = "파워 정격 − (CPU + GPU + 기타)"
    other = ((rules.get("margins") or {}).get("power") or {}).get("other_load")
    known = p["cpu"] + p["gpu"] if p["cpu"] is not None and p["gpu"] is not None else None
    common = {"factors_applied": [], "known_load_w": known}
    if other is None:
        return _item(UNAVAILABLE, "W", formula, inputs=p["inputs"], missing=p["missing"], reason=OTHER_LOAD_BASIS_MISSING,
                     note="기타 구성품 부하의 근거 값이 없어 전체 전력 여유를 계산하지 않았습니다(CPU+GPU 부하만 기록).", **common)
    if known is None or p["psu"] is None:
        return _item(UNAVAILABLE, "W", formula, inputs=p["inputs"], missing=p["missing"], reason=INPUTS_MISSING,
                     note="전력 값이 없어 여유를 계산하지 못했습니다.", **common)
    inputs = [*p["inputs"], {"slot": None, "side": None, "name": "기타 구성품", "key": "other_load", "value": other["watts"],
                            "unit": "W", "source": other["source"], "source_kind": "config", "checked_at": None}]
    return _item(AVAILABLE, "W", formula, value=p["psu"] - (known + other["watts"]), inputs=inputs, **common,
                 other_load_w=other["watts"], other_load_source=other["source"])


def _power(chosen, spec, rules: dict) -> dict:
    r = rules["power"]
    sizing = _requirement_sizing(spec)
    if _no_purchase(chosen, "CPU", "GPU", "파워"):
        return {"compat_check": _not_applicable("W", "파워 정격 × 0.9 − (CPU + GPU)", NO_PURCHASED_PART, _NO_PURCHASE_NOTE),
                "requirement_sizing": sizing,
                "total": _not_applicable("W", "파워 정격 − (CPU + GPU + 기타)", NO_PURCHASED_PART, _NO_PURCHASE_NOTE)}
    p = _power_inputs(chosen, spec, r)
    return {"compat_check": _compat_check(chosen, spec, r, p), "requirement_sizing": sizing, "total": _total(chosen, spec, rules, p)}


# ── 냉각 ────────────────────────────────────────────────────────────────────────────────────────

def _cooling(chosen, spec, rules: dict) -> dict:
    """입력만 기록한다. 카탈로그에 비교 가능한 냉각 시험 자료가 없고 TDP 차이로 여유를 확정하지 않으므로 항상 unavailable."""
    r = rules["power"]
    pairs = (("CPU", r["cpu_spec"], "W"), ("CPU", r.get("cpu_peak_spec", ""), "W"),
             ("쿨러", "cooling_type", None), ("쿨러", "radiator_mm", "mm"), ("쿨러", "height_mm", "mm"))
    inputs = [_input(chosen, spec, slot, key, _read(chosen, spec, slot, key), unit) for slot, key, unit in pairs if key]
    cpu_name = (chosen["CPU"].name if "CPU" in chosen else (spec.owned.get("CPU") or {}).get("name"))
    case_name = (chosen["케이스"].name if "케이스" in chosen else (spec.owned.get("케이스") or {}).get("name"))
    inputs.append({**_input(chosen, spec, "케이스", "name", case_name, None), "source": None, "source_kind": None, "checked_at": None})
    if cpu_name:
        inputs.append({**_input(chosen, spec, "CPU", "name", cpu_name, None), "source": None, "source_kind": None, "checked_at": None})
    rows = {row["axis"]: row for row in pc_compat_details(chosen, spec, rules)}
    mounting = {axis: {"state": rows[axis]["state"], "detail": rows[axis]["detail"]}
                for axis in ("cooler_socket", "cooler_height", "radiator") if axis in rows}
    return _item(UNAVAILABLE, "W", "—", inputs=inputs, reason=NO_COMPARABLE_THERMAL_TEST,
                 note="비교 가능한 냉각 시험 자료(온도·전력 조건)가 없어 냉각 여유를 확정하지 않았습니다. 쿨러·CPU의 TDP 차이로 계산하지 않습니다.",
                 power_setting="기본 설정 가정(사용자 전력 제한 정보 없음)", mounting=mounting)


# ── 진입점 ──────────────────────────────────────────────────────────────────────────────────────

def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def evaluate_margins(chosen: dict[str, Candidate], spec: RequirementSpec, rules: dict) -> dict:
    """선택된 조합(구매 부품 `chosen` + 유지 부품 `spec.owned`)의 전력·크기·냉각 여유 기록. rules 는 규칙 문서의 verification 절.

    결과는 기록일 뿐이다 — 적격성·점수·신뢰도에 쓰지 않는다(호출부도 그 값을 읽어 판정하지 않는다)."""
    size = {
        "gpu_length": _size_margin(chosen, spec, rules, rule="gpu_length", formula="케이스 허용 GPU 길이 − GPU 길이",
                                   allowed=("케이스", "case_spec"), actual=("GPU", "gpu_spec")),
        "cooler_height": _cooler_height(chosen, spec, rules),
        "psu_length": _size_margin(chosen, spec, rules, rule="psu_length", formula="케이스 허용 파워 길이 − 파워 길이",
                                   allowed=("케이스", "case_spec"), actual=("파워", "psu_spec")),
        "gpu_slots": _gpu_slots(chosen, spec, rules),
        "radiator": _radiator(chosen, spec, rules),
        "not_evaluated": [{"check": "cooler_ram_clearance", "reason": "쿨러의 RAM 간섭 허용 높이 정보 없음"}],
    }
    return _json_safe({"version": MARGINS_VERSION, "power": _power(chosen, spec, rules), "size": size,
                       "cooling": _cooling(chosen, spec, rules)})


def margin_items(margins: dict) -> dict[str, dict]:
    """결과의 평가 항목들을 "power.compat_check" 같은 이름으로 평평하게 — 요약·집계용."""
    out: dict[str, dict] = {}
    for group in ("power", "size"):
        for name, item in (margins.get(group) or {}).items():
            if isinstance(item, dict) and "status" in item:
                out[f"{group}.{name}"] = item
    if isinstance(margins.get("cooling"), dict) and "status" in margins["cooling"]:
        out["cooling"] = margins["cooling"]
    return out


def margins_summary_text(margins: dict) -> str:
    """reasoning_log 단계의 짧은 요약 문장."""
    counts = {AVAILABLE: 0, UNAVAILABLE: 0, NOT_APPLICABLE: 0}
    for item in margin_items(margins).values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return (f"조합 여유 기록(참고용 — 추천 점수·적격성에 반영하지 않음): 계산 {counts[AVAILABLE]}건 · "
            f"확인 불가 {counts[UNAVAILABLE]}건 · 비적용 {counts[NOT_APPLICABLE]}건")
