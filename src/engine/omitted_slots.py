"""신규 조립에서 일부러 뺀 GPU·쿨러 슬롯의 기록·복원 (docs/추천엔진_GPU쿨러_미구매_구성_계획_20261015.md 7단계).

[2]가 `RequirementSpec.omitted_slots`(슬롯 -> 이유 코드)와 `budget.borrowed_alloc`(빌려 온 배분)을 정한다. 이 값은 추천 실행의 추적 기록
(reasoning_log)에 단계 하나로 저장된다 — 새 컬럼 없이 저장·재조회·개정 복제(reasoning_log 를 통째로 복사)에서 그대로 유지된다.
결과 대화의 재검증(`recommendation_service._current_set`)은 이 단계를 읽어 spec 에 되돌려, 빠진 슬롯을 "정보 없음"으로 세지 않는다.
DB·LLM 없는 순수 함수다.
"""
from __future__ import annotations

from typing import Any

from src.dto import RequirementSpec
from src.engine.compat_parse import parse_ox
from src.engine.stage2_requirement import REINSTATE_REASONS

OMITTED_SLOTS_STEP = "견적 구성 슬롯"

SLOT_LABELS = {"GPU": "그래픽카드", "쿨러": "CPU 쿨러"}
# 이유 코드(OMITTABLE_SLOTS 의 값) -> 화면 문구.
REASON_TEXT = {"integrated_graphics": "내장 그래픽 사용", "box_cooler": "CPU 기본 쿨러 사용"}

# 슬롯별 구매 전 확인 안내(계획 3.3절). 카탈로그에 없는 정보는 없다고 적는다.
NOTES = {
    "GPU": ["메인보드의 영상 출력 단자(HDMI·DP 등)는 카탈로그에 정보가 없어 확인하지 못했습니다. 내장 그래픽을 쓰려면 "
            "메인보드에 영상 출력이 있어야 하니 구매 전 메인보드 사양을 확인해 주세요."],
    "쿨러": ["기본 쿨러는 CPU 정품 박스 제품에만 들어 있습니다(벌크·멀티팩에는 없음). 카탈로그에 포장 형태 정보가 없어 "
             "표시된 가격이 정품 박스 가격인지 확인하지 못했습니다 — 구매 전 판매 상품이 정품 박스인지 확인해 주세요."],
}


def omitted_entries(omitted: dict[str, str]) -> list[dict[str, Any]]:
    """omitted_slots -> API/저장용 항목 목록: {slot, slot_label, reason, reason_text, notes}."""
    return [{"slot": slot, "slot_label": SLOT_LABELS.get(slot, slot), "reason": kind,
             "reason_text": REASON_TEXT.get(kind, kind), "notes": list(NOTES.get(slot, []))}
            for slot, kind in omitted.items()]


def borrowed_entries(borrowed: dict[str, dict]) -> list[dict[str, Any]]:
    """budget.borrowed_alloc -> {slot, ratio, reason, reason_text}. 기본 배분에서 빌려 온 비율과 이유."""
    return [{"slot": slot, "ratio": info["ratio"], "reason": info["reason"],
             "reason_text": REINSTATE_REASONS.get(info["reason"], info["reason"])}
            for slot, info in borrowed.items()]


def build_step(omitted: dict[str, str], borrowed: dict[str, dict]) -> dict | None:
    """reasoning_log 단계. 뺀 슬롯도 빌린 배분도 없으면 None(저장하지 않는다)."""
    if not omitted and not borrowed:
        return None
    bits = [f"{SLOT_LABELS.get(slot, slot)} 미구매({REASON_TEXT.get(kind, kind)}, 용도 배분 0%)" for slot, kind in omitted.items()]
    bits += [f"{SLOT_LABELS.get(b['slot'], b['slot'])} 배분 0% → 기본 배분 {b['ratio']:.0%} 를 빌림({b['reason_text']})"
             for b in borrowed_entries(borrowed)]
    return {"step": OMITTED_SLOTS_STEP, "title": OMITTED_SLOTS_STEP, "detail": " · ".join(bits),
            "omitted_slots": omitted_entries(omitted), "borrowed_alloc": borrowed_entries(borrowed)}


def omitted_from_step(step: dict | None) -> dict[str, str]:
    """저장된 단계 -> {슬롯: 이유 코드}. 단계가 없거나(옛 run) 형식이 다르면 빈 dict."""
    if not isinstance(step, dict):
        return {}
    return {e["slot"]: e["reason"] for e in step.get("omitted_slots") or []
            if isinstance(e, dict) and e.get("slot") and e.get("reason")}


def out_from_step(step: dict | None) -> dict[str, list[dict]]:
    """저장된 단계 -> API 모양 {"omitted_slots": [...], "borrowed_alloc": [...]} (저장된 값을 그대로 — 다시 계산하지 않는다)."""
    if not isinstance(step, dict):
        return {"omitted_slots": [], "borrowed_alloc": []}
    return {"omitted_slots": [e for e in step.get("omitted_slots") or [] if isinstance(e, dict)],
            "borrowed_alloc": [e for e in step.get("borrowed_alloc") or [] if isinstance(e, dict)]}


def apply_to_spec(spec: RequirementSpec, step: dict | None) -> RequirementSpec:
    """재검증용 spec 에 저장된 omitted_slots 를 되돌린다."""
    spec.omitted_slots = omitted_from_step(step)
    return spec


# 뺀 슬롯의 역할을 CPU 가 대신하는지 보는 검사 축 이름(호환 상세·link_check 의 키).
SUBSTITUTE_AXIS = {"GPU": "integrated_graphics", "쿨러": "box_cooler"}


def substitute_state(slot: str, cpu_specs: dict, max_tdp_w: float | None) -> tuple[str, str, object]:
    """뺀 slot(GPU|쿨러)의 역할을 지금 CPU 가 대신하는가 -> (state "ok"|"fail"|"unknown", 설명 문장, 근거 원문 값).

    GPU: 내장 그래픽 O 면 ok, X 면 fail(그래픽카드가 필요), 값이 없거나 읽을 수 없으면 unknown.
    쿨러: 정품 박스 기본 쿨러 X 이거나 CPU TDP 가 허용값(box_cooler_max_tdp_w)을 넘으면 fail(별도 쿨러가 필요), 모르면 unknown.
    엔진의 CPU 사전 필터(stage3a)와 같은 판정이다 — 추천 때는 이미 Pass 인 CPU 만 오고, 결과 대화에서 CPU 를 바꾼 뒤의 재검증이 이걸 쓴다."""
    if slot == "GPU":
        raw = cpu_specs.get("integrated_graphics")
        graphics = parse_ox(raw)
        if graphics is True:
            return "ok", "CPU에 내장 그래픽이 있어 그래픽카드 없이 사용합니다(견적에서 GPU를 뺌)", raw
        if graphics is False:
            return "fail", "CPU에 내장 그래픽이 없는데 이 견적에는 그래픽카드가 없습니다 — 그래픽카드를 담거나 내장 그래픽이 있는 CPU로 바꿔야 합니다", raw
        return "unknown", "CPU의 내장 그래픽 정보가 없어 그래픽카드 없이 쓸 수 있는지 확인하지 못했습니다", raw
    raw = cpu_specs.get("cooler_included")
    box, tdp = parse_ox(raw), cpu_specs.get("tdp_w")
    if box is False:
        return "fail", "CPU 정품 박스에 기본 쿨러가 없는데 이 견적에는 별도 쿨러가 없습니다 — 쿨러를 담거나 기본 쿨러가 있는 CPU로 바꿔야 합니다", raw
    if tdp is not None and max_tdp_w is not None and tdp > max_tdp_w:
        return "fail", f"CPU TDP {tdp}W 가 기본 쿨러 허용 {max_tdp_w:g}W 를 넘는데 이 견적에는 별도 쿨러가 없습니다 — 쿨러를 담아야 합니다", raw
    if box is None or tdp is None:
        return "unknown", "CPU의 기본 쿨러 포함 여부 또는 TDP 정보가 없어 기본 쿨러로 충분한지 확인하지 못했습니다", raw
    return "ok", f"CPU 정품 박스의 기본 쿨러를 씁니다(CPU TDP {tdp}W ≤ 허용 {max_tdp_w:g}W, 별도 쿨러 없음)", raw


def empty_step() -> dict:
    """뺀 슬롯이 하나도 안 남았을 때(결과 대화에서 모두 담음) 저장된 단계를 비우는 값 — 단계 자체는 남겨 둔다(upsert)."""
    return {"step": OMITTED_SLOTS_STEP, "title": OMITTED_SLOTS_STEP, "detail": "", "omitted_slots": [], "borrowed_alloc": []}


def chat_added_slots(step: dict | None) -> dict[str, str]:
    """저장된 단계에서 결과 대화로 담아 배분을 빌린 슬롯 -> {슬롯: "result_chat"}. 다시 [2]를 세울 때 reinstate 로 넘긴다."""
    if not isinstance(step, dict):
        return {}
    return {e["slot"]: "result_chat" for e in step.get("borrowed_alloc") or []
            if isinstance(e, dict) and e.get("reason") == "result_chat" and e.get("slot")}
