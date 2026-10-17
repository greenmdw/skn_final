"""주변기기 견적 문장 해석 서비스 — 언어 모델 → 단어 규칙 물러나기, 같은 문장 재사용, 이어서 말하기.

경계(견적 입력 설계 4·10장)
- 칩 조작은 이 서비스를 부르지 않는다. 문장을 새로 보낼 때만 해석한다.
- 같은 문장(공백·대소문자 정리)과 규칙 버전은 모델 결과를 서버 안에 저장해 다시 부르지 않는다.
  단어 규칙의 결과는 싸므로 저장하지 않는다(모델이 다시 쓸 수 있게 되면 바로 모델로 읽어야 한다).
- 모델을 쓰지 못한 경우(꺼짐, 한도, 실패, 자리 없음)에도 해석은 나온다. 물러났다는 사실은 기록만 하고
  사용자에게 오류로 보여주지 않는다. `source` 로만 알린다.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from src.agent import peripheral_intent_agent
from src.engine import peripheral_chat, peripheral_intent
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_rules import interpretation_settings, load_peripheral_rules

log = logging.getLogger(__name__)

_cache: OrderedDict[str, Interpretation] = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str) -> Interpretation | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
        return hit


def _cache_put(key: str, value: Interpretation, limit: int) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > limit:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def interpret(text: str, previous: dict[str, Any] | None = None, kinds: list[str] | None = None) -> dict[str, Any]:
    """문장 한 줄을 읽어 이전 해석에 더하고, 종류별 풀이까지 낸다. 응답 모양은 schemas.PeripheralInterpretOut."""
    rules = load_peripheral_rules()
    settings = interpretation_settings(rules)
    limit = settings["max_chars"]
    truncated = len(text) > limit
    sentence = text[:limit]

    hint = peripheral_intent.kinds_all_order(kinds or [])
    key = f"{rules['rule_set_version']}|{','.join(hint)}|{peripheral_intent.normalize_text(sentence)}"
    new = _cache_get(key)
    source = "llm"
    if new is None:
        new, source = _read(sentence, key, rules, settings["cache_size"], hint)

    base = peripheral_intent.sanitize(previous, rules) if previous else None
    # 금액은 대화의 종류로 맞춘다. 규칙 해석도 이번 문장만 보므로 "30만원"처럼 종류 이름 없이 이어 말한 금액을 버렸다
    # (10/17 확인) — 모델 해석과 같이 이전 해석의 종류를 문맥으로 준다.
    new = peripheral_intent.reconcile_budget(new, sentence, [*(base.kinds if base else []), *hint], rules)
    new = _with_question(new, sentence, rules)

    merged = peripheral_intent.merge(base, new, rules)
    if kinds:      # 종류 카드로 고른 값 — 질문은 이번 문장의 것이므로 합치면서 지워지지 않게 되돌려 놓는다
        merged = peripheral_intent.merge(merged, peripheral_intent.sanitize({"kinds": kinds}, rules), rules)
        merged = merged.model_copy(update={"question": new.question})

    return {
        "interpretation": merged,
        "resolved": peripheral_intent.resolve(merged, rules),
        "needs_kind": not merged.kinds and not (merged.question and merged.question.type in _KINDLESS_QUESTIONS),
        "source": source,
        "truncated": truncated,
        # 채팅 한 턴(peripheral_chat_service)이 이번 문장만 따로 보려고 쓴다. 응답 모양에는 나가지 않는다.
        "turn_state": {"sentence": sentence, "new": new, "previous": base},
    }


# 종류를 몰라도 답할 수 있는 질문: 이때는 "어떤 기기를 찾으세요?" 카드를 띄우지 않는다.
_KINDLESS_QUESTIONS = ("capabilities", "term", "other")


def _with_question(new: Interpretation, sentence: str, rules: dict) -> Interpretation:
    """이번 문장이 질문이면 종류를 붙이고, 조건 말이 없는 질문이면 읽어 온 조건을 지운다(질문은 조건을 바꾸지 않는다).

    질문 여부는 단어 규칙(질문 말투 + 낱말)이 우선이고, 규칙이 못 가른 것만 언어 모델의 `question` 을 받는다. 모델이 질문이라 해도
    질문 말투가 문장에 없으면 조건 문장으로 둔다. 조건을 하나도 못 읽었고 질문 말투만 있으면 `other`(범위 밖 질문)다."""
    question = peripheral_chat.classify_question(sentence, rules)
    marked = peripheral_chat.has_question_marker(sentence, rules)
    if question is None and new.question is not None and marked:
        question = new.question
    if question is None and marked and peripheral_chat.read_nothing(new.model_copy(update={"question": None})):
        question = Question(type="other")
    if question is None:
        return new.model_copy(update={"question": None})
    if not question.kinds:
        question = question.model_copy(update={"kinds": peripheral_intent.kinds_in_text(sentence)})
    new = new.model_copy(update={"question": question})
    if question.type != "other" and not peripheral_chat.has_request_words(sentence, rules):
        return peripheral_chat.question_only(new)
    return new


def _read(sentence: str, key: str, rules: dict, cache_size: int, hint: list[str]) -> tuple[Interpretation, str]:
    if peripheral_intent_agent.available():
        try:
            result = peripheral_intent_agent.interpret(sentence, rules, hint)
        except Exception:  # noqa: BLE001 — 한도·자리 없음·형식 오류 모두 규칙으로 물러난다. 기록만 남긴다.
            log.warning("peripheral intent: 모델 해석 실패, 단어 규칙으로 물러남", exc_info=True)
        else:
            _cache_put(key, result, cache_size)
            return result, "llm"
    return peripheral_intent.interpret_by_words(sentence, rules, hint), "rules"
