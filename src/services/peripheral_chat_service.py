"""주변기기 채팅 한 턴 서비스 — 문장 해석 + 이번에 새로 반영한 것 + 반영하지 못한 말 설명 + 질문 답변을 한 번에 낸다
(QA PQA-012·013·014, docs/local/주변기기_추천_QA_기획.md 2.3절).

화면은 이 응답의 `turn.reply` 를 채팅에 그대로 보여 준다. 답장 문장을 화면이 조건 목록으로 다시 만들지 않는다
(이어 말하기로 쌓인 조건을 "반영했어요"라고 되풀이하던 PQA-013 이 거기서 생겼다).

DB 연결은 **추천 결과가 있어야 답할 수 있는 질문**(고른 이유·비교·스펙·사용기·PC 호환)일 때만 연다 — 언어 모델을 부르는
동안 연결을 잡고 있지 않는다. 추천은 같은 입력이면 같은 결과를 내므로(저장 없는 순수 계산) 화면에 보이는 결과와 같은 결과로 답한다.
"""
from __future__ import annotations

from typing import Any, Callable, ContextManager

from src.engine import peripheral_chat, peripheral_intent
from src.engine.peripheral_chat import needs_result
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_rules import chat_config, load_peripheral_rules
from src.schemas import PeripheralsRecommendIn
from src.services import peripheral_interpret_service, peripherals_service


def _recommend_body(interp: Interpretation, pc_list_id: str | None) -> PeripheralsRecommendIn:
    """해석(합쳐진 조건)을 추천 요청으로. 화면이 해석 결과를 추천 요청으로 옮기는 것과 같다."""
    return PeripheralsRecommendIn(
        kinds=interp.kinds, budget_max=interp.budget_total, pc_list_id=pc_list_id,
        purposes=interp.purposes, situations=interp.situations, stated=interp.stated, kind_budget=interp.budget,
        kind_budget_min=interp.budget_min,
        brand_like=interp.brand_like, brand_avoid=interp.brand_avoid, emphasis=interp.emphasis, hand_size=interp.hand_size,
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
    out = peripheral_interpret_service.interpret(text, previous, kinds)
    state = out.pop("turn_state")
    merged: Interpretation = out["interpretation"]
    new: Interpretation = state["new"]
    before: Interpretation | None = state["previous"]
    sentence: str = state["sentence"]

    new_items = peripheral_chat.new_conditions(before, merged, rules)
    reading = peripheral_chat.reading_notes(sentence, new, rules)
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
        "reply": reply,
        "chips": (answer or {}).get("chips") or peripheral_chat.chips(False, rules),
        "result_chips": peripheral_chat.chips(True, rules),
    }
    return out
