"""조합 적격성 — 정상 추천 가능 여부(eligibility)의 공용 상수·문장 (정책 §5.2~§5.4, 구현계획 4단계).

적격성은 신뢰도 점수와 별개로 판정한다: 확인된 호환 위반·필수 호환 정보 누락·사용자 필수 요구 미충족·예산 초과·호환 세트 없음
중 하나라도 있으면 `not_recommendable` 이고, 부품표는 진단용으로만 보여 준다. 이 모듈은 순수 함수만 둔다(DB·LLM 없음).
"""
from __future__ import annotations

from typing import Any

from src.engine.brands import PC_SLOTS

ELIGIBILITY_STEP = "추천 적격성"
RECOMMENDABLE, NOT_RECOMMENDABLE = "recommendable", "not_recommendable"

COMPAT_VIOLATION = "compat_violation"
REQUIRED_INFO_MISSING = "required_info_missing"
REQUIREMENT_UNMET = "requirement_unmet"
BUDGET_EXCEEDED = "budget_exceeded"
NO_COMPATIBLE_SET = "no_compatible_set"
VERIFICATION_INPUTS_MISSING = "verification_inputs_missing"

# 사유 코드의 표시 순서
REASON_ORDER = (COMPAT_VIOLATION, REQUIRED_INFO_MISSING, REQUIREMENT_UNMET, BUDGET_EXCEEDED, NO_COMPATIBLE_SET,
                VERIFICATION_INPUTS_MISSING)

# ── 설정 `verification.required_checks` 가 쓸 수 있는 이름(stage2 가 검증하고 stage4 가 해석한다) ──────────────────
REQUIRED_CHECK_AXES = (
    "socket", "memory", "motherboard_case", "bios", "cooler_socket", "cooler_height", "radiator", "gpu_len",
    "gpu_slots", "psu_form", "psu_length", "power", "gpu_connector", "gpu_connector_count", "ram_slots", "m2", "ram_speed",
)
REQUIRED_CHECK_WHEN = ("socket_not_failed", "air_cooler", "liquid_cooler", "gpu_aux_power", "m2_ssd", "user_ram_speed")
REQUIRED_CHECK_PARSE = (
    "number", "form", "form_list", "cpu_families", "socket_list", "size_list", "slot_thickness", "psu_form", "psu_forms",
    "gpu_connector", "psu_connector", "module_count",
)
REQUIRED_CHECK_SLOTS = PC_SLOTS
REQUIRED_CHECK_KEY_FIELDS = {"slot", "key", "any_of", "parse", "as"}
REQUIRED_CHECK_AXIS_FIELDS = {"keys", "when", "row_axis"}


def row_axis(check: dict, axis: str) -> str:
    """검사 축이 호환 점검 상세의 어느 행에 속하는가(개수 검사는 gpu_connector 행에 합쳐진다)."""
    return check.get("row_axis") or axis


def is_fail_state(state: Any) -> bool:
    """link_check 값이 확정된 위반인가(verify_build 가 "위반" 쟁점으로 세는 것과 같은 판정)."""
    text = str(state).lower()
    return "fail" in text or "미충족" in text or "over" in text


def blocking_entries(link_check: dict, findings: list[dict], *, budget_exceeded: bool) -> list[dict]:
    """정상 추천을 막는 사유 목록 [{code, axis?, missing?}] — build_computer 와 verify_build 가 같은 규칙을 쓴다.

    확인된 위반(link_check fail, set 은 따로) · 예산 초과 · 필수 정보 누락 · 사용자 필수 요구 미충족. 신뢰도 점수와 무관하다."""
    out: list[dict] = []
    for axis, state in (link_check or {}).items():
        if axis not in ("budget", "예산") and is_fail_state(state):
            out.append({"code": NO_COMPATIBLE_SET if axis == "set" else COMPAT_VIOLATION, "axis": axis})
    if budget_exceeded:
        out.append({"code": BUDGET_EXCEEDED, "axis": "budget"})
    for f in findings:
        if f["missing"]:
            out.append({"code": REQUIRED_INFO_MISSING, "axis": f["row_axis"], "missing": f["missing"]})
        if f["unmet"]:
            out.append({"code": REQUIREMENT_UNMET, "axis": f["row_axis"]})
    return out


def make_eligibility(blocking: list[dict]) -> dict[str, Any]:
    """blocking(항목별 {code, axis?, missing?}) → {"status", "reasons": [{"code", "axes", "missing"?}]}. 같은 코드는 한 사유로 묶는다."""
    reasons: list[dict[str, Any]] = []
    for code in REASON_ORDER:
        entries = [b for b in blocking if b.get("code") == code]
        if not entries:
            continue
        reason: dict[str, Any] = {"code": code, "axes": list(dict.fromkeys(b["axis"] for b in entries if b.get("axis")))}
        seen: set[tuple] = set()
        missing = []
        for m in (m for b in entries for m in b.get("missing") or []):
            ident = (m["slot"], m["key"], m.get("side"), m.get("product_key"))
            if ident not in seen:                 # 같은 값이 여러 축에서 걸려도 한 번만(예: 쿨러 냉각 방식)
                seen.add(ident)
                missing.append(m)
        if missing:
            reason["missing"] = missing
        reasons.append(reason)
    return {"status": NOT_RECOMMENDABLE if reasons else RECOMMENDABLE, "reasons": reasons}


def _part_label(item: dict) -> str:
    return f"{'쓰고 계신' if item.get('side') == 'owned' else '추천 구성의'} {item['slot']}"


def _key_label(slot: str, key: str) -> str:
    from src.engine.stage3c_verify import _KEY_LABEL
    label = _KEY_LABEL.get((slot, key))
    return label or key


def missing_text(missing: list[dict]) -> str:
    """누락 항목 → "쓰고 계신 파워의 파워 용량, 추천 구성의 케이스의 …" 식 한 문장 조각(부품 이름이 있으면 괄호로)."""
    parts = []
    for m in missing:
        name = f"({m['name']})" if m.get("name") else ""
        parts.append(f"{_part_label(m)}{name}의 '{_key_label(m['slot'], m['key'])}'")
    return ", ".join(dict.fromkeys(parts))


def reason_text(reason: dict) -> str:
    from src.engine.stage3c_verify import axis_label
    code, axes = reason.get("code"), reason.get("axes") or []
    names = ", ".join(axis_label(a) for a in axes)
    if code == COMPAT_VIOLATION:
        return f"서로 맞지 않는 부품이 있어요({names})"
    if code == REQUIRED_INFO_MISSING:
        return f"호환 확인에 꼭 필요한 정보가 없어요 — {missing_text(reason.get('missing') or [])}"
    if code == REQUIREMENT_UNMET:
        return f"요청하신 조건을 만족하지 못해요({names})"
    if code == BUDGET_EXCEEDED:
        return "예산을 넘어요"
    if code == NO_COMPATIBLE_SET:
        return "서로 호환되는 구성을 찾지 못했어요"
    return "검증에 필요한 입력이 없어요"


NOTICE_PREFIX = "정상 추천 조건을 만족하는 구성을 찾지 못해 확인용 구성을 보여 드려요"


def eligibility_notice(eligibility: dict | None) -> str | None:
    """부적격일 때 설명 요약 앞에 붙이는 안내 문장(코드가 만든다 — LLM 아님). 적격이면 None."""
    if not eligibility or eligibility.get("status") != NOT_RECOMMENDABLE:
        return None
    reasons = [reason_text(r) for r in eligibility.get("reasons") or []]
    owned = [m for r in eligibility.get("reasons") or [] for m in r.get("missing") or [] if m.get("side") == "owned"]
    text = f"{NOTICE_PREFIX}: " + "; ".join(reasons) + "."
    if owned:
        text += " 쓰고 계신 부품은 모델명을 정확히 알려 주시면 확인할 수 있어요."
    return text
