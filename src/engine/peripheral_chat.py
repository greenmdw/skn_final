"""주변기기 채팅 한 턴 — 질문 분류, 이번 문장에서 새로 반영한 것, 반영하지 못한 말 설명, 질문 답변
(QA PQA-012·013·014, docs/local/주변기기_추천_QA_기획.md 2.3절).

DB·언어 모델을 모르는 순수 함수만 둔다. 언어 모델은 질문 종류를 고르는 데만 쓰이고(`peripheral_intent_agent`),
**답 문장은 이 모듈이 설정(`config/peripherals.yaml` 의 chat 절)·추천 결과·스펙·사용기에서만 만든다** — 없는 값을 지어내지 않는다.

## 원칙

- 질문은 조건을 바꾸지 않는다. 조건 말이 없는 질문 문장에서는 조건을 읽어 오지 않는다(`question_only`).
- 답장은 서버가 만든다: ① 이번 문장에서 **새로** 반영한 것 ② 질문의 답 ③ 반영하지 못한 말·상충(`compose_reply`).
- 값이 없으면 "정보가 없어요"라고 말한다. 0·역산·추정으로 채우지 않는다.
"""
from __future__ import annotations

from typing import Any

from src.dto import PeripheralResult
from src.engine import peripheral_intent as pi
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_payload import _REQUIREMENT_KEY_LABEL
from src.engine.peripheral_rules import (
    chat_config, kind_def, load_peripheral_rules, peripheral_kinds, purposes, situations, spec_conditions,
)

TOP_AXES = 2                      # "왜 골랐어?"에서 말하는 점수에 크게 반영된 축의 수
MAX_QUOTES_PER_ATTRIBUTE = 1      # 사용기 답변에서 속성마다 보여 주는 인용 문장 수

_EXTRA_KEY_LABELS = {
    "resolution_raw": "해상도", "switch_kind_raw": "스위치", "switch_method_raw": "스위치 방식", "battery_power_raw": "배터리",
    "dpi_max": "DPI(최대)", "key_force_min_g": "키압 최소(g)", "key_force_max_g": "키압 최대(g)",
    "connectivity_wired": "유선", "connectivity_wireless": "무선", "connectivity_bluetooth": "블루투스",
}
_CHECK_STATE_TEXT = {"ok": "맞아요", "fail": "맞지 않아요", "unknown": "확인이 필요해요"}


def _lower_has(text: str, words) -> bool:
    return any(w.lower() in text for w in words)


def _topic_hit(lowered: str, topics: dict[str, dict]) -> str | None:
    """주제 표에서 문장 **뒤쪽**에 낱말이 나오는 주제(질문은 보통 문장 끝에 있다 — "무선이면 좋겠는데 배터리는 얼마나 가?"는
    배터리). 위치가 같으면 더 긴 낱말을 가진 주제."""
    best: tuple[int, int] | None = None
    best_name: str | None = None
    for name, entry in topics.items():
        for word in entry["words"]:
            pos = lowered.rfind(word.lower())
            if pos >= 0 and (best is None or (pos, len(word)) > best):
                best, best_name = (pos, len(word)), name
    return best_name


def _glossary_hit(lowered: str, chat: dict) -> str | None:
    return _topic_hit(lowered, chat["glossary"])


# ── 질문 분류 ──────────────────────────────────────────────────────────────
def classify_question(text: str, rules: dict | None = None) -> Question | None:
    """문장이 질문이면 그 종류를, 아니면 None. 질문 말투(`chat.markers`)가 있어야 질문으로 본다 — "무게 가벼운 마우스 추천"처럼
    질문이 아닌 문장이 스펙 낱말 때문에 질문으로 읽히지 않게 한다. 위 말투만 있고 종류를 못 가른 문장은 None 이다
    (조건을 하나도 못 읽었을 때만 서비스가 `other` 로 본다)."""
    rules = rules or load_peripheral_rules()
    chat = chat_config(rules)
    if not chat:
        return None
    lowered = pi.normalize_text(text)
    if not _lower_has(lowered, chat["markers"]):
        return None
    kinds = pi.kinds_in_text(text)
    term = _glossary_hit(lowered, chat)
    spec_topic = _topic_hit(lowered, chat["spec_topics"])
    review_topic = _topic_hit(lowered, chat["review_topics"])
    for qtype, entry in chat["types"].items():
        by_words = _lower_has(lowered, entry["words"])
        if qtype == "term":
            if by_words and term is not None:
                return Question(type="term", topic=term, kinds=kinds)
        elif qtype == "spec":
            if by_words or spec_topic:
                return Question(type="spec", topic=spec_topic, kinds=kinds)
        elif qtype == "review":
            if by_words or review_topic:
                return Question(type="review", topic=review_topic, kinds=kinds)
        elif by_words:
            return Question(type=qtype, kinds=kinds)
    return None


def has_question_marker(text: str, rules: dict | None = None) -> bool:
    """질문 말투(물음표·"뭐야"·"어때" 등)가 있는가. 언어 모델이 질문이라고 해도 이 말투가 없으면 조건 문장으로 둔다."""
    rules = rules or load_peripheral_rules()
    return _lower_has(pi.normalize_text(text), chat_config(rules).get("markers", ()))


def has_request_words(text: str, rules: dict | None = None) -> bool:
    """질문 문장 안에 조건을 함께 말한 표현("무선이면 좋겠는데", "추천해줘")이 있는가."""
    rules = rules or load_peripheral_rules()
    return _lower_has(pi.normalize_text(text), chat_config(rules).get("request_words", ()))


def question_only(interp: Interpretation) -> Interpretation:
    """순수한 질문 문장의 해석에서 조건을 모두 지운다("래피드 트리거가 뭐야?"가 래피드 트리거 조건이 되지 않게). 종류와 질문만 남긴다."""
    return Interpretation(kinds=interp.kinds, question=interp.question)


def read_nothing(interp: Interpretation) -> bool:
    """해석에서 아무것도 읽지 못했는가(종류·조건·금액·강조·브랜드·손 크기·질문 모두 비어 있음)."""
    return not (interp.kinds or interp.purposes or interp.situations or interp.stated or interp.budget or interp.budget_min or interp.budget_total
                or interp.emphasis or interp.brand_like or interp.brand_avoid or interp.hand_size or interp.question)


# ── 이번 문장에서 새로 반영한 것 ───────────────────────────────────────────────
def _won(value: int) -> str:
    return f"{value:,}원"


def _reflected(interp: Interpretation, rules: dict) -> dict[tuple, dict[str, str]]:
    """해석이 지금 반영하고 있는 것 하나하나(키 → {kind, label}). 이전 해석과 비교해 새로 생긴 것을 가린다."""
    items: dict[tuple, dict[str, str]] = {}
    for kind, resolved in pi.resolve(interp, rules).items():
        for purpose in resolved.purposes:
            items[(kind, "purpose", purpose["code"])] = {"kind": kind, "label": purpose["label"]}
        for cond in [*resolved.filters, *resolved.preferences]:
            items[(kind, "condition", cond.condition)] = {"kind": kind, "label": cond.label}
    shown_by_kind = {code for kind in interp.kinds for code in purposes(kind, rules)}
    for code in interp.situations:
        if code not in shown_by_kind:       # 어떤 종류의 목적 표에도 없는 상황은 위에서 안 나왔다 — 체감 점수에 쓰이므로 읽었다고 말한다
            items[("*", "situation", code)] = {"kind": "*", "label": situations(rules)[code]["label"]}
    for kind, won in interp.budget.items():
        items[(kind, "budget", won)] = {"kind": kind, "label": f"{kind_def(kind, rules)['label']} 예산 {_won(won)}"}
    for kind, won in interp.budget_min.items():
        items[(kind, "budget_min", won)] = {"kind": kind, "label": f"{kind_def(kind, rules)['label']} 예산 {_won(won)} 이상"}
    if interp.budget_total:
        items[("*", "budget_total", interp.budget_total)] = {"kind": "*", "label": f"예산 합계 {_won(interp.budget_total)}"}
    for kind, axes in interp.emphasis.items():
        for axis in axes:
            if axis == "브랜드":
                continue                    # 선호 브랜드를 말하면 저절로 붙는다 — 브랜드 이름으로 한 번만 말한다
            items[(kind, "emphasis", axis)] = {"kind": kind, "label": f"{kind_def(kind, rules)['label']} {axis} 중시"}
    for kind, brands in interp.brand_like.items():
        for brand in brands:
            items[(kind, "brand_like", brand)] = {"kind": kind, "label": f"{brand} 선호"}
    for kind, brands in interp.brand_avoid.items():
        for brand in brands:
            items[(kind, "brand_avoid", brand)] = {"kind": kind, "label": f"{brand} 제외"}
    if interp.hand_size:
        names = {"small": "작은 편", "medium": "보통", "large": "큰 편"}
        items[("*", "hand_size", interp.hand_size)] = {"kind": "*", "label": f"손 크기 {names[interp.hand_size]}"}
    return items


def new_conditions(previous: Interpretation | None, current: Interpretation, rules: dict | None = None) -> list[dict[str, str]]:
    """이전 해석에는 없고 지금 해석에 새로 생긴 반영 항목([{kind, label}], 같은 라벨은 한 번)."""
    rules = rules or load_peripheral_rules()
    before = _reflected(previous, rules) if previous is not None else {}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, item in _reflected(current, rules).items():
        if key in before or item["label"] in seen:
            continue
        seen.add(item["label"])
        out.append(item)
    return out


# ── 반영하지 못한 말·읽은 방법 ────────────────────────────────────────────────
def unsupported_notes(text: str, rules: dict | None = None) -> list[dict[str, str]]:
    """아직 조건으로 고를 수 없는 말이 문장에 있으면 그 설명([{words, text}]). 단어 규칙이 못 읽은 말도 사용자에게 알린다."""
    rules = rules or load_peripheral_rules()
    lowered = pi.normalize_text(text)
    out = []
    for entry in chat_config(rules).get("unsupported", ()):
        hit = next((w for w in entry["words"] if w.lower() in lowered), None)
        if hit:
            out.append({"words": hit, "text": entry["text"]})
    return out


def unrecognized_notes(items: list[str]) -> list[str]:
    """언어 모델이 목록에서 못 고른 말을 사용자에게 알리는 문장."""
    return [f"“{item}”: 아직 조건으로 고를 수 없어서 반영하지 못했어요." for item in items]


def reading_notes(text: str, interp: Interpretation, rules: dict | None = None) -> list[str]:
    """낱말이 아니라 가까이 나온 두 낱말로 읽은 조건은 어떻게 읽었는지 말한다(잘못 읽었으면 사용자가 고칠 수 있게)."""
    rules = rules or load_peripheral_rules()
    notes: list[str] = []
    for kind, ids in interp.stated.items():
        conds = spec_conditions(kind, rules)
        for cond_id in ids:
            cond = conds.get(cond_id)
            word = pi.near_reading(text, cond, kind) if cond else None
            if word:
                notes.append(f"‘{word}’ → {kind_def(kind, rules)['label']} {cond['label']} 조건으로 읽었어요.")
    return notes


def conflict_notes(resolved: dict[str, Any], previous_resolved: dict[str, Any] | None = None) -> list[str]:
    """함께 고를 수 없는 조건을 서버가 어떻게 정리했는지(이전 턴에 이미 알린 것은 다시 말하지 않는다)."""
    seen = {tuple(c["conditions"]) for r in (previous_resolved or {}).values() for c in r.conflicts}
    notes = []
    for entry in resolved.values():
        for conflict in entry.conflicts:
            if tuple(conflict["conditions"]) in seen:
                continue
            a, b = conflict["labels"]
            if conflict["kept"] is None:
                notes.append(f"‘{a}’·‘{b}’ 조건은 함께 고를 수 없어서 둘 다 뺐어요. 어느 쪽인지 다시 말씀해 주세요.")
            else:
                kept = a if conflict["kept"] == conflict["conditions"][0] else b
                notes.append(f"‘{a}’·‘{b}’ 조건은 함께 고를 수 없어서 ‘{kept}’ 쪽을 우선했어요.")
    return notes


# ── 질문 답변: 결과가 필요 없는 것 ──────────────────────────────────────────────
RESULT_QUESTION_TYPES = ("why", "compare", "spec", "review", "compat")


def needs_result(question: Question | None) -> bool:
    return question is not None and question.type in RESULT_QUESTION_TYPES


def kind_condition_chips(rules: dict | None = None) -> list[str]:
    """종류마다 "…는 어떤 조건으로 나눌 수 있어?" 문장(모두 같은 종류의 질문으로 읽힌다). 어떤 기기인지 모를 때 고르게 한다."""
    rules = rules or load_peripheral_rules()
    return [f"{kind_def(kind, rules)['label']}는 어떤 조건으로 나눌 수 있어?" for kind in peripheral_kinds(rules)]


def chips(has_result: bool, rules: dict | None = None) -> list[str]:
    """다음에 물어볼 만한 문장. 결과가 있으면 결과에 대한 질문, 없으면 조건·할 수 있는 일."""
    rules = rules or load_peripheral_rules()
    chat = chat_config(rules)
    return list(chat["chips"]["after_result" if has_result else "start"]) if chat else []


def _conditions_text(kind: str, rules: dict, chat: dict) -> str:
    label = kind_def(kind, rules)["label"]
    table = purposes(kind, rules)
    goals = [e["label"] for e in table.values()]
    conds = [e["label"] for e in spec_conditions(kind, rules).values()]
    sits = [e["label"] for code, e in situations(rules).items() if code in table or code in ("trending", "design")]
    lines = [f"{label}에 말씀하실 수 있는 조건이에요."]
    if goals:
        lines.append(f"· 쓰는 목적: {', '.join(goals)}")
    if conds:
        lines.append(f"· 직접 말할 수 있는 조건: {', '.join(conds)}")
    if sits:
        lines.append(f"· 상황: {', '.join(sits)}")
    lines.append("· 예산은 “5만 원 이하”, 브랜드는 “로지텍 말고”, 중요한 것은 “가성비 좋은”처럼 말씀하시면 돼요.")
    lines.append(f"예) {chat['examples'][kind]}")
    return "\n".join(lines)


def static_answer(question: Question, kinds: list[str], rules: dict | None = None) -> dict[str, Any]:
    """결과가 없어도 답할 수 있는 질문(할 수 있는 일·말할 수 있는 조건·용어 설명·범위 밖)의 답.
    {type, topic, text, kinds, chips}. kinds 는 질문이 가리킨 종류, 없으면 지금 고른 종류."""
    rules = rules or load_peripheral_rules()
    chat = chat_config(rules)
    answers = chat["answers"]
    target = pi.kinds_all_order(question.kinds or kinds)
    if question.type == "capabilities":
        text, out_chips = answers["capabilities"], chips(False, rules)
    elif question.type == "conditions":
        if not target:
            return {"type": "conditions", "topic": None, "text": answers["no_kind"], "kinds": [],
                    "chips": kind_condition_chips(rules)}
        text = "\n\n".join(_conditions_text(k, rules, chat) for k in target)
        out_chips = chips(False, rules)
    elif question.type == "term" and question.topic in chat["glossary"]:
        text, out_chips = chat["glossary"][question.topic]["text"], []
    else:
        text, out_chips = answers["other"], chips(False, rules)
    return {"type": question.type, "topic": question.topic, "text": text, "kinds": target, "chips": out_chips}


# ── 질문 답변: 추천 결과가 필요한 것 ────────────────────────────────────────────
def _fmt_value(value: Any, unit: str | None) -> str:
    if isinstance(value, bool):
        return "지원해요" if value else "지원하지 않아요"
    if isinstance(value, (int, float)):
        return f"{value:g}{unit or ''}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _key_label(key: str) -> str:
    return _EXTRA_KEY_LABELS.get(key) or _REQUIREMENT_KEY_LABEL.get(key, key)


def _spec_line(topic: dict, specs: dict[str, Any]) -> str:
    present = [(k, specs[k]) for k in topic["keys"] if specs.get(k) is not None]
    if not present:
        return f"{topic['label']}: 카탈로그에 정보가 없어요"
    if len(topic["keys"]) == 1:
        return f"{topic['label']}: {_fmt_value(present[0][1], topic.get('unit'))}"
    return f"{topic['label']}: " + " · ".join(f"{_key_label(k)} {_fmt_value(v, None)}" for k, v in present)


def _answer_why(item: dict[str, Any]) -> list[str]:
    lines = [f"{item['kind_label']} — {item['product']['name']}: {item['reason']['text']}"]
    detail = item.get("score_detail")
    if detail:
        axes = sorted(detail["axes"], key=lambda a: -a["points"])[:TOP_AXES]
        lines.append("· 점수에 크게 반영된 축: " + ", ".join(f"{a['axis']}(가중치 {a['weight']:.0%})" for a in axes))
        if detail.get("weights_reason"):
            lines.append("· 가중치 조정: " + "; ".join(detail["weights_reason"]))
        if detail["penalties"].get("evidence", 0) > 0:
            lines.append(f"· 리뷰 근거가 {detail['evidence_count']}건뿐이라 점수를 조금 낮췄어요")
    return lines


def _answer_compare(item: dict[str, Any]) -> list[str]:
    alts = item.get("alternatives") or []
    if not alts:
        return [f"{item['kind_label']}: 비교할 다른 선택지가 없어요"]
    lines = [f"{item['kind_label']} — 1위 {item['product']['name']}({item['price']:,}원)와 비교"]
    for i, alt in enumerate(alts, start=2):
        diff = alt["diff"]
        gap = "같은 가격" if diff == 0 else f"1위보다 {abs(diff):,}원 {'저렴' if diff < 0 else '비쌈'}"
        extra = f", {alt['why_not_first']}" if alt.get("why_not_first") else ""
        lines.append(f"· {i}위 {alt['name']}({alt['price']:,}원): {gap}{extra}")
    return lines


def _answer_spec(item: dict[str, Any], specs: dict[str, Any], question: Question, chat: dict) -> list[str]:
    names = [question.topic] if question.topic in chat["spec_topics"] else chat["spec_summary"][item["kind"]]
    lines = [f"{item['kind_label']} — {item['product']['name']}"]
    lines += [f"· {_spec_line(chat['spec_topics'][n], specs)}" for n in names]
    return lines


def _answer_review(item: dict[str, Any], question: Question, chat: dict) -> list[str]:
    head = f"{item['kind_label']} — {item['product']['name']}"
    feel = item.get("feel")
    rows = (feel or {}).get("attributes") or []
    if question.topic in chat["review_topics"]:
        codes = set(chat["review_topics"][question.topic]["attributes"])
        rows = [r for r in rows if r["code"] in codes]
    else:
        rows = rows[:3]
    if not rows:
        topic = f"{chat['review_topics'][question.topic]['label']} 관련 " if question.topic in chat["review_topics"] else ""
        return [head, f"· {topic}사용기·리뷰 근거가 아직 없어요"]
    lines = [head]
    for row in rows:
        lines.append(f"· {row['label']}: {row['text']}")
        for quote in row.get("quotes", [])[:MAX_QUOTES_PER_ATTRIBUTE]:
            lines.append(f"  “{quote['sentence']}”")
    return lines


def _answer_compat(item: dict[str, Any], chat: dict) -> list[str]:
    if item["kind"] != "monitor":
        return [f"{item['kind_label']}: {chat['answers']['no_cross_check']}"]
    checks = item.get("checks") or []
    lines = [f"{item['kind_label']} — {item['product']['name']}"]
    if not checks:
        return [*lines, "· PC와 맞춰 볼 항목이 아직 없어요"]
    return [*lines, *(f"· {c['label']}: {_CHECK_STATE_TEXT.get(c['state'], c['state'])} — {c['detail']}" for c in checks)]


def result_answer(
    question: Question, result: PeripheralResult | None, payload: dict[str, Any] | None, kinds: list[str],
    pc_context: dict | None, rules: dict | None = None,
) -> dict[str, Any]:
    """추천 결과로 답할 수 있는 질문(고른 이유·비교·스펙·사용기·PC 호환)의 답. 답에 쓴 값은 모두 `payload`(응답에 나가는 값)와
    `result.picks[].candidate.specs`(카탈로그 스펙)에서 온다. 결과가 없으면 없다고 말한다."""
    rules = rules or load_peripheral_rules()
    chat = chat_config(rules)
    answers = chat["answers"]
    base = {"type": question.type, "topic": question.topic}
    if result is None or payload is None or payload.get("status") != "ready" or not payload.get("items"):
        return {**base, "text": answers["no_result"], "kinds": pi.kinds_all_order(kinds), "chips": chips(False, rules)}
    if question.type == "compat" and pc_context is None:
        return {**base, "text": answers["no_pc"], "kinds": [i["kind"] for i in payload["items"]], "chips": chips(True, rules)}

    wanted = set(question.kinds)
    items = [i for i in payload["items"] if not wanted or i["kind"] in wanted] or payload["items"]
    specs_by_kind = {p.kind: p.candidate.specs for p in result.picks}
    blocks: list[str] = []
    for item in items:
        if question.type == "why":
            lines = _answer_why(item)
        elif question.type == "compare":
            lines = _answer_compare(item)
        elif question.type == "spec":
            lines = _answer_spec(item, specs_by_kind.get(item["kind"], {}), question, chat)
        elif question.type == "review":
            lines = _answer_review(item, question, chat)
        else:
            lines = _answer_compat(item, chat)
        blocks.append("\n".join(lines))
    return {**base, "text": "\n\n".join(blocks), "kinds": [i["kind"] for i in items], "chips": chips(True, rules)}


# ── 답장 한 덩어리 ─────────────────────────────────────────────────────────
def compose_reply(
    new_items: list[dict[str, str]], reading: list[str], conflicts: list[str], answer: dict[str, Any] | None,
    not_reflected: list[str], *, example: str | None = None,
) -> str:
    """이번 턴의 답장: ① 이번에 새로 반영한 것(어떻게 읽었는지·정리한 상충 포함) ② 질문의 답 ③ 반영하지 못한 말.
    아무것도 없으면 읽어 낸 조건이 없다고 말하고 말하는 예를 든다 — 지난 턴까지 쌓인 조건을 되풀이하지 않는다."""
    parts: list[str] = []
    if new_items:
        parts.append("이번에 반영했어요: " + " · ".join(item["label"] for item in new_items))
    parts += reading
    parts += conflicts
    if answer:
        parts.append(answer["text"])
    parts += not_reflected
    if not parts:
        tail = f" 예: “{example}”" if example else ""
        parts.append("이번 문장에서는 새로 읽어 낸 조건이 없어요." + tail)
    return "\n".join(parts)
