"""견적 리스트 히스토리 (C1: docs/개발요청_백엔드_및_타팀.md 2번).

확정된 목록 하나가 만들어지기까지의 여정 — 조건 대화에서 한 말, 추천을 받은 것, 결과 화면에서 물은 것,
부품 교체·제외, 확정 — 을 사건 목록(events)과 요약 문장(summary)으로 돌려준다.

- **사건과 숫자는 코드가** DB에서 뽑는다: `identity.message`(사용자 말), `engine.recommendation_run`(추천),
  `engine.feedback_event`(교체·제외), `planning.plan_revision`(확정 시각·총액).
- **문장은 LLM이** 사건 목록만 보고 쓴다. LLM을 못 쓰거나(MOCK_MODE·키 없음), 실패하거나, 사건 목록에 없는
  숫자를 쓰면 규칙 문장으로 대신한다 — 기록에 없는 것은 쓰지 않는다.
- 확정된 목록은 스냅샷이라(이후 교체·대화가 붙지 않는다) 한 번 만든 요약을 프로세스 메모리에 둔다.

수량·구매 시점 변경은 어디에도 기록되지 않아 사건에 없다. favorite(찜)도 아직 서버 개념이 없다.
"""
from __future__ import annotations

import re
from uuid import UUID

from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.engine.lang import fmt_money
from src.repo.user_repo import ConversationRepo

_TEXT_LIMIT = 120          # 사건 한 줄에 옮기는 사용자 말 길이
_PROMPT_EVENT_LIMIT = 40   # LLM에 넣는 사건 수(앞뒤를 남기고 가운데를 줄인다)
_summary_cache: dict[tuple[str, str], str] = {}

_SYSTEM = (
    "당신은 PC 견적 서비스 TrueFit에서, 사용자가 확정한 견적이 만들어진 과정을 요약합니다.\n"
    "- 주어진 사건 목록만 근거로 2~3문장의 한국어 존댓말 요약을 씁니다.\n"
    "- 사건 목록에 없는 제품명·금액·숫자·이유를 만들지 않습니다. 왜 바꿨는지 기록에 없으면 짐작하지 않습니다.\n"
    "- 사용자가 무엇을 찾기 시작했고, 무엇을 묻고 바꿨으며, 어떻게 확정했는지 순서대로 씁니다.\n"
    "- 화면에서 본인에게 보여 주는 글입니다. '사용자는' 같은 3인칭 주어 없이 씁니다(예: '게임용 PC를 찾으셨고…').\n"
    "- 목록·머리표·따옴표 없이 문장만 씁니다."
)


def llm_available() -> bool:
    return not MOCK_MODE and LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY) and bool(LLM_MODEL)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_LIMIT else text[: _TEXT_LIMIT - 1] + "…"


# 한글이 아닌 끝 글자를 읽을 때 받침이 있는지(영=0·일·삼·육·칠·팔 / 엘·엠·엔·알). ㄹ 받침은 "으로" 대신 "로".
_LATIN_DIGIT_BATCHIM = {c: True for c in "013678lmnrLMNR"}
_LATIN_DIGIT_RIEUL = set("178lrLR")


def _batchim(word: str) -> tuple[bool, bool]:
    """(받침 있음, 그 받침이 ㄹ). 괄호·공백 같은 끝 기호는 건너뛴다."""
    for ch in reversed(word.strip()):
        if "가" <= ch <= "힣":
            final = (ord(ch) - 0xAC00) % 28
            return final != 0, final == 8
        if ch.isalnum():
            return _LATIN_DIGIT_BATCHIM.get(ch, False), ch in _LATIN_DIGIT_RIEUL
    return False, False


def _eul(word: str) -> str:
    return word + ("을" if _batchim(word)[0] else "를")


def _euro(word: str) -> str:
    has, rieul = _batchim(word)
    return word + ("으로" if has and not rieul else "로")


def _user_text(text: str) -> str:
    """칩으로 고른 금액은 숫자만 남는다("5000000") — 화면과 같게 원화로 적는다."""
    text = " ".join(text.split())
    return fmt_money(int(text)) if text.isdigit() and len(text) >= 4 else text


def _variant_names(conn, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT v.id::text AS id, p.name FROM catalog.product_variant v JOIN catalog.product p ON p.id=v.product_id "
        "WHERE v.id = ANY(%s::uuid[])", (list(ids),),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _item_slots(conn, revision_id: UUID) -> dict[str, dict]:
    """이 revision 의 모든 run 에 있던 품목 → 슬롯 이름·지금 제품명·교체 사유 문장."""
    rows = conn.execute(
        """SELECT c.id::text, n.name, p.name, c.reason
           FROM engine.recommendation_candidate c
           JOIN engine.recommendation_run r ON r.id=c.run_id
           JOIN catalog.product_variant v ON v.id=c.variant_id
           JOIN catalog.product p ON p.id=v.product_id
           JOIN planning.requirement q ON q.id=c.requirement_id
           JOIN planning.plan_node n ON n.id=q.node_id
           WHERE r.revision_id=%s""", (revision_id,),
    ).fetchall()
    return {r[0]: {"slot": r[1], "product": r[2], "reason": r[3] or ""} for r in rows}


def _key_item(event_key: str) -> str | None:
    """`run:item[#n]:version:action` → item. 예전 교체 이벤트는 payload 가 비어 있어 키에서 읽는다."""
    parts = event_key.split(":")
    if len(parts) != 4 or parts[1] == "noitem":
        return None
    return parts[1].split("#", 1)[0]


def build_events(conn, revision: dict) -> list[dict]:
    """시간순 사건 목록. 각 사건은 {at, kind, text} — kind: condition|recommend|question|swap|remove|confirm."""
    from src.services.recommendation_service import _SWAP_RE

    revision_id = revision["id"]
    runs = conn.execute(
        "SELECT id, completed_at FROM engine.recommendation_run "
        "WHERE revision_id=%s AND status IN ('completed','stale') AND completed_at IS NOT NULL ORDER BY completed_at",
        (revision_id,),
    ).fetchall()
    first_result_at = runs[0][1] if runs else None

    events: list[dict] = []
    for m in ConversationRepo(conn).messages(revision["conversation_id"]):
        if m["role"] != "user" or not m["content"].strip():
            continue
        # 첫 추천이 나오기 전의 말은 조건 대화, 뒤의 말은 결과 화면에서 물은 것이다.
        after = first_result_at is not None and m["created_at"] > first_result_at
        events.append({"at": m["created_at"], "kind": "question" if after else "condition", "text": _clip(_user_text(m["content"]))})

    for index, (_run_id, completed_at) in enumerate(runs):
        events.append({"at": completed_at, "kind": "recommend",
                       "text": "추천 구성을 받았어요." if index == 0 else "조건을 바꿔 추천을 다시 받았어요."})

    feedback = conn.execute(
        "SELECT event_type, event_key, payload, occurred_at FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type IN ('item_replaced','item_removed') ORDER BY occurred_at",
        (revision_id,),
    ).fetchall()
    items = _item_slots(conn, revision_id)
    variant_ids = {v for _t, _k, p, _a in feedback for key in ("from_variant_id", "to_variant_id") if (v := (p or {}).get(key))}
    names = _variant_names(conn, variant_ids)
    swaps_per_item: dict[str, int] = {}
    for event_type, event_key, payload, _at in feedback:
        if event_type == "item_replaced":
            item = (payload or {}).get("item_id") or _key_item(event_key)
            swaps_per_item[item] = swaps_per_item.get(item, 0) + 1

    for event_type, event_key, payload, occurred_at in feedback:
        payload = payload or {}
        item_id = payload.get("item_id") or _key_item(event_key)
        item = items.get(item_id or "", {})
        slot = item.get("slot") or "부품"
        if event_type == "item_removed":
            events.append({"at": occurred_at, "kind": "remove", "text": f"{_eul(slot)} 구성에서 뺐어요."})
            continue
        before, after = names.get(payload.get("from_variant_id", "")), names.get(payload.get("to_variant_id", ""))
        if not (before and after) and swaps_per_item.get(item_id) == 1:
            # 예전 기록(무엇→무엇이 없음): 한 번만 바꾼 품목이면 교체 사유 문장과 지금 제품이 그 교체다.
            found = _SWAP_RE.search(item.get("reason", ""))
            if found:
                before, after = found.group(1), item.get("product")
        text = (f"{_eul(slot)} {before}에서 {_euro(after)} 바꿨어요." if before and after
                else f"{_eul(slot)} 다른 제품으로 바꿨어요.")
        events.append({"at": occurred_at, "kind": "swap", "text": text})

    if revision.get("confirmed_at") is not None:
        events.append({"at": revision["confirmed_at"], "kind": "confirm",
                       "text": f"{fmt_money(revision['confirmed_total'])}으로 확정했어요."})
    events.sort(key=lambda e: e["at"])
    return events


def rule_summary(events: list[dict]) -> str:
    """LLM 없이 쓰는 요약 — 사건 수와 교체·확정 문장을 그대로 잇는다."""
    count = {kind: sum(1 for e in events if e["kind"] == kind) for kind in
             ("condition", "recommend", "question", "swap", "remove")}
    parts: list[str] = []
    first = next((e["text"] for e in events if e["kind"] == "condition"), None)
    if first:
        parts.append(f"{_euro(chr(34) + first + chr(34))} 시작해 조건 대화에서 {count['condition']}번 말씀하셨어요.")
    if count["recommend"]:
        parts.append(f"추천을 {count['recommend']}번 받았고" + (f" 결과 화면에서 {count['question']}번 질문하셨어요."
                                                           if count["question"] else " 추가 질문 없이 결과를 보셨어요."))
    changes = [e["text"] for e in events if e["kind"] in ("swap", "remove")]
    if changes:
        parts.append(" ".join(changes))
    confirm = next((e["text"] for e in events if e["kind"] == "confirm"), None)
    if confirm:
        parts.append("최종적으로 " + confirm)
    return " ".join(parts)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def llm_summary(events: list[dict]) -> str | None:
    """사건 목록만 넣어 LLM 요약을 받는다. 실패하거나 목록에 없는 숫자가 나오면 None."""
    from src.clients.llm_client import call_llm

    picked = events if len(events) <= _PROMPT_EVENT_LIMIT else (
        events[: _PROMPT_EVENT_LIMIT // 2] + events[-_PROMPT_EVENT_LIMIT // 2:])
    lines = [f"{i}. [{e['kind']}] {e['text']}" for i, e in enumerate(picked, start=1)]
    prompt = ("사건 목록(kind: condition=조건 대화에서 한 말, recommend=추천을 받음, question=결과 화면 질문, "
              "swap=부품 교체, remove=부품 제외, confirm=확정)\n" + "\n".join(lines))
    try:
        text = (call_llm(prompt, system=_SYSTEM).get("text") or "").strip()
    except Exception:
        return None
    if not text:
        return None
    allowed = _numbers(prompt)
    if not _numbers(text) <= allowed:
        return None
    return text


def summarize(list_id: UUID, revision: dict, events: list[dict]) -> str:
    key = (str(list_id), revision["confirmed_at"].isoformat() if revision.get("confirmed_at") else "")
    if key in _summary_cache:
        return _summary_cache[key]
    text = llm_summary(events) if llm_available() else None
    if text is None:
        return rule_summary(events)        # 규칙 문장은 캐시하지 않는다 — 다음 요청에서 LLM을 다시 시도한다
    _summary_cache[key] = text
    return text


def render(list_id: UUID, revision: dict, events: list[dict]) -> dict:
    """응답 모양. DB 를 쓰지 않는다 — 라우터가 트랜잭션을 닫은 뒤 부른다(LLM 대기 동안 연결을 잡지 않는다)."""
    return {
        "summary": {"status": "ready", "text": summarize(list_id, revision, events)},
        "events": [{"at": e["at"].isoformat(), "kind": e["kind"], "text": e["text"]} for e in events],
    }
