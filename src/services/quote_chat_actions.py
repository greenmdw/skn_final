"""받은 견적 점검 채팅의 **동작**(재기획 6단계) — 말로 교체 담기·빼기, 조건 바꾸기, 제품 확정, 정보 찾기, 다시 분석하기.

원칙(재기획 7절):
- 동작을 읽는 것은 LLM 이 아니라 **코드 규칙**이다. 사용자가 *요청하는 말투*("~해줘", "~담아", "~빼줘")로 말했을 때만 동작하고,
  "~하면 어때?"·"알려줘"·"비교해줘" 같은 질문은 동작하지 않는다(그건 기존 읽기 답변으로 간다).
- 동작은 이미 있는 서비스 함수(`quote_draft_service`)를 그대로 부른다 — 소유권 검사·버전 검사·후보 규칙이 거기서 지켜진다.
- 답변 문장은 코드가 만든다(바뀐 결과와 영향). 동작을 했으면 응답에 `action`(무엇을 했는지 · 되돌리는 방법)을 싣는다.
- 새 비호환이 생기는 교체는 담지 않는다. 성능이 낮아지는 교체는 담되 경고한다.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from src.auth.deps import Principal
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import NotFound, TruefitError
from src.services import quote_draft_service as qds
from src.services import quote_replacement_plan
from src.services.quote_chat_service import extract_targets, match_slot

log = logging.getLogger(__name__)

# 질문·정보 요청 말투 — 하나라도 있으면 동작이 아니다.
_INFO_WORDS = ("알려", "보여", "비교", "차이", "어때", "괜찮", "왜 ", "뭐가", "뭐야", "얼마", "될까", "돌아가", "있어?", "인가요", "나요", "까요", "ㄹ까")
# 요청 말투
_REQUEST = re.compile(r"(해\s?줘|해\s?주세요|해\s?줄래|해\s?봐|해\s?라$|줘$|주세요$|줄래$|할게$|하자$|담아|넣어|빼$|빼\s?줘|빼\s?주|지워|취소|되돌려|고쳐|바꿔|정해|확정해|선택해|찾아|검색해)")
_ALL = ("전부", "모두", "다 ", "전체")
_PURPOSE = {"게임": "game", "창작": "creation", "영상": "creation", "작업": "creation", "사무": "office", "학습": "study", "공부": "study"}
_PRIORITY = (("저소음", "quiet"), ("조용", "quiet"), ("가성비", "value"), ("성능", "performance"))
_RESOLUTION = (("fhd", "FHD_144"), ("qhd", "QHD_165"), ("4k", "4K"), ("uhd", "4K"))
_PURPOSE_LABEL = {"game": "게임", "creation": "창작", "office": "사무", "study": "학습", "other": "기타"}
_PRIORITY_LABEL = {"performance": "성능 우선", "value": "가성비", "quiet": "저소음"}
_RESOLUTION_LABEL = {"FHD_144": "FHD 144Hz", "QHD_165": "QHD 165Hz", "4K": "4K"}
_MONEY = re.compile(r"(\d+(?:\.\d+)?)\s*(만\s*원|만|원)")


def _won(value: int | float) -> str:
    return f"{int(value):,}원"


def _signed(value: int) -> str:
    return ("+" if value > 0 else "-" if value < 0 else "") + f"{abs(int(value)):,}원"


def is_request(text: str) -> bool:
    low = text.strip().rstrip("?").lower()
    if any(w in low for w in _INFO_WORDS) or text.strip().endswith("?") and "줄래" not in low and "주세요" not in low:
        return False
    return bool(_REQUEST.search(low))


def _money(text: str) -> int | None:
    match = _MONEY.search(text.replace(",", ""))
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2).replace(" ", "")
    return int(number * 10_000) if unit.startswith("만") else int(number)


# ── 해석: 말 → 동작 계획 ───────────────────────────────────────────────────────
def parse(text: str, *, analyzed: bool, replaced: set[str]) -> dict[str, Any] | None:
    """요청 말투일 때만 동작 계획을 낸다. 계획: {"kind", ...}. 모르면 None(읽기 답변으로)."""
    if not is_request(text):
        return None
    low = text.lower()
    slot = match_slot(low)

    if re.search(r"(다시|재)\s*분석", text):
        return {"kind": "reanalyze"}

    if "교체" in text and re.search(r"(빼|제거|삭제|취소|되돌|비워|지워)", text):
        if any(w in text for w in _ALL) or ("목록" in text and "비워" in text):
            return {"kind": "remove_all"}
        if slot:
            return {"kind": "remove", "slot": slot}
    if slot and slot in replaced and re.search(r"(되돌려|취소|빼\s?줘|빼\s?주|빼$)", text):
        return {"kind": "remove", "slot": slot}

    condition = _parse_condition(text, low)
    if condition:
        return condition

    if slot and re.search(r"(정보|스펙|사양).{0,6}(찾|검색)|검색해", text):
        return {"kind": "lookup", "slot": slot}

    if slot and re.search(r"교체\s*(목록)?\s*에?\s*(담|넣|추가)", text):
        return {"kind": "add", "slot": slot, "text": text}
    if slot and re.search(r"(으로|로)\s*(바꿔|교체)", text):
        return {"kind": "add" if analyzed else "fix", "slot": slot, "text": text}
    if slot and re.search(r"(으로|로)\s*(정해|확정|선택|고쳐|수정)", text):
        return {"kind": "fix", "slot": slot, "text": text}
    return None


def _parse_condition(text: str, low: str) -> dict[str, Any] | None:
    if "교체" in text and "예산" in text:
        return None                    # 교체 예산은 없다 — 총예산으로 잘못 읽지 않는다
    if "예산" in text:
        amount = _money(text)
        if amount is not None:
            return {"kind": "condition", "patch": {"budget_max": amount}}
    if "용도" in text:
        for word, value in _PURPOSE.items():
            if word in text:
                return {"kind": "condition", "patch": {"purpose": value}}
    if "해상도" in text or re.search(r"(fhd|qhd|4k|uhd)", low):
        for word, value in _RESOLUTION:
            if word in low:
                return {"kind": "condition", "patch": {"resolution": value}}
    if "우선순위" in text or "우선" in text:
        for word, value in _PRIORITY:
            if word in text:
                return {"kind": "condition", "patch": {"priority": value}}
    return None


# ── 실행 ───────────────────────────────────────────────────────────────────────
def _item_for(draft: dict, slot: str) -> dict | None:
    chosen = draft["selected_item_by_category"].get(slot)
    return next((i for i in draft["items"] if i["id"] == chosen), None) or next((i for i in draft["items"] if i["category"] == slot), None)


def _replacement_sentence(state: dict, slot: str) -> str:
    row = next((r for r in state["replacements"] if r["slot"] == slot), None)
    parts = []
    if row:
        delta = row["price_delta"]
        parts.append(f"가격 차이 {_signed(delta)}" if delta is not None else "현재 부품 가격을 몰라 가격 차이는 알 수 없어요")
    before, after = state["compat"]["before"].get("fail", 0), state["compat"]["after"].get("fail", 0)
    parts.append(f"확정된 호환 문제 {before}개 → {after}개")
    return ", ".join(parts)


def _do_add(conn, list_id: UUID, principal: Principal, draft: dict, review: dict, plan: dict) -> tuple[str, dict | None]:
    slot, text = plan["slot"], plan["text"]
    by_slot = load_pc_catalog(lambda _msg: None)
    pool = by_slot.get(slot, [])
    item = _item_for(draft, slot)
    named = extract_targets(text, slot, pool, exclude_name=(item or {}).get("matched_name"))
    if len(named) > 1:
        return f"{slot} 후보가 여러 개로 읽혀요({', '.join(named[:3])}). 하나만 정확히 말해 주세요.", None
    if named:
        cand = next(c for c in pool if c.name == named[0])
        product_id, name = cand.product_id, cand.name
    else:
        targets = quote_replacement_plan.build_targets(review, by_slot, conn=conn, limit=1)
        target = next((t for t in targets["targets"] if t["slot"] == slot), None)
        if not target or not target["candidates"]:
            note = (target or {}).get("note")
            return f"{slot}에 담을 추천 후보가 없어요.{(' ' + note) if note else ''} 제품 이름을 말해 주시면 확인해 볼게요.", None
        top = target["candidates"][0]
        product_id, name = top["product_id"], top["name"]
    previous = (draft.get("replacements") or {}).get(slot)
    state = qds.set_replacement(conn, list_id, principal, draft["version"], slot, product_id)
    row = next(r for r in state["replacements"] if r["slot"] == slot)
    if "new_incompatible" in row["warnings"]:
        # 새 호환 문제가 생기는 교체는 담지 않는다 — 방금 담은 것을 되돌린다.
        revert = (qds.set_replacement(conn, list_id, principal, state["draft_version"], slot, previous["candidate_product_id"])
                  if previous else qds.remove_replacement(conn, list_id, principal, state["draft_version"], slot))
        del revert
        return f"{name}(으)로 바꾸면 견적의 다른 부품과 새로 호환 문제가 생겨서 교체 목록에 담지 않았어요.", None
    warning = " 현재 부품보다 성능이 낮아요." if "grade_lower" in row["warnings"] else ""
    label = f"교체 목록에 담기 · {slot}"
    undo = ({"kind": "put_replacement", "slot": slot, "product_id": previous["candidate_product_id"]} if previous
            else {"kind": "remove_replacement", "slot": slot})
    return (f"{slot}을(를) {row['from']['name'] or '현재 부품'} → {name}(으)로 교체 목록에 담았어요. {_replacement_sentence(state, slot)}.{warning}",
            {"kind": "add_replacement", "label": label, "undo": undo})


def _do_remove(conn, list_id, principal, draft, plan) -> tuple[str, dict | None]:
    current = dict(draft.get("replacements") or {})
    slots = list(current) if plan["kind"] == "remove_all" else [plan["slot"]]
    slots = [s for s in slots if s in current]
    if not slots:
        return "교체 목록에 빼거나 되돌릴 부품이 없어요.", None
    version = draft["version"]
    state = None
    for slot in slots:
        state = qds.remove_replacement(conn, list_id, principal, version, slot)
        version = state["draft_version"]
    undo = {"kind": "restore_replacements", "items": [{"slot": s, "product_id": current[s]["candidate_product_id"]} for s in slots]}
    names = ", ".join(f"{s}({current[s]['candidate_name']})" for s in slots)
    return (f"교체 목록에서 {names}을(를) 뺐어요. 이제 교체 목록은 {len(state['replacements'])}개예요.",
            {"kind": "remove_replacement", "label": f"교체 빼기 · {', '.join(slots)}", "undo": undo})


def _do_condition(conn, list_id, principal, draft, plan) -> tuple[str, dict | None]:
    patch = plan["patch"]
    old = {k: (draft.get("conditions") or {}).get(k) for k in patch}
    updated = qds.update_conditions(conn, list_id, principal, draft["version"], patch)
    pieces = []
    for key, value in patch.items():
        if key == "purpose":
            pieces.append(f"용도를 {_PURPOSE_LABEL.get(value, value)}(으)로")
        elif key == "resolution":
            pieces.append(f"해상도를 {_RESOLUTION_LABEL.get(value, value)}(으)로")
        elif key == "priority":
            pieces.append(f"우선순위를 {_PRIORITY_LABEL.get(value, value)}(으)로")
        elif key == "budget_max":
            pieces.append(f"총예산을 {_won(value)}으로" if value else "총예산을 비웠어요, ")
    stale = qds.analysis_stale(updated)
    tail = " 분석한 결과는 이전 조건 기준이에요. '다시 분석해줘'라고 하시면 새 조건으로 다시 볼게요." if stale else ""
    return (f"{' '.join(pieces).rstrip(', ')} 바꿨어요.{tail}",
            {"kind": "set_condition", "label": "조건 바꾸기", "undo": {"kind": "set_conditions", "values": old}})


def _do_reanalyze(conn, list_id, principal) -> tuple[str, dict | None]:
    result = qds.analyze_selected(conn, list_id, principal)
    summary = result["compat"]["summary"]
    view = result.get("price_view") or {}
    price = f" {view['label']} {_won(view['quote_total'] or view['line_total'])}." if view.get("mode") in ("line", "total_only") and (view.get("quote_total") or view.get("line_total")) else ""
    return (f"다시 분석했어요. 호환 통과 {summary.get('ok', 0)}개, 문제 {summary.get('fail', 0)}개, 확인 못 함 {summary.get('unknown', 0)}개예요.{price}",
            {"kind": "reanalyze", "label": "다시 분석", "undo": None})


def _do_fix(conn, list_id, principal, draft, plan) -> tuple[str, dict | None]:
    slot, text = plan["slot"], plan["text"]
    item = _item_for(draft, slot)
    if item is None:
        return f"견적에서 {slot} 항목을 찾지 못했어요.", None
    by_slot = load_pc_catalog(lambda _msg: None)
    reason = item.get("match_reason") or {}
    names = extract_targets(text, slot, by_slot.get(slot, []))
    if not names:                         # 이유 칩의 후보 번호("첫 번째")로 고르기
        index = next((i for i, w in enumerate(("첫", "두", "세")) if f"{w} 번째" in text or f"{w}번째" in text or f"{i + 1}번" in text), None)
        cands = reason.get("candidates") or []
        if index is not None and index < len(cands):
            names = [cands[index]["name"]]
    if len(names) != 1:
        return f"{slot}을(를) 어떤 제품으로 정할지 하나로 특정하지 못했어요. 제품 이름을 정확히 말해 주세요.", None
    old_name = item["normalized_name"]
    updated = qds.patch_items(conn, list_id, principal, draft["version"], [{"id": item["id"], "normalized_name": names[0]}], None)
    fixed = next(i for i in updated["items"] if i["id"] == item["id"])
    if fixed["match_status"] == "confirmed":
        sentence = f"{slot}을(를) {fixed['matched_name']}(으)로 확정했어요. 분석이 이미 끝났다면 '다시 분석해줘'로 반영할 수 있어요."
    else:
        sentence = f"{slot} 이름을 '{names[0]}'(으)로 고쳤지만 카탈로그 제품으로는 아직 확정하지 못했어요."
    return sentence, {"kind": "edit_item", "label": f"제품 확정 · {slot}", "undo": {"kind": "edit_item", "item_id": item["id"], "name": old_name}}


def _do_lookup(conn, list_id, principal, draft, plan) -> tuple[str, dict | None, dict]:
    """정보 찾기는 외부 검색(비용이 든다)이라 바로 실행하지 않고 먼저 묻는다 — 동의하면 다음 턴에 기존 검색 동의 흐름이 실행한다."""
    from src.agent.conditions_agent import SEARCH_PERMISSION_MARKER
    from src.services import live_spec_lookup

    item = _item_for(draft, plan["slot"])
    if item is None or item["match_status"] == "confirmed":
        return f"{plan['slot']}은(는) 이미 카탈로그 제품으로 확인돼서 따로 찾을 정보가 없어요.", None, {}
    if not live_spec_lookup.available():
        return "지금은 실시간 검색을 쓸 수 없어요.", None, {}
    reply = f"'{item['normalized_name']}' 정보를 찾으려면 외부 검색을 해야 하고 검색 비용이 들어요. {SEARCH_PERMISSION_MARKER}"
    return reply, None, {"pending_search": {"slot": plan["slot"], "product": item["normalized_name"]}}


def try_action(conn, list_id: UUID, principal: Principal, text: str) -> tuple[str, dict | None, dict] | None:
    """말이 동작 요청이면 실행하고 (답변 문장, action 메타, 메시지에 더 저장할 값)을 돌려준다. 동작이 아니면 None(읽기 답변으로)."""
    result = _try_action(conn, list_id, principal, text)
    if result is None:
        return None
    return result if len(result) == 3 else (*result, {})


def _try_action(conn, list_id: UUID, principal: Principal, text: str):
    try:
        draft = qds.get_draft(conn, list_id, principal)
    except NotFound:
        return None                       # 초안이 없는 예전 점검 세션 — 동작 없음
    try:
        review: dict | None = qds.quote_review_service.get_review(conn, list_id, principal)
    except NotFound:
        review = None                     # 아직 분석하지 않았다
    plan = parse(text, analyzed=review is not None, replaced=set((draft.get("replacements") or {})))
    if plan is None:
        return None
    kind = plan["kind"]
    needs_review = kind in ("add", "remove", "remove_all", "reanalyze")
    if needs_review and review is None and kind != "reanalyze":
        return "먼저 분석을 마친 뒤에 교체 목록을 바꿀 수 있어요.", None
    try:
        if kind == "add":
            return _do_add(conn, list_id, principal, draft, review, plan)
        if kind in ("remove", "remove_all"):
            return _do_remove(conn, list_id, principal, draft, plan)
        if kind == "condition":
            return _do_condition(conn, list_id, principal, draft, plan)
        if kind == "reanalyze":
            return _do_reanalyze(conn, list_id, principal)
        if kind == "fix":
            return _do_fix(conn, list_id, principal, draft, plan)
        if kind == "lookup":
            return _do_lookup(conn, list_id, principal, draft, plan)
    except TruefitError as exc:
        log.info("chat action %s refused: %s", kind, exc)
        return f"요청을 처리하지 못했어요. {exc.message}", None
    return None
