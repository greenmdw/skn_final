"""주변기기 채팅 기록 — 한 턴(사용자 말·답)과 추천을 받은 때의 조건을 그 목록(세션)의 대화에 남기고, 돌아왔을 때 되살린다.

10/16 까지 주변기기 대화는 어디에도 저장되지 않았다(화면 메모리뿐). 다른 화면에 갔다 오면 채팅·추천이 사라지고(QA 10/15 #19·#30),
대화 내역에서 주변기기 대화를 열 수 없고(#47), 리포트에서도 볼 수 없었다(10/16 #17).

저장 위치: 주변기기 화면은 PC 견적과 **다른** 목록(세션)을 만들어 쓴다(`POST /session`). 그 목록의 대화(identity.message)에
본체 대화와 같은 방식으로 쌓는다 — 받은 견적 점검 채팅이 자기 목록을 쓰는 것과 같다. 메시지 metadata 의 `channel` 이
"peripheral" 이면 주변기기 채팅이다.

- 사용자 말: role=user, content=문장
- 답: role=assistant, content=답장 문장, metadata={channel, event:"turn", interpretation, kinds, needs_kind,
  peripheral_turn(답장 문장을 뺀 나머지)} — 키를 `turn` 으로 두지 않는다: 결과 채팅 답의 표시라 턴 점검 배치가 결과 채팅으로 센다
- 추천: role=system, content="", metadata={channel, event:"recommend", body(추천 입력), notices} — 칩 삭제·"더 맞추기"처럼
  채팅 없이 조건을 바꾼 것도 추천 입력에 남아, 돌아왔을 때 마지막 추천과 같은 조건으로 다시 받는다.

본체 대화를 읽는 곳(히스토리·턴 점검)은 이 채널을 뺀다 — 주변기기 목록은 본체 대화가 아니다.
DB 연결은 호출부가 준다. 언어 모델 호출 없음.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.engine import peripheral_intent
from src.engine.peripheral_intent import Interpretation
from src.repo.user_repo import ConversationRepo

CHANNEL = "peripheral"


def _turn_meta(out: dict[str, Any], kinds: list[str] | None) -> dict[str, Any]:
    turn = {k: v for k, v in out["turn"].items() if k != "reply"}
    return {"channel": CHANNEL, "event": "turn", "interpretation": out["interpretation"],
            "kinds": list(kinds or []), "needs_kind": bool(out["needs_kind"]), "source": out["source"], "peripheral_turn": turn}


def record_turn(conn, conversation_id: UUID, text: str, kinds: list[str] | None, out: dict[str, Any]) -> None:
    """채팅 한 턴을 남긴다. `out` 은 응답(`PeripheralChatOut`)을 JSON 모양으로 바꾼 dict 다."""
    repo = ConversationRepo(conn)
    repo.add_message(conversation_id, "user", text, metadata={"channel": CHANNEL})
    repo.add_message(conversation_id, "assistant", out["turn"]["reply"], metadata=_turn_meta(out, kinds))


def record_recommend(conn, conversation_id: UUID, body, payload: dict[str, Any]) -> None:
    """추천을 받은 때의 입력과 채팅에 말한 유의사항을 남긴다(화면에 보이는 말은 아니다 — role=system)."""
    notices = [n["text"] for n in payload.get("notices") or [] if n.get("text")]
    stored = body.model_dump(mode="json", exclude={"pc_list_id", "resolution"})
    ConversationRepo(conn).add_message(conversation_id, "system", "", metadata={
        "channel": CHANNEL, "event": "recommend", "body": stored, "notices": notices})


def _from_body(body: dict[str, Any], unrecognized: list[str]) -> Interpretation:
    interp = peripheral_intent.sanitize({
        "kinds": body.get("kinds") or [], "purposes": body.get("purposes") or [],
        "purpose_kinds": body.get("purpose_kinds") or {}, "situations": body.get("situations") or [],
        "stated": body.get("stated") or {}, "budget": body.get("kind_budget") or {}, "budget_min": body.get("kind_budget_min") or {},
        "budget_total": body.get("budget_max"), "emphasis": body.get("emphasis") or {}, "brand_like": body.get("brand_like") or {},
        "brand_avoid": body.get("brand_avoid") or {}, "exclude": body.get("exclude") or {}, "hand_size": body.get("hand_size"),
    })
    return interp.model_copy(update={"unrecognized": list(unrecognized)})


def _question_only(meta: dict[str, Any]) -> bool:
    """화면과 같은 규칙: 질문의 답이 있고 조건이 바뀌지 않았으면 해석을 받아들이지 않는다(PeripheralsPage.sendTurn)."""
    turn = meta.get("peripheral_turn") or {}
    return turn.get("answer") is not None and not turn.get("new_conditions") and not turn.get("removed_conditions")


def history(conn, conversation_id: UUID) -> dict[str, Any]:
    """대화를 화면 순서대로, 그리고 마지막 상태(해석·추천을 받았는지·마지막 유의사항)를 낸다.

    상태는 화면이 하던 일을 기록 순서대로 되풀이해 얻는다: 종류를 못 알아들은 턴과 질문만 한 턴은 해석을 바꾸지 않고,
    "처음부터 다시"는 결과를 지우고, 추천은 그 입력이 곧 조건이다. 주변기기 기록이 하나도 없으면 messages 가 비어 있다."""
    messages: list[dict[str, Any]] = []
    state: Interpretation | None = None
    showing = False
    spoken: list[str] = []
    for row in ConversationRepo(conn).messages(conversation_id):
        meta = row.get("metadata") or {}
        if meta.get("channel") != CHANNEL:
            continue
        event = meta.get("event")
        if row["role"] == "user":
            messages.append({"role": "user", "text": row["content"], "at": row["created_at"].isoformat()})
            continue
        if event == "recommend":
            body = meta.get("body") or {}
            state = _from_body(body, state.unrecognized if state else [])
            showing = True
            notices = list(meta.get("notices") or [])
            if notices and notices != spoken:       # 화면도 같은 유의사항은 되풀이해 말하지 않는다
                messages.extend({"role": "assistant", "text": text, "at": row["created_at"].isoformat()} for text in notices)
            spoken = notices
            continue
        if row["role"] != "assistant":
            continue
        messages.append({"role": "assistant", "text": row["content"], "at": row["created_at"].isoformat()})
        if event != "turn" or meta.get("needs_kind") or _question_only(meta):
            continue
        state = peripheral_intent.sanitize(meta.get("interpretation") or {})
        if (meta.get("peripheral_turn") or {}).get("reset"):
            showing = False
    interp = state or Interpretation()
    return {
        "messages": messages,
        "interpretation": interp,
        "resolved": peripheral_intent.resolve(interp),
        "showing_results": showing and bool(interp.kinds),
        "notices": spoken,
    }
