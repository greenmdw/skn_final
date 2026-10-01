"""견적 리스트 히스토리 (C1: docs/개발요청_백엔드_및_타팀.md 2번).

확정된 목록 하나가 만들어지기까지의 여정을 세 층으로 돌려준다.

- **요약(summary)**: 2~3문장. LLM이 아래 단계만 보고 쓴다. LLM을 못 쓰거나(MOCK_MODE·키 없음), 실패하거나,
  단계에 없는 숫자를 쓰거나, 한글·영문 밖의 글자(키릴 문자 등)를 섞으면 규칙 문장으로 대신한다.
- **이렇게 정해졌어요(steps)**: 결과를 바꾼 것만 몇 단계로 — `history_journey` 가 기록에서 코드로 만든다.
- **자세히(events)**: 대화 순서대로 "한 말 → 그 결과" — 조건을 정한 말엔 알아들은 조건, 바꿔 달라는 말엔 바뀐 것
  (없으면 "바뀐 것 없음"), 그 사이 추천·버튼 교체·확정. 아무것도 바꾸지 않은 질문과 잡담은 대화 내역에서 본다.
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
    """칩으로 고른 금액은 숫자만 남는다("5000000") — 사용자가 말하는 단위로 적는다("500만 원", 단계와 같게)."""
    from src.services.history_journey import _man
    text = " ".join(text.split())
    return _man(int(text)) if text.isdigit() and len(text) >= 4 else text


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


def _swap_texts(items: dict, events: list[tuple], names: dict) -> list[str]:
    """교체·제외 이벤트들 → "GPU RTX 4070 SUPER → RX 6800 XT" 줄. 한 품목을 여러 번 바꿨으면 처음 → 마지막,
    되돌렸으면 뺀다 — 에이전트가 요청 하나에 후보를 여러 번 바꿔 본 것이 한 줄이 된다."""
    from src.services.recommendation_service import _SWAP_RE

    order: list[str] = []
    seen: dict[str, dict] = {}
    for event_type, event_key, payload, _at in events:
        payload = payload or {}
        item_id = payload.get("item_id") or _key_item(event_key) or event_key
        item = items.get(item_id or "", {})
        slot = payload.get("slot") or item.get("slot") or "부품"
        if item_id not in seen:
            order.append(item_id)
            seen[item_id] = {"slot": slot, "from": payload.get("from_variant_id"), "removed": False, "reason": item.get("reason", "")}
        if event_type == "item_removed":
            seen[item_id]["removed"] = True
        else:
            seen[item_id]["to"] = payload.get("to_variant_id")
    lines = []
    for item_id in order:
        s = seen[item_id]
        if s["removed"]:
            lines.append(f"{_eul(s['slot'])} 뺐어요")
            continue
        before, after = names.get(s["from"] or ""), names.get(s.get("to") or "")
        if s["from"] and s["from"] == s.get("to"):
            continue                                          # 바꿨다가 되돌렸다
        if not (before and after):
            # 예전 기록(무엇→무엇이 없음): 교체 사유 문장에서 자동 추천 제품을 찾는다.
            found = _SWAP_RE.search(s["reason"])
            before, after = (found.group(1), items.get(item_id, {}).get("product")) if found else (None, None)
        lines.append(f"{s['slot']} {before} → {after}" if before and after else f"{_eul(s['slot'])} 다른 제품으로 바꿨어요")
    return lines


def _understood(cat_def: dict, rows: list[dict]) -> str:
    """조건 대화의 말 한 마디에서 시스템이 알아들은 조건 — "게임 · 오버워치 · 200만 원"."""
    from src.services import history_journey
    values = {r["key"]: r["value"] for r in rows}
    shown = history_journey._display(cat_def, values)
    parts = [shown[k][1] for k in history_journey._KEYS if k in shown and values.get(k) not in (None, "", [])]
    if "budget_max" in shown and values.get("budget_max"):
        parts[parts.index(shown["budget_max"][1])] = f"예산 {shown['budget_max'][1]}"      # "170만 원"만으로는 무엇인지 모른다
    if "brand_pref" in shown and values.get("brand_pref"):
        parts[parts.index(shown["brand_pref"][1])] = f"{shown['brand_pref'][1]} CPU"
    parts += [f"요청 ‘{x}’" for x in values.get("extra") or []]
    return " · ".join(parts)


def build_events(conn, revision: dict) -> list[dict]:
    """대화 순서대로 "한 말 → 그 결과". 각 사건은 {at, kind, text, quote} — kind:
    condition(조건을 정한 말 → 알아들은 조건) | request(바꿔 달라는 말 → 바뀐 것, 없으면 "바뀐 것 없음") |
    recommend | swap·remove(버튼으로 직접) | confirm.

    아무것도 바꾸지 않은 질문("왜 이 그래픽카드야?")과 엉뚱한 말("ㅁㄴㅇㄹ")은 빠진다 — 원문은 대화 내역에서 본다.
    바꿔 달라는 말은 결과가 없어도 남긴다: 빠지면 다음 말("그럼 더 비싼거로 바꿔줘")이 무엇을 받는지 모른다.
    말이 바꾼 부품과 버튼으로 바꾼 부품은 시각으로 가른다 — 그 말과 그 말의 답 사이에 일어난 교체가 말이 시킨 것이다
    (결과 채팅은 사용자 말을 처리 전에, 답을 처리 뒤에 저장한다). 질문과 답이 같은 시각인 예전 기록은 바꿔 달라는
    말일 때만 다음 말 전까지의 교체를 그 말의 결과로 본다."""
    from psycopg.rows import dict_row

    from src.categories import load_category
    from src.services.history_journey import _CHANGE_ASK

    revision_id = revision["id"]
    runs = conn.execute(
        "SELECT id, created_at, completed_at FROM engine.recommendation_run "
        "WHERE revision_id=%s AND status IN ('completed','stale') AND completed_at IS NOT NULL ORDER BY created_at",
        (revision_id,),
    ).fetchall()
    # 견적 수정하기로 복사한 실행은 원본 완료 시각을 그대로 가져와 생성 시각보다 앞선다 — 새로 받은 추천이 아니다.
    cloned = bool(runs) and runs[0][2] < runs[0][1]
    live = [(run_id, completed_at) for run_id, created_at, completed_at in runs if completed_at >= created_at]
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT condition_key AS key, value->'value' AS value, source_message_id FROM planning.plan_condition "
        "WHERE revision_id=%s AND source_message_id IS NOT NULL ORDER BY created_at",
        (revision_id,),
    ).fetchall()
    by_message: dict = {}
    for r in rows:
        by_message.setdefault(r["source_message_id"], []).append(r)

    start, end = revision["created_at"], revision.get("confirmed_at")
    feedback = conn.execute(
        "SELECT event_type, event_key, payload, occurred_at FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type IN ('item_replaced','item_removed') ORDER BY occurred_at",
        (revision_id,),
    ).fetchall()
    items = _item_slots(conn, revision_id)
    names = _variant_names(conn, {v for _t, _k, p, _a in feedback
                                  for key in ("from_variant_id", "to_variant_id") if (v := (p or {}).get(key))})
    cat_def = load_category("computer")

    talk = [m for m in ConversationRepo(conn).messages(revision["conversation_id"])
            if m["created_at"] >= start and (end is None or m["created_at"] <= end) and m["content"].strip()]
    events: list[dict] = []
    claimed: set[int] = set()
    for index, m in enumerate(talk):
        if m["role"] != "user":
            continue
        later = talk[index + 1:]
        reply = next((x for x in later if x["role"] == "assistant"), None)
        next_user = next((x for x in later if x["role"] == "user"), None)
        until = next_user["created_at"] if next_user else end
        asks = bool(_CHANGE_ASK.search(m["content"]))
        if m["id"] in by_message:
            caused = []          # 조건을 정한 말은 조건 대화가 처리한다 — 부품을 바꾸지 않는다("예산을 200만원으로 올려 주세요")
        elif reply is not None and reply["created_at"] > m["created_at"]:
            caused = [i for i, e in enumerate(feedback) if m["created_at"] <= e[3] <= reply["created_at"]]
        elif asks:
            caused = [i for i, e in enumerate(feedback) if m["created_at"] <= e[3] and (until is None or e[3] < until)]
        else:
            caused = []
        caused = [i for i in caused if i not in claimed]
        claimed.update(caused)
        changes = _swap_texts(items, [feedback[i] for i in caused], names)
        quote = _clip(_user_text(m["content"]))
        if m["id"] in by_message:
            understood = _understood(cat_def, by_message[m["id"]])
            events.append({"at": m["created_at"], "kind": "condition", "quote": quote,
                           "text": understood or "조건을 정했어요"})
        elif asks or changes:
            events.append({"at": m["created_at"], "kind": "request", "quote": quote,
                           "text": " · ".join(changes) if changes else "바뀐 것 없음"})

    for index, (_run_id, completed_at) in enumerate(live):
        events.append({"at": completed_at, "kind": "recommend", "quote": None,
                       "text": "추천 구성을 받았어요." if index == 0 and not cloned else "조건을 바꿔 추천을 다시 받았어요."})

    # 말 없이 버튼으로 바꾸거나 뺀 것 — 한 번에 한 줄.
    for i, e in enumerate(feedback):
        if i in claimed:
            continue
        line = _swap_texts(items, [e], names)
        if line:
            kind = "remove" if e[0] == "item_removed" else "swap"
            text = line[0] if kind == "remove" else f"직접 바꾸셨어요 · {line[0]}"
            events.append({"at": e[3], "kind": kind, "quote": None, "text": text})

    if revision.get("confirmed_at") is not None:
        events.append({"at": revision["confirmed_at"], "kind": "confirm", "quote": None,
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
        "events": [{"at": e["at"].isoformat(), "kind": e["kind"], "text": e["text"], "quote": e.get("quote")}
                   for e in journey["events"]],
    }
