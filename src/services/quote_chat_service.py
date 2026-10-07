"""PC 견적 점검 — 되묻기 채팅 (CHAT-04) + 대화 이력 저장.

저장된 비교 분석 결과(`quote_review`: 호환 · 가격 · 균형 · 우리 추천 비교)만 근거로 답하고, 같은 부품군의 대안을 조회한다.
에이전트(QUOTE_REVIEW_AGENT=1)가 있으면 도구로 사실을 읽어 답하고, 없거나 실패하면 이 모듈의 규칙 경로가 같은 사실 문장을
그대로 돌려준다 — 어느 쪽이든 새 수치·판정을 만들지 않는다(기획서 P7).

대화는 `identity.message`(이 견적 점검 세션의 conversation)에 저장한다 — 재시작·재접속 뒤에도 이어 묻고, 저장한 견적을 다시 열면
이전 대화를 복원할 수 있다(CHAT-08). 답변은 견적·저장된 결과를 바꾸지 않는다(조회만).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

from src.auth.deps import Principal
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import ValidationFailed
from src.repo.user_repo import ConversationRepo
from src.services import quote_alternatives, quote_comparison_service, quote_facts, quote_review_service as qrs, session_service

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 1000
HISTORY_TURNS = 8

_SLOT_WORDS = {
    "CPU": ("cpu", "프로세서", "씨피유"), "GPU": ("gpu", "그래픽", "지피유", "vga"), "RAM": ("ram", "램", "메모리"),
    "메인보드": ("메인보드", "보드", "mainboard"), "저장장치": ("ssd", "저장", "스토리지", "nvme"),
    "파워": ("파워", "psu", "전원"), "케이스": ("케이스", "case"), "쿨러": ("쿨러", "cooler", "수랭", "공랭"),
}
_CHEAPER = ("저렴", "싼 ", "싼걸", "싸게", "더 싸", "낮은 가격", "가성비", "절약", "줄이")      # 맨 "싸"는 "비싸"에도 있어 뺀다
_BETTER = ("더 좋은", "좋은", "상위", "업그레이드", "성능 높", "더 강", "빠른", "올리")
_INTENT_WORDS = {
    "alternatives": ("대안", "바꿀", "바꿔", "바꾸", "교체", "다른 제품", "다른 걸", "다른 거", "추천해", "대신", "후보",
                     "뭐가 있", "뭐 있", "말고", "걸로", "다른"),
    "compat": ("호환", "맞아", "맞나", "맞는", "들어가", "장착", "소켓", "전력", "충분", "문제", "안 되", "안되", "연결"),
    "prices": ("가격", "비싸", "싸", "얼마", "값", "비용"),
    "balance": ("부족", "과해", "과한", "충분", "용도", "성능", "균형", "병목", "예산 비중", "오버"),
    "compare": ("우리 추천", "비교", "차이", "뭐가 달라", "뭐가 다른", "추천이랑", "추천과"),
}
EVIDENCE_LABEL = {"overview": "견적 분석 요약", "compat": "호환 검사", "prices": "가격 비교", "balance": "용도 대비 균형",
                  "compare": "우리 추천과 비교", "alternatives": "대안 조회", "compare_parts": "부품 비교",
                  "saved_comparison": "저장 견적 비교", "series_hint": "제품 후보", "search_consent": "실시간 검색 동의",
                  "live_search": "실시간 검색"}
_PART_WORDS = ("스펙", "사양", "리뷰", "후기", "부품 비교", "다른 제품이랑", "이랑 비교", "와 비교", "과 비교", "랑 비교")


# 부품군 이름이 없어도 브랜드·시리즈·칩셋 이름이면 부품군을 안다 — "라이젠 9000이랑 비교해줘"·"RTX 4070 대신"은 이게 없으면 부품군을 못 찾아
# 일반 비교("우리 추천과 비교")로 빠졌고 말한 제품은 무시됐다(2026-10-07).
_SLOT_PATTERNS = {
    "CPU": re.compile(r"라이젠|ryzen|코어\s*(?:울트라|i\d)|core\s*(?:ultra|i\d)|(?<![a-z0-9])i[3579](?![a-z0-9])|셀러론|펜티엄"),
    "GPU": re.compile(r"지포스|geforce|(?<![a-z])rtx|(?<![a-z])gtx|라데온|radeon|엔비디아|nvidia|(?<![a-z])rx\s*\d{3,4}"),
    "RAM": re.compile(r"ddr[345]"),
    "메인보드": re.compile(r"(?<![a-z0-9])[abhxz]\d{3}e?m?(?![a-z0-9])"),
}


def match_slot(text: str) -> str | None:
    low = text.lower()
    for slot, words in _SLOT_WORDS.items():
        if any(w in low for w in words):
            return slot
    for slot, pattern in _SLOT_PATTERNS.items():
        if pattern.search(low):
            return slot
    return None


def _direction(text: str) -> str | None:
    cheaper, better = any(w in text for w in _CHEAPER), any(w in text for w in _BETTER)
    return "cheaper" if cheaper and not better else "better" if better and not cheaper else None


_COMPAT_AXIS = {"소켓": "socket", "전력": "power", "파워": "power", "메모리": "memory", "길이": "gpu_len", "높이": "cooler_height",
                "m.2": "m2", "슬롯": "ram_slots"}


_COMPARE_WORDS = ("비교", "대신", "말고", "바꾸면", "바꿔", "쓰면", "달라", "차이", "vs", "랑", "이랑", "와 ", "과 ")


def extract_targets(text: str, slot: str, pool: list, exclude_name: str | None = None) -> list[str]:
    """질문에 적힌 모델명(예: "RTX 4070", "9600X")을 카탈로그 후보 이름으로 — 모델이 이름을 잘못 옮기는 일(9600X → 7600X)을
    막으려고 코드가 질문 글에서 직접 찾는다. 하나로 특정되는 것만 돌려주고, 견적 속 부품 자신은 뺀다."""
    from src.engine.owned_parts import _is_model_token, _match_catalog, _significant, _tokens

    found: list[str] = []
    exact = _match_catalog(text, pool)
    if exact and len({c.name for c in exact}) == 1:
        found.append(exact[0].name)
    wanted = [t for t in _significant(_tokens(text)) if _is_model_token(t) and len(t) >= 3]
    for token in wanted:
        hits = [c for c in pool if token in _tokens(c.name)]
        if len({c.name for c in hits}) == 1 and hits[0].name not in found:
            found.append(hits[0].name)
    return [n for n in found if n != exclude_name]


_PARTICLE_TAIL = re.compile(r"(?<=[0-9A-Za-z가-힣])(?:이랑|랑|하고|과|와|으로|로|보다)$")
_CLAUSE_BREAK = frozenset({"대신", "말고", "vs", "VS", "그리고", "또는"})


def product_phrase(text: str, model_tokens: list[str] | None = None) -> str:
    """질문에서 **물어본 제품 이름만** — "RTX 6090이랑 비교해줘" → "RTX 6090", "CPU 5600X 대신 9999X 쓰면 뭐가 달라져?" → "9999X".

    제품 이름은 모델 번호 낱말(model_tokens)을 끝으로 하고, 거기서 앞으로 영문·숫자 낱말이나 브랜드 한글 낱말(라이젠·엔비디아)이 이어지는
    만큼이다. "대신/말고" 같은 절 경계나 앞 낱말의 조사(…랑·…과)를 만나면 거기서 멈춘다 — 비교하려는 견적 속 부품의 이름이 섞여
    검색어가 나빠지지 않게."""
    from src.engine.owned_parts import _ALIASES

    words = text.replace("?", " ").replace("!", " ").split()
    stripped = [_PARTICLE_TAIL.sub("", w) for w in words]
    wanted = [t.lower() for t in (model_tokens or [])]
    last = next((i for i in range(len(stripped) - 1, -1, -1)
                 if any(ch.isdigit() for ch in stripped[i]) and (not wanted or any(t in stripped[i].lower() for t in wanted))), None)
    if last is None:
        return text[:60].strip()
    phrase = [stripped[last]]
    i = last - 1
    while i >= 0 and len(phrase) < 4:
        previous_had_particle = stripped[i] != words[i]
        if words[i] in _CLAUSE_BREAK or previous_had_particle:
            break
        if not (re.fullmatch(r"[A-Za-z0-9\-.+/]+", stripped[i]) or stripped[i] in _ALIASES):      # "PC에"처럼 한글이 섞인 낱말은 이름이 아니다
            break
        phrase.insert(0, stripped[i])
        i -= 1
    return " ".join(phrase)[:60].strip()


_SERIES_THOUSAND = re.compile(r"^(\d)0{3}$")        # 9000 → 9xxx 모델들(라이젠 9000·RTX 5000)


def series_options(tokens: list[str], pool: list, limit: int = 6) -> list[str]:
    """"9000"처럼 모델이 아니라 시리즈를 가리키는 낱말이면, 카탈로그에서 그 시리즈에 속한 제품 이름들(없으면 빈 목록)."""
    from src.engine.owned_parts import _significant, _tokens

    for token in tokens:
        match = _SERIES_THOUSAND.match(token)
        if not match:
            continue
        prefix = re.compile(rf"^{match.group(1)}\d{{3}}[a-z0-9]*$")
        names = [c.name for c in pool if any(prefix.match(t) for t in _significant(_tokens(c.name)))]
        if names:
            return sorted(dict.fromkeys(names))[:limit]
    return []


def route(text: str, by_slot_loader=None, review: dict | None = None) -> list[tuple[str, dict]]:
    """질문에서 어떤 사실을 읽을지 — [(도구 이름, 인자)]. 규칙 경로의 답이면서 에이전트에는 미리 조회한 근거가 된다.

    카탈로그 로더와 저장된 결과를 주면 질문 속 제품 이름을 찾아 부품 비교(compare_parts)의 대상으로 넘긴다."""
    low = text.lower()
    slot = match_slot(low)
    if slot and by_slot_loader is not None and any(w in low for w in _COMPARE_WORDS):
        baseline = None
        if review is not None:
            from src.engine.owned_parts import resolve_owned_parts
            from src.categories import load_category
            specs = (review.get("input") or {}).get("current_specs") or {}
            baseline = (resolve_owned_parts(specs, by_slot_loader(), load_category("computer")["slot_structure"]).get(slot) or {}).get("name")
        pool = by_slot_loader().get(slot, [])
        targets = extract_targets(text, slot, pool, baseline)
        if not targets:
            # 질문에 모델명이 있는데 카탈로그에서 정확히 못 찾았다 — 다른 제품으로 슬쩍 바꿔 답하지 않는다(견적 속 부품 자신의 이름 낱말은 뺀다).
            #  ① 시리즈 낱말이 빠졌을 뿐 카탈로그에 있는 제품("엔비디아 5070")이면 그 제품들과 비교한다
            #  ② "라이젠 9000"처럼 시리즈 이름이면 어느 모델인지 되묻는다
            #  ③ 카탈로그에 없으면 "DB에 없다"고 알리고 검색 동의를 구한다(동의하면 실시간 검색 — 자동 실행 금지)
            from src.engine.owned_parts import _is_model_token, _significant, _tokens, catalog_family_matches
            own = set(_tokens(baseline or ""))
            leftover = [t for t in _significant(_tokens(text)) if _is_model_token(t) and len(t) >= 3 and t not in own]
            if leftover and any(w in low for w in ("비교", "대신", "말고", "바꾸면", "쓰면", "vs")):
                rest = " ".join(t for t in _tokens(text) if t not in own)
                family = catalog_family_matches(rest, pool)
                if family:
                    return [("compare_parts", {"slot": slot, "direction": None, "targets": [c.name for c in family[:4]]})]
                options = series_options(leftover, pool)
                if options:
                    return [("series_hint", {"slot": slot, "product": product_phrase(text, leftover), "options": options})]
                return [("search_consent", {"slot": slot, "product": product_phrase(text, leftover)})]
        if targets:
            return [("compare_parts", {"slot": slot, "direction": None, "targets": targets})]
    hits = {name for name, words in _INTENT_WORDS.items() if any(w in low for w in words)}
    if slot and _direction(low):                        # "GPU 더 저렴한 거" — 방향어가 있으면 대안 요청이다
        hits.add("alternatives")
    calls: list[tuple[str, dict]] = []
    if slot and any(w in low for w in _PART_WORDS):          # "GPU 스펙 비교", "CPU 리뷰는 어때" — 같은 부품군 다른 제품과 나란히
        return [("compare_parts", {"slot": slot, "direction": _direction(low), "targets": []})]
    if "alternatives" in hits and slot:
        calls.append(("alternatives", {"slot": slot, "direction": _direction(low)}))
        hits -= {"prices", "balance"}                    # "저렴한 GPU 추천해줘"의 "저렴/성능"은 대안 요청의 방향어다
    if "compat" in hits and not (slot and "alternatives" in hits):
        axis = next((a for word, a in _COMPAT_AXIS.items() if word in low), "")
        calls.append(("compat", {"axis": axis}))
    if "prices" in hits:
        calls.append(("prices", {"part": slot or ""}))
    if "balance" in hits and "compat" not in hits:
        calls.append(("balance", {}))
    if "compare" in hits:
        calls.append(("compare", {"part": slot or ""}))
    if not calls and slot:
        calls.append(("compare", {"part": slot}))          # "GPU는 어때?"처럼 부품만 물으면 우리 추천과의 비교를 보인다
    return calls or [("overview", {})]


def run_fact(review: dict, name: str, args: dict, by_slot_loader) -> str:
    if name == "overview":
        return quote_facts.overview(review)
    if name == "compat":
        return quote_facts.compat(review, args.get("axis", ""))
    if name == "prices":
        return quote_facts.prices(review, args.get("part", ""))
    if name == "balance":
        return quote_facts.balance(review)
    if name == "compare":
        return quote_facts.compare(review, args.get("part", ""))
    if name == "alternatives":
        result = quote_alternatives.alternatives(review, args["slot"], by_slot_loader(), args.get("direction"))
        return quote_facts.alternatives(result)
    if name == "compare_parts":
        result = quote_alternatives.compare_parts(review, args["slot"], by_slot_loader(), args.get("targets") or None,
                                                  args.get("direction"))
        return quote_facts.compare_parts(result)
    if name == "series_hint":
        names = ", ".join(args.get("options") or [])
        return (f"'{args.get('product')}'은(는) 특정 제품이 아니라 시리즈 이름이에요. 카탈로그에는 이 시리즈로 {names} 등이 있어요. "
                "어느 모델과 비교할까요?")
    if name == "search_consent":
        from src.agent.conditions_agent import SEARCH_PERMISSION_MARKER
        return f"'{args.get('product')}'는 저희 DB에 없는 상품으로 확인됩니다. {SEARCH_PERMISSION_MARKER}"
    raise ValueError(f"unknown fact: {name}")


def rule_reply(review: dict, text: str, by_slot_loader, calls: list | None = None, fact=None) -> tuple[str, list[str]]:
    """에이전트 없이 — 질문에 맞는 사실 문장을 그대로 돌려준다(요약·판정 없음). `calls`·`fact`를 주면 그 조회를 쓴다."""
    calls = calls if calls is not None else route(text, by_slot_loader, review)
    fact = fact or (lambda n, a: run_fact(review, n, a, by_slot_loader))
    body = "\n\n".join(f"[{EVIDENCE_LABEL[n]}]\n{fact(n, a)}" for n, a in calls)
    if calls[0][0] == "overview":
        body += ("\n\n호환, 가격, 용도 대비 균형, 우리 추천과의 차이를 물어보거나 '그래픽카드 더 저렴한 걸로 뭐가 있어?'처럼 "
                 "부품을 골라 대안을 물어볼 수 있어요.")
    return body, [EVIDENCE_LABEL[n] for n, _ in calls]


def _catalog_loader():
    cache: dict = {}

    def load():
        if "by_slot" not in cache:
            cache["by_slot"] = load_pc_catalog(lambda _msg: None)
        return cache["by_slot"]
    return load


def _stored_review(conn, list_id: UUID, principal: Principal) -> tuple[dict, dict]:
    from src.repo.plan_repo import QUOTE_REVIEW_KEY, PlanRepo
    from src.errors import NotFound

    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    row = repo.active_condition(revision["id"], QUOTE_REVIEW_KEY)
    if row is None:
        raise NotFound("이 목록에는 견적 점검 결과가 없습니다.")
    return revision, row["value"]["value"]


def _pairs(messages: list[dict]) -> list[tuple[str, str]]:
    """저장된 대화 → 최근 (질문, 답) 쌍. 짝이 안 맞는 행(중간 실패)은 건너뛴다."""
    pairs: list[tuple[str, str]] = []
    pending: str | None = None
    for m in messages:
        if m["role"] == "user":
            pending = m["content"]
        elif m["role"] == "assistant" and pending is not None:
            pairs.append((pending, m["content"]))
            pending = None
    return pairs[-HISTORY_TURNS:]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _payload(message_id: UUID | str, created_at: str, reply: str, meta: dict) -> dict:
    """저장된(또는 방금 만든) 답 → API 응답. 메타데이터가 없는 예전 답은 빈 시각 자료·가이드로 돌려준다."""
    return {
        "message_id": str(message_id), "answer_id": meta.get("answer_id") or str(message_id), "reply": reply,
        "evidence": list(meta.get("evidence") or []), "guide_refs": list(meta.get("guide_refs") or []),
        "visuals": list(meta.get("visuals") or []), "via": meta.get("via") or "rules",
        "display_target": meta.get("display_target") or "chat", "duplicate_of": meta.get("duplicate_of"),
        "created_at": created_at,
    }


def _answer_search_consent(conn, stored_messages: list[dict], text: str) -> tuple[str, dict] | None:
    """직전 답이 "외부 검색을 진행해도 될까요?"였고 이번 메시지가 동의이면, 그 제품을 실시간 검색해 답한다. 아니면 None.
    동의 판정은 모델이 아니라 코드(is_search_confirmation)가 한다 — 두 대화 에이전트와 같은 규칙."""
    from src.agent.conditions_agent import is_search_confirmation
    from src.errors import ServiceUnavailable
    from src.services import live_spec_lookup

    last = next((m for m in reversed(stored_messages) if m["role"] == "assistant"), None)
    pending = ((last or {}).get("metadata") or {}).get("pending_search")
    if not pending or not is_search_confirmation(last["content"], text):
        return None
    product, slot = pending["product"], pending["slot"]
    label = EVIDENCE_LABEL["live_search"]
    meta = {"answer_id": str(uuid.uuid4()), "evidence": [label], "guide_refs": [], "visuals": [], "via": "rules",
            "display_target": "chat"}
    if not live_spec_lookup.available():
        return "지금은 실시간 검색을 쓸 수 없어요.", meta
    try:
        result = live_spec_lookup.lookup(conn, product, slot=slot)
    except ServiceUnavailable as exc:                        # 검색이 몰려 있거나 연결 실패 — 대화를 끊지 않고 문장으로 알린다
        return f"{exc.message} 지금은 '{product}' 정보를 가져오지 못했어요.", meta
    if not result.relevant or not result.has_any_field():
        return f"'{product}'에 대한 정보를 실시간 검색으로도 찾지 못했어요. 제품 이름을 다시 확인해 주세요.", meta
    found = {k: v for k, v in result.supported_fields.model_dump().items() if v is not None}
    fields = ", ".join(f"{k}={v}" for k, v in found.items())
    source = f" · 출처: {result.source_url}" if result.source_url else ""
    return (f"'{product}' 실시간 검색 결과 — {fields}{source} · 카탈로그 정식 등재 값이 아니니 참고만 하세요. "
            f"견적 속 {slot}과 직접 비교하려면 카탈로그에 있는 제품 이름으로 물어봐 주세요."), meta


def chat(conn, list_id: UUID, principal: Principal, text: str, *, client_message_id: str | None = None,
         context: dict | None = None) -> dict:
    """견적 점검 질문 하나. `context`(저장 견적 비교)가 있으면 그 비교의 사실·시각 자료·가이드로 답하고, 같은 질문은 저장된 답을
    다시 쓴다(LLM을 부르지 않는다). `client_message_id`가 이미 처리된 것이면(재전송) 저장된 답을 그대로 돌려준다."""
    text = (text or "").strip()
    if not text:
        raise ValidationFailed("질문을 입력해 주세요.", field="text")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationFailed(f"질문이 너무 깁니다({MAX_TEXT_CHARS:,}자 이하).", field="text")
    revision, review = _stored_review(conn, list_id, principal)
    conversations = ConversationRepo(conn)
    conversation_id = revision["conversation_id"]

    if client_message_id:                                     # 같은 요청의 재전송 — 새 답을 만들지 않는다
        sent = conversations.find_by_client_message_id(conversation_id, client_message_id)
        if sent is not None:
            answer = conversations.assistant_after(conversation_id, sent["id"])
            if answer is not None:
                return _payload(answer["id"], answer["created_at"].isoformat(timespec="seconds"), answer["content"], answer["metadata"] or {})

    comparison = None
    comparison_id = None
    if context:
        comparison_id = str(context["comparison_id"])
        comparison = quote_comparison_service.get_comparison(conn, list_id, principal, comparison_id)
    normalized = quote_comparison_service.normalize_question(text)
    user_meta = {"comparison_id": comparison_id, "normalized_question": normalized} if comparison else {}

    if comparison:
        earlier = conversations.answer_for_question(conversation_id, comparison_id, normalized)
        if earlier is not None:                               # 같은 질문 — 기존 답·자료·가이드를 그대로(LLM 호출 없음)
            original = dict(earlier["metadata"] or {})
            meta = {**original, "answer_id": str(uuid.uuid4()), "duplicate_of": original.get("answer_id")}
            conversations.add_message(conversation_id, "user", text, client_message_id=client_message_id, metadata=user_meta)
            message_id = conversations.add_message(conversation_id, "assistant", earlier["content"], metadata=meta)
            return _payload(message_id, _now_iso(), earlier["content"], meta)

    stored_messages = conversations.messages(conversation_id)
    history = _pairs(stored_messages)
    loader = _catalog_loader()

    searched = None if comparison else _answer_search_consent(conn, stored_messages, text)
    if searched is not None:                                   # 직전에 검색 동의를 구했고 이번이 동의 — 이 턴에만 실시간 검색
        reply, meta = searched
        conversations.add_message(conversation_id, "user", text, client_message_id=client_message_id, metadata=user_meta)
        message_id = conversations.add_message(conversation_id, "assistant", reply, metadata=meta)
        return _payload(message_id, _now_iso(), reply, meta)

    calls = route(text, loader, review)
    fact = lambda n, a: run_fact(review, n, a, loader)       # noqa: E731
    extras = {"visuals": [], "guide_refs": []}
    if comparison:
        extras = quote_comparison_service.answer_extras(comparison, review, text, loader())
        # 저장 견적 비교에 대한 질문은 그 비교가 근거다 — 받은 견적만의 카탈로그 가격 비교·균형·추천 비교를 미리 싣지 않는다
        # (싣으면 "저장 견적과 얼마나 다르냐"는 질문에 카탈로그 가격 얘기로 답하는 일이 실측됐다). 호환·대안·부품 비교는 그대로.
        calls = [("saved_comparison", {"categories": extras["intent"]["slots"]}),
                 *[c for c in calls if c[0] not in ("overview", "prices", "balance", "compare")]]

        def fact(n, a):                                       # noqa: F811
            if n == "saved_comparison":
                return quote_comparison_service.facts_text(comparison, a.get("categories") or [])
            return run_fact(review, n, a, loader)

    from src.agent import quote_review_agent
    reply, evidence, via = None, [], "rules"
    pending_search = None
    if not comparison and calls and calls[0][0] in ("search_consent", "series_hint"):
        # 동의를 묻는 문장은 고정 문구(마커)가 있어야 다음 턴에 동의로 읽힌다 — 모델이 고쳐 쓰지 못하게 규칙 문장 그대로 답한다.
        reply, evidence = fact(*calls[0]), [EVIDENCE_LABEL[calls[0][0]]]
        if calls[0][0] == "search_consent":
            pending_search = {"slot": calls[0][1]["slot"], "product": calls[0][1]["product"]}
    elif quote_review_agent.available():
        try:
            turn = quote_review_agent.run_turn(review, history, text, calls, fact, user_text=text)
            reply, evidence, via = turn.reply, turn.evidence, "agent"
            log.info("quote review agent [%s]: %s", list_id, " | ".join(turn.trace) or "(도구 호출 없음)")
        except Exception as exc:  # noqa: BLE001 — 모델·네트워크 오류는 이번 턴만 규칙 경로로
            log.warning("quote review agent failed, falling back to rules: %s", exc)
    if reply is None:
        reply, evidence = rule_reply(review, text, loader, calls=calls, fact=fact)

    meta = {"answer_id": str(uuid.uuid4()), "evidence": evidence, "guide_refs": extras["guide_refs"], "visuals": extras["visuals"],
            "via": via, "display_target": "saved_comparison_explanation" if comparison else "chat"}
    if pending_search:
        meta["pending_search"] = pending_search
    if comparison:
        meta.update(comparison_id=comparison_id, normalized_question=normalized)
    conversations.add_message(conversation_id, "user", text, client_message_id=client_message_id, metadata=user_meta)
    message_id = conversations.add_message(conversation_id, "assistant", reply, metadata=meta)
    return _payload(message_id, _now_iso(), reply, meta)


def history(conn, list_id: UUID, principal: Principal) -> list[dict]:
    """저장한 견적 점검을 다시 열 때 복원할 대화(CHAT-08) — 시간순."""
    revision, _ = _stored_review(conn, list_id, principal)
    out = []
    for m in ConversationRepo(conn).messages(revision["conversation_id"]):
        meta = m.get("metadata") or {}
        row = {"id": str(m["id"]), "role": m["role"], "text": m["content"], "created_at": m["created_at"].isoformat(),
               "comparison_id": meta.get("comparison_id")}
        if m["role"] == "assistant":
            row.update(answer_id=meta.get("answer_id"), evidence=list(meta.get("evidence") or []),
                       guide_refs=list(meta.get("guide_refs") or []), visuals=list(meta.get("visuals") or []),
                       via=meta.get("via"), display_target=meta.get("display_target"), duplicate_of=meta.get("duplicate_of"))
        out.append(row)
    return out
