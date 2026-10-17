"""주변기기 채팅 한 턴 서비스 — 문장 해석 + 이번에 새로 반영한 것 + 반영하지 못한 말 설명 + 질문 답변을 한 번에 낸다
(QA PQA-012·013·014, docs/local/주변기기_추천_QA_기획.md 2.3절).

화면은 이 응답의 `turn.reply` 를 채팅에 그대로 보여 준다. 답장 문장을 화면이 조건 목록으로 다시 만들지 않는다
(이어 말하기로 쌓인 조건을 "반영했어요"라고 되풀이하던 PQA-013 이 거기서 생겼다).

DB 연결은 **추천 결과가 있어야 답할 수 있는 질문**(고른 이유·비교·스펙·사용기·PC 호환)일 때만 연다 — 언어 모델을 부르는
동안 연결을 잡고 있지 않는다. 추천은 같은 입력이면 같은 결과를 내므로(저장 없는 순수 계산) 화면에 보이는 결과와 같은 결과로 답한다.
"""
from __future__ import annotations

from typing import Any, Callable, ContextManager

from src.engine import peripheral_chat, peripheral_commands, peripheral_intent
from src.engine.peripheral_chat import needs_result
from src.engine.peripheral_commands import Command
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_rules import chat_config, interpretation_settings, kind_def, load_peripheral_rules
from src.schemas import PeripheralsRecommendIn
from src.services import peripheral_interpret_service, peripherals_service


def _recommend_body(interp: Interpretation, pc_list_id: str | None) -> PeripheralsRecommendIn:
    """해석(합쳐진 조건)을 추천 요청으로. 화면이 해석 결과를 추천 요청으로 옮기는 것과 같다."""
    return PeripheralsRecommendIn(
        kinds=interp.kinds, budget_max=interp.budget_total, pc_list_id=pc_list_id,
        purposes=interp.purposes, situations=interp.situations, stated=interp.stated, kind_budget=interp.budget,
        kind_budget_min=interp.budget_min,
        brand_like=interp.brand_like, brand_avoid=interp.brand_avoid, exclude=interp.exclude, emphasis=interp.emphasis,
        hand_size=interp.hand_size,
    )


def _question_answer(
    question: Question, interp: Interpretation, pc_list_id: str | None, pc_context: dict | None,
    open_conn: Callable[[], ContextManager], rules: dict,
) -> dict[str, Any]:
    if not needs_result(question):
        return peripheral_chat.static_answer(question, interp.kinds, rules)
    answers = chat_config(rules)["answers"]
    if not interp.kinds:       # 어떤 기기의 결과인지 알 수 없다
        return {"type": question.type, "topic": question.topic, "text": answers["no_kind"], "kinds": [],
                "chips": peripheral_chat.kind_condition_chips(rules)}
    with open_conn() as conn:
        payload, result = peripherals_service.recommend_detailed(conn, _recommend_body(interp, pc_list_id), pc_context)
    return peripheral_chat.result_answer(question, result, payload, interp.kinds, pc_context, rules)


def turn(
    text: str, previous: dict[str, Any] | None, kinds: list[str] | None, *,
    pc_list_id: str | None, pc_context: dict | None, open_conn: Callable[[], ContextManager],
) -> dict[str, Any]:
    """한 문장을 한 턴으로 처리해 해석(`PeripheralInterpretOut` 모양)과 `turn` 블록을 함께 낸다.

    turn.new_conditions — 이번 문장에서 **새로** 반영한 것(이전 해석에 없던 것)
    turn.not_reflected  — 반영하지 못한 말과 이유(아직 고를 수 없는 말·모델이 목록에서 못 고른 말)
    turn.notes          — 어떻게 읽었는지, 함께 고를 수 없어 정리한 조건
    turn.answer         — 질문이면 그 답({type, topic, text, kinds, chips}), 아니면 None
    turn.reply          — 위를 순서대로 이은 채팅 답장 한 덩어리
    """
    rules = load_peripheral_rules()
    sentence = text[: interpretation_settings(rules)["max_chars"]]
    base = peripheral_intent.sanitize(previous, rules) if previous else None
    context = peripheral_intent.kinds_all_order([*(base.kinds if base else []), *(kinds or [])])
    command = peripheral_commands.detect(sentence, context, rules)
    if command is not None:
        current = (base or Interpretation()).model_copy(update={"kinds": context})
        return _command_turn(command, sentence, current, len(text) > len(sentence),
                             pc_list_id=pc_list_id, pc_context=pc_context, open_conn=open_conn, rules=rules)

    out = peripheral_interpret_service.interpret(text, previous, kinds)
    state = out.pop("turn_state")
    merged: Interpretation = out["interpretation"]
    new: Interpretation = state["new"]
    before: Interpretation | None = state["previous"]
    sentence: str = state["sentence"]

    new_items = peripheral_chat.new_conditions(before, merged, rules)
    reading = peripheral_chat.reading_notes(sentence, new, rules)
    reading += peripheral_chat.pc_purpose_notes((pc_context or {}).get("purpose"), before, merged, rules)
    previous_resolved = peripheral_intent.resolve(before, rules) if before is not None else None
    conflicts = peripheral_chat.conflict_notes(out["resolved"], previous_resolved)
    not_reflected = [n["text"] for n in peripheral_chat.unsupported_notes(sentence, rules)]
    not_reflected += peripheral_chat.unrecognized_notes(new.unrecognized)

    answer = None
    if merged.question is not None:
        answer = _question_answer(merged.question, merged, pc_list_id, pc_context, open_conn, rules)
    example = chat_config(rules)["examples"].get(merged.kinds[0]) if merged.kinds else None
    reply = peripheral_chat.compose_reply(new_items, reading, conflicts, answer, not_reflected, example=example)

    out["turn"] = {
        "new_conditions": new_items,
        "not_reflected": not_reflected,
        "notes": [*reading, *conflicts],
        "answer": answer,
        "command": None,
        "removed_conditions": [],
        "reset": False,
        "reply": reply,
        "chips": (answer or {}).get("chips") or peripheral_chat.chips(False, rules),
        "result_chips": peripheral_chat.chips(True, rules),
    }
    return out


# ── 결과 화면 명령(peripheral_commands) ─────────────────────────────────────────
def _won(value: int) -> str:
    return f"{value:,}원"


def _picks(interp: Interpretation, pc_list_id: str | None, pc_context: dict | None, open_conn) -> dict[str, Any]:
    """해석으로 추천을 계산해 종류 → 1위 후보. 화면이 같은 해석으로 받는 결과와 같다(저장 없는 순수 계산)."""
    if not interp.kinds:
        return {}
    with open_conn() as conn:
        _payload, result = peripherals_service.recommend_detailed(conn, _recommend_body(interp, pc_list_id), pc_context)
    return {p.kind: p.candidate for p in (result.picks if result is not None else [])}


def _apply_per_kind(
    command: Command, current: Interpretation, picks: dict[str, Any], rules: dict,
) -> tuple[Interpretation, list[str]]:
    """swap·cheaper·relative_budget 을 품목마다 해석에 반영한다. (새 해석, 반영하지 못한 품목의 이유 문장)."""
    interp, problems = current, []
    for kind in command.kinds:
        label = kind_def(kind, rules)["label"]
        pick = picks.get(kind)
        if command.type == "swap":
            if pick is None:
                problems.append(f"지금 {label} 추천 결과가 없어 바꿀 제품이 없어요.")
                continue
            exclude = {**interp.exclude, kind: [*interp.exclude.get(kind, []), pick.name]}
            interp = interp.model_copy(update={"exclude": exclude})
            continue
        base = interp.budget.get(kind) if command.type == "relative_budget" else None
        if base is None:
            if pick is None:
                problems.append(f"지금 {label} 추천 결과가 없어 기준 금액을 알 수 없어요. 예산을 금액으로 말씀해 주세요.")
                continue
            base = pick.price
        target = base + command.delta if command.type == "relative_budget" else (pick.price - 1) // 1000 * 1000
        if target <= 0:
            problems.append(f"{label} 예산을 {_won(base)}보다 그만큼 낮출 수 없어요.")
            continue
        update = {"budget": {**interp.budget, kind: target}, "budget_total": None if len(interp.kinds) == 1 else interp.budget_total}
        if command.delta > 0 and pick is not None:
            # "5만원 올려줘"는 더 쓰겠다는 말이다 — 상한만 올리면 예산이 생긴 가격 축이 오히려 싼 제품을 1위로 올린다(실측: 125,000원
            # → 38,480원). 지금 1위보다 비싼 쪽(다음 천 원 단위부터)에서 고른다.
            update["budget_min"] = {**interp.budget_min, kind: (pick.price // 1000 + 1) * 1000}
        interp = interp.model_copy(update=update)
    return interp, problems


def _command_turn(
    command: Command, sentence: str, current: Interpretation, truncated: bool, *,
    pc_list_id: str | None, pc_context: dict | None, open_conn, rules: dict,
) -> dict[str, Any]:
    labels = {k: kind_def(k, rules)["label"] for k in current.kinds}
    after, lines, problems, ask_kind = current, [], [], False
    if command.type == "reset":
        after = peripheral_commands.reset(current)
        kept = "·".join(labels.values())
        lines.append("조건을 모두 지웠어요." + (f" 고른 품목({kept})은 그대로예요." if kept else "") + " 원하는 조건을 다시 말씀해 주세요.")
    elif command.type == "remove":
        removed = peripheral_commands.remove(current, sentence, command.kinds, rules)
        if removed is None:
            problems.append("뺄 조건을 찾지 못했어요. '이해한 내용'에서 지울 조건을 누르시거나 \"무선 조건 빼줘\"처럼 말씀해 주세요.")
        else:
            after = removed
    elif not command.kinds and command.type == "relative_budget" and len(current.kinds) > 1:
        picks = _picks(current, pc_list_id, pc_context, open_conn)
        base = current.budget_total or sum(c.price for c in picks.values())
        if not picks and not current.budget_total:
            problems.append("지금 추천 결과가 없어 기준 금액을 알 수 없어요. 예산을 금액으로 말씀해 주세요.")
        elif base + command.delta <= 0:
            problems.append(f"예산 합계를 {_won(base)}보다 그만큼 낮출 수 없어요.")
        else:
            after = current.model_copy(update={"budget_total": base + command.delta})
    elif not command.kinds:
        ask_kind = True
        problems.append("어느 품목을 " + ("바꿀까요?" if command.type == "swap" else "더 싸게 볼까요?") if current.kinds
                        else "먼저 추천받을 품목을 골라 주세요.")
    else:
        picks = _picks(current, pc_list_id, pc_context, open_conn)
        after, problems = _apply_per_kind(command, current, picks, rules)
        new_picks = _picks(after, pc_list_id, pc_context, open_conn) if after != current else {}
        lost = [k for k in command.kinds if k in picks and k not in new_picks]
        if after != current and lost:      # 바꾼 조건으로는 그 품목 후보가 하나도 없다 — 결과가 비지 않게 반영하지 않는다
            problems += [f"지금 {labels[k]} 1위 {picks[k].name}({_won(picks[k].price)})보다 싼 후보는 조건에 맞는 게 없어요." if command.type == "cheaper"
                         else (f"{labels[k]} {_won(after.budget_min[k])}~{_won(after.budget[k])}" if after.budget_min.get(k) != current.budget_min.get(k)
                          else f"{labels[k]} 예산 {_won(after.budget[k])}") + "에는 조건에 맞는 후보가 없어 바꾸지 않았어요."
                         if command.type != "swap" and k in after.budget else f"조건에 맞는 다른 {labels[k]} 후보가 없어 바꾸지 않았어요."
                         for k in lost]
            after = current
        elif after != current:
            for kind in command.kinds:
                old, new = picks.get(kind), new_picks.get(kind)
                if old is None or new is None:
                    continue
                if command.type == "swap":
                    lines.append(f"{labels[kind]}를 바꿨어요: {old.name}({_won(old.price)}) → {new.name}({_won(new.price)}). "
                                 "되돌리려면 '이해한 내용'에서 뺀 제품을 지워 주세요.")
                else:
                    low = after.budget_min.get(kind)
                    lines.append(f"{labels[kind]}를 {_won(low)}~{_won(after.budget[kind])}에서 다시 골랐어요: {new.name}({_won(new.price)})"
                                 if low and low != current.budget_min.get(kind) else
                                 f"{labels[kind]} 예산을 {_won(after.budget[kind])}으로 바꿔 다시 골랐어요: {new.name}({_won(new.price)})")

    added = peripheral_chat.new_conditions(current, after, rules)
    removed_items = peripheral_chat.new_conditions(after, current, rules)
    dropped = [k for k in current.kinds if k not in after.kinds]
    if command.type == "remove" and dropped:
        lines.append(f"{'·'.join(labels[k] for k in dropped)}를 품목에서 뺐어요.")
    elif command.type == "remove" and removed_items:
        lines.append("뺐어요: " + " · ".join(i["label"] for i in removed_items))
    elif command.type == "relative_budget" and not command.kinds and added:
        lines.append(f"예산 합계를 {_won(after.budget_total)}으로 바꿨어요.")
    reply = "\n".join([*lines, *problems]) or "이번 문장에서는 바꾼 것이 없어요."
    chips = ([f"{labels[k]} 다른 걸로" if command.type == "swap" else f"{labels[k]} 더 싼 걸로" for k in current.kinds]
             if ask_kind else peripheral_chat.chips(True, rules))
    return {
        "interpretation": after,
        "resolved": peripheral_intent.resolve(after, rules),
        "needs_kind": False,
        "source": "rules",
        "truncated": truncated,
        "turn": {
            "new_conditions": [] if command.type == "remove" else added,
            "not_reflected": problems,
            "notes": [],
            "answer": None,
            "command": command.type,
            "removed_conditions": removed_items,
            "reset": command.type == "reset",
            "reply": reply,
            "chips": chips,
            "result_chips": peripheral_chat.chips(True, rules),
        },
    }
