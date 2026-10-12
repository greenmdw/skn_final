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
from src.engine import peripheral_intent
from src.engine.peripheral_intent import Interpretation
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
    merged = peripheral_intent.merge(base, new)
    if kinds:      # 종류 카드로 고른 값
        merged = peripheral_intent.merge(merged, peripheral_intent.sanitize({"kinds": kinds}, rules))

    return {
        "interpretation": merged,
        "resolved": peripheral_intent.resolve(merged, rules),
        "needs_kind": not merged.kinds,
        "source": source,
        "truncated": truncated,
    }


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
