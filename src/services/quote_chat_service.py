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
from uuid import UUID

from src.auth.deps import Principal
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import ValidationFailed
from src.repo.user_repo import ConversationRepo
from src.services import quote_alternatives, quote_facts, quote_review_service as qrs, session_service

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
                  "compare": "우리 추천과 비교", "alternatives": "대안 조회", "compare_parts": "부품 비교"}
_PART_WORDS = ("스펙", "사양", "리뷰", "후기", "부품 비교", "다른 제품이랑", "이랑 비교", "와 비교", "과 비교", "랑 비교")


def match_slot(text: str) -> str | None:
    low = text.lower()
    for slot, words in _SLOT_WORDS.items():
        if any(w in low for w in words):
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
            # 질문에 모델명이 있는데 카탈로그에서 못 찾았다 — 다른 제품으로 슬쩍 바꿔 답하지 않도록, 적힌 이름 그대로 넘겨
            # "찾지 못했습니다"로 알리게 한다(견적 속 부품 자신의 이름 낱말은 뺀다).
            from src.engine.owned_parts import _is_model_token, _significant, _tokens
            own = set(_tokens(baseline or ""))
            leftover = [t for t in _significant(_tokens(text)) if _is_model_token(t) and len(t) >= 3 and t not in own]
            if leftover and any(w in low for w in ("비교", "대신", "말고", "바꾸면", "쓰면", "vs")):
                return [("compare_parts", {"slot": slot, "direction": None, "targets": leftover})]
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
    raise ValueError(f"unknown fact: {name}")


def rule_reply(review: dict, text: str, by_slot_loader) -> tuple[str, list[str]]:
    """에이전트 없이 — 질문에 맞는 사실 문장을 그대로 돌려준다(요약·판정 없음)."""
    calls = route(text, by_slot_loader, review)
    body = "\n\n".join(f"[{EVIDENCE_LABEL[n]}]\n{run_fact(review, n, a, by_slot_loader)}" for n, a in calls)
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


def chat(conn, list_id: UUID, principal: Principal, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValidationFailed("질문을 입력해 주세요.", field="text")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationFailed(f"질문이 너무 깁니다({MAX_TEXT_CHARS:,}자 이하).", field="text")
    revision, review = _stored_review(conn, list_id, principal)
    conversations = ConversationRepo(conn)
    history = _pairs(conversations.messages(revision["conversation_id"]))
    loader = _catalog_loader()

    from src.agent import quote_review_agent
    reply, evidence, via = None, [], "rules"
    if quote_review_agent.available():
        try:
            turn = quote_review_agent.run_turn(review, history, text, route(text, loader, review), lambda n, a: run_fact(review, n, a, loader),
                                           user_text=text)
            reply, evidence, via = turn.reply, turn.evidence, "agent"
            log.info("quote review agent [%s]: %s", list_id, " | ".join(turn.trace) or "(도구 호출 없음)")
        except Exception as exc:  # noqa: BLE001 — 모델·네트워크 오류는 이번 턴만 규칙 경로로
            log.warning("quote review agent failed, falling back to rules: %s", exc)
    if reply is None:
        reply, evidence = rule_reply(review, text, loader)

    conversations.add_message(revision["conversation_id"], "user", text)
    conversations.add_message(revision["conversation_id"], "assistant", reply)
    return {"reply": reply, "evidence": evidence, "via": via}


def history(conn, list_id: UUID, principal: Principal) -> list[dict]:
    """저장한 견적 점검을 다시 열 때 복원할 대화(CHAT-08) — 시간순."""
    revision, _ = _stored_review(conn, list_id, principal)
    return [{"id": str(m["id"]), "role": m["role"], "text": m["content"], "created_at": m["created_at"].isoformat()}
            for m in ConversationRepo(conn).messages(revision["conversation_id"])]
