"""견적 리스트 히스토리 (C1: docs/개발요청_백엔드_및_타팀.md 2번).

확정된 목록 하나가 만들어지기까지의 여정을 세 층으로 돌려준다.

- **요약(summary)**: 2~3문장. LLM이 아래 단계만 보고 쓴다. LLM을 못 쓰거나(MOCK_MODE·키 없음), 실패하거나,
  단계에 없는 숫자를 쓰거나, 한글·영문 밖의 글자(키릴 문자 등)를 섞으면 규칙 문장으로 대신한다.
- **이렇게 정해졌어요(steps)**: 결과를 바꾼 것만 몇 단계로 — `history_journey` 가 기록에서 코드로 만든다.
- **자세히(events)**: 대화 순서 그대로의 사건 목록 — `identity.message`(사용자 말), `engine.recommendation_run`
  (추천), `engine.feedback_event`(교체·제외), `planning.plan_revision`(확정 시각·총액). 사용자 말은 결과에 영향을
  준 것만(조건을 정했거나 그 뒤 부품이 바뀐 말) — 나머지는 대화 내역에서 본다.
- 확정된 목록은 스냅샷이라(이후 교체·대화가 붙지 않는다) 한 번 만든 요약을 프로세스 메모리에 둔다.

수량·구매 시점 변경은 어디에도 기록되지 않아 사건에 없다. favorite(찜)도 아직 서버 개념이 없다.
"""
from __future__ import annotations

import re
from uuid import UUID

from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.engine.lang import fmt_money, josa
from src.repo.user_repo import ConversationRepo

_TEXT_LIMIT = 120          # 사건 한 줄에 옮기는 사용자 말 길이
_summary_cache: dict[tuple[str, str, int], str] = {}

_SYSTEM = (
    "당신은 PC 견적 서비스 TrueFit에서, 사용자가 확정한 견적이 어떻게 이 구성이 됐는지 요약합니다.\n"
    "- 주어진 단계 목록만 근거로 2~3문장의 한국어 존댓말 요약을 씁니다.\n"
    "- 무엇을 원하셨고, 무엇이 결과를 바꿨고(조건 변화·직접 바꾼 부품), 얼마에 확정했는지를 씁니다.\n"

    "- 단계 목록에 없는 제품명·금액·숫자·이유를 만들지 않습니다. 원인은 단계에 적힌 것만 씁니다.\n"
    "- 제품명·브랜드는 단계에 적힌 표기 그대로 씁니다. 한글로 옮기거나 줄이지 않습니다.\n"
    "- 화면에서 본인에게 보여 주는 글입니다. '사용자는'·'사용자께서' 같은 3인칭 없이 해요체로 씁니다"
    "(예: '게임용 PC를 찾으셨고 … 확정하셨어요').\n"
    "- 목록·머리표 없이 한국어 문장만 씁니다. 제품명·브랜드 외에 다른 언어를 섞지 않습니다."
)
# 단계에 '반영 못 함'이 있을 때만 붙인다 — 늘 붙였더니 없을 때 "반영하지 못한 것은 없습니다"를 덧붙이고, 기본값
# 안내("해상도는 말씀 안 하셔서 …")를 "반영하지 못한 것은 해상도"로 옮겼다(2026-10-01).
_SYSTEM_UNAPPLIED = (
    "\n- '반영하지 못한 것'은 한 마디로 밝힙니다. 반영되지 않은 말을 반영된 것처럼 쓰지 않습니다."
    "\n- '반영하지 못한 것'에 괄호로 덧붙은 사실(예: 지금 GPU는 마침 NVIDIA 제품이에요)이 있으면 함께 씁니다."
)
_SYSTEM_NOTHING_UNAPPLIED = "\n- 반영 여부는 언급하지 않습니다."
# 말하지 않아 기본값으로 정한 것("해상도는 말씀 안 하셔서 …") — 단계에는 두고 요약 입력에서는 뺀다.
_ASSUMED = "말씀 안 하셔서"
_UNAPPLIED_SENTENCE = re.compile(r"[^.!?\n]*반영(?:하지 못|되지 않|하지 않|이 안)[^.!?\n]*[.!?]?\s*")

# 요약에 나와도 되는 글자 — 한글, 영문·숫자·기호(제품명·금액), 가운뎃점·화살표·따옴표. 그 밖(키릴·한자·가나 등)이
# 보이면 버린다: gpt-4o-mini 가 "추천 구성 предложили 이후"처럼 러시아어 낱말을 섞은 적이 있다(2026-10-01).
_ALLOWED = re.compile(r"[\uac00-\ud7a3\u3131-\u318e\x20-\x7e\n·→‘’“”…]*")


def llm_available() -> bool:
    return not MOCK_MODE and LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY) and bool(LLM_MODEL)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_LIMIT else text[: _TEXT_LIMIT - 1] + "…"


def _eul(word: str) -> str:
    return josa(word, "을/를")


def _euro(word: str) -> str:
    return josa(word, "으로/로")


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
        "SELECT id, created_at, completed_at FROM engine.recommendation_run "
        "WHERE revision_id=%s AND status IN ('completed','stale') AND completed_at IS NOT NULL ORDER BY created_at",
        (revision_id,),
    ).fetchall()
    # 견적 수정하기로 복사한 실행은 원본 완료 시각을 그대로 가져와 생성 시각보다 앞선다 — 새로 받은 추천이 아니다.
    # 복사본이 있으면 견적서를 연 순간부터 결과 화면이다.
    cloned = bool(runs) and runs[0][2] < runs[0][1]
    live = [(run_id, completed_at) for run_id, created_at, completed_at in runs if completed_at >= created_at]
    first_result_at = revision["created_at"] if cloned else (live[0][1] if live else None)
    # 조건을 정하거나 바꾼 말은 결과 화면에서 했어도 조건 대화다("예산을 170만원으로 할게요").
    condition_sources = {row[0] for row in conn.execute(
        "SELECT source_message_id FROM planning.plan_condition WHERE revision_id=%s AND source_message_id IS NOT NULL",
        (revision_id,)).fetchall()}

    # 대화는 목록(plan) 하나에 하나다. 견적서(revision)가 여럿이면 이 견적서를 쓰던 동안의 말만 — 새 견적서는
    # 앞 견적서가 확정된 뒤에 만들어지므로 [revision 생성, 확정] 구간이 곧 이 견적서의 대화다.
    start, end = revision["created_at"], revision.get("confirmed_at")
    feedback = conn.execute(
        "SELECT event_type, event_key, payload, occurred_at FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type IN ('item_replaced','item_removed') ORDER BY occurred_at",
        (revision_id,),
    ).fetchall()
    said = [m for m in ConversationRepo(conn).messages(revision["conversation_id"])
            if m["role"] == "user" and m["content"].strip()
            and m["created_at"] >= start and (end is None or m["created_at"] <= end)]
    events: list[dict] = []
    for index, m in enumerate(said):
        # 결과에 영향을 준 말만 남긴다 — 조건을 정하거나 바꾼 말, 또는 그 뒤 다음 말 전에 부품을 바꾸거나 뺀 말.
        # 아무것도 바꾸지 않은 질문("왜 이 그래픽카드야?")이나 엉뚱한 말("ㅁㄴㅇㄹ")은 대화 내역에만 남는다.
        until = said[index + 1]["created_at"] if index + 1 < len(said) else end
        acted = any(m["created_at"] <= at and (until is None or at < until) for _t, _k, _p, at in feedback)
        if m["id"] not in condition_sources and not acted:
            continue
        # 첫 추천이 나오기 전의 말과 조건을 바꾼 말은 조건 대화, 그 밖에 결과가 나온 뒤의 말은 결과 화면에서 물은 것이다.
        after = first_result_at is not None and m["created_at"] > first_result_at and m["id"] not in condition_sources
        events.append({"at": m["created_at"], "kind": "question" if after else "condition", "text": _clip(_user_text(m["content"]))})

    for index, (_run_id, completed_at) in enumerate(live):
        events.append({"at": completed_at, "kind": "recommend",
                       "text": "추천 구성을 받았어요." if index == 0 and not cloned else "조건을 바꿔 추천을 다시 받았어요."})

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


_STEP_LABEL = {"start": "시작", "change": "조건 변경", "swap": "직접 교체", "remove": "직접 제외",
               "unapplied": "반영 못 함", "confirm": "확정"}


def rule_summary(steps: list[dict]) -> str:
    """LLM 없이 쓰는 요약 — 단계의 문장을 그대로 잇는다."""
    parts: list[str] = []
    for step in steps:
        if step["kind"] == "start":
            wanted = step["text"].removeprefix("원하신 것: ")
            parts.append(f"{josa(wanted, '으로/로')} 찾기 시작하셨어요." if wanted != step["text"] else f"{step['text']}.")
        elif step["kind"] == "change":
            parts.append(f"{step['text']}" + (f" — {step['changes'][0]}." if step["changes"] else "."))
        elif step["kind"] in ("swap", "remove", "confirm"):
            parts.append(f"{step['text']}.")
        elif step["kind"] == "unapplied":
            parts.append(f"말씀하셨지만 반영하지 못한 것이 {len(step['notes'])}가지 있어요.")
    return " ".join(parts)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def _prompt(steps: list[dict]) -> str:
    lines = ["단계 목록"]
    for i, step in enumerate(steps, start=1):
        lines.append(f"{i}. [{_STEP_LABEL.get(step['kind'], step['kind'])}] {step['text']}")
        lines += [f"   - {c}" for c in step["changes"]]
        lines += [f"   · {n}" for n in step["notes"] if _ASSUMED not in n]
        if step["quote"]:
            lines.append(f"   (사용자 말: “{step['quote']}”)")
    return "\n".join(lines)


def llm_summary(steps: list[dict]) -> str | None:
    """단계 목록만 넣어 LLM 요약을 받는다. 실패하거나, 단계에 없는 숫자나 한글·영문 밖의 글자가 나오면 None."""
    from src.clients.llm_client import call_llm

    prompt = _prompt(steps)
    unapplied = any(step["kind"] == "unapplied" for step in steps)
    try:
        system = _SYSTEM + (_SYSTEM_UNAPPLIED if unapplied else _SYSTEM_NOTHING_UNAPPLIED)
        text = (call_llm(prompt, system=system).get("text") or "").strip()
    except Exception:
        return None
    if not unapplied:
        text = _UNAPPLIED_SENTENCE.sub("", text).strip()     # 지시를 어기고 "반영하지 못한 것은 없습니다"를 붙여도 뺀다
    if not text or not _ALLOWED.fullmatch(text):
        return None
    if not _numbers(text) <= _numbers(prompt):
        return None
    return text


def summarize(list_id: UUID, revision: dict, steps: list[dict]) -> str:
    key = (str(list_id), revision["confirmed_at"].isoformat() if revision.get("confirmed_at") else "", hash(_prompt(steps)))
    if key in _summary_cache:
        return _summary_cache[key]
    text = llm_summary(steps) if llm_available() else None
    if text is None:
        return rule_summary(steps)        # 규칙 문장은 캐시하지 않는다 — 다음 요청에서 LLM을 다시 시도한다
    _summary_cache[key] = text
    return text


def build(conn, revision: dict) -> dict:
    """DB 에서 읽는 부분 — 단계와 사건. 요약(LLM)은 render 가 트랜잭션 밖에서 만든다."""
    from src.services import history_journey
    return {"steps": history_journey.build_steps(conn, revision), "events": build_events(conn, revision)}


def render(list_id: UUID, revision: dict, journey: dict) -> dict:
    """응답 모양. DB 를 쓰지 않는다 — 라우터가 트랜잭션을 닫은 뒤 부른다(LLM 대기 동안 연결을 잡지 않는다)."""
    return {
        "summary": {"status": "ready", "text": summarize(list_id, revision, journey["steps"])},
        "steps": journey["steps"],
        "events": [{"at": e["at"].isoformat(), "kind": e["kind"], "text": e["text"]} for e in journey["events"]],
    }
