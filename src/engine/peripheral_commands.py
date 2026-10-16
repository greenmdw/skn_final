"""주변기기 채팅의 결과 화면 명령 — "키보드는 빼줘", "무선 조건 취소", "마우스 다른 걸로", "3만원 더 싸게", "처음부터 다시".

문장 해석(peripheral_intent)은 이어 말하면 조건을 **더하기만** 한다. 그래서 결과를 본 뒤 하는 말(빼기·바꾸기·상대 금액·처음부터)이
"새로 읽어 낸 조건이 없어요"로 끝났다(10/16 실측 15개 대화). 이 모듈은 그런 문장을 낱말로 가르고(모델을 부르지 않는다),
뺄 것을 해석에서 지운다. 지금 1위가 필요한 명령(swap·cheaper·relative)의 금액·제품은 서비스가 추천을 다시 계산해 채운다.

명령으로 보는 조건:
- 명령 낱말이 문장 **끝 가까이**에 있다(명령문). "RGB 빼고 조용한 키보드"처럼 뒤에 다른 말이 이어지면 조건 문장이다.
- 브랜드 이름이 있으면 명령이 아니다 — "로지텍 빼줘"는 기피 브랜드다(해석이 읽는다).
- swap·cheaper 는 조건 낱말이 없을 때만이다 — "무선으로 바꿔줘"는 조건 문장이다.
DB·네트워크·언어 모델 호출 없음.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.engine import peripheral_intent as pi
from src.engine.peripheral_intent import Interpretation
from src.engine.peripheral_rules import chat_config, emphasis_cfg, load_peripheral_rules

_REMOVE_TAIL = 8          # 빼기 낱말 뒤에 이어도 되는 글자 수("빼 주세요", "취소해 줘")
_SWAP_TAIL = 10           # 바꾸기·더 싸게 낱말 뒤("다른 걸로 보여 주세요")
_RELATIVE = re.compile(
    r"(?:(\d+(?:[.,]\d+)?)\s*만\s*원?|(?<![\d만])만\s*원)\s*(?:만큼|정도|쯤)?\s*(?:만\s*)?(?:더\s*)?"
    r"(?:(싸게|저렴하게|낮춰|낮게|줄여|내려|깎|아껴|덜)|(올려|늘려|높여|더\s*써|더\s*쓸|비싸도|추가))")


@dataclass
class Command:
    type: str                                   # reset · remove · swap · cheaper · relative_budget
    kinds: list[str] = field(default_factory=list)   # 대상 종류(문장에 이름이 나왔거나 대화의 종류가 하나뿐일 때)
    delta: int = 0                              # relative_budget: 원(내리면 음수)


def _commands(rules: dict) -> dict:
    return chat_config(rules).get("commands") or {}


def _near_end(lowered: str, words, tail: int) -> bool:
    for word in words:
        at = lowered.rfind(word.lower())
        if at >= 0 and len(lowered) - (at + len(word)) <= tail:
            return True
    return False


def _names_brand(lowered: str, rules: dict) -> bool:
    return any(alias in lowered for aliases in emphasis_cfg(rules)["brands"].values() for alias in aliases)


def _reads_conditions(reading: Interpretation) -> bool:
    return bool(reading.purposes or reading.situations or reading.stated or reading.emphasis or reading.brand_like
                or reading.brand_avoid or reading.hand_size or reading.budget or reading.budget_min or reading.budget_total)


def detect(text: str, context_kinds: list[str], rules: dict | None = None) -> Command | None:
    """문장이 결과 화면 명령이면 그 명령. `context_kinds` 는 지금 대화의 종류(이전 해석·종류 카드)."""
    rules = rules or load_peripheral_rules()
    words = _commands(rules)
    if not words:
        return None
    lowered = pi.normalize_text(text)
    named = pi.kinds_in_text(text)
    target = named or (context_kinds if len(context_kinds) == 1 else [])
    if any(w.lower() in lowered for w in words.get("reset", ())):
        return Command("reset")
    if _names_brand(lowered, rules):
        return None
    match = _RELATIVE.search(lowered)
    if match:
        won = pi._won_of(match.group(1)) if match.group(1) else 10_000
        return Command("relative_budget", target, -won if match.group(2) else won)
    reading = pi.interpret_by_words(text, rules, context_kinds)
    if _near_end(lowered, words.get("remove", ()), _REMOVE_TAIL):
        return Command("remove", named)
    if _reads_conditions(reading):
        return None
    if _near_end(lowered, words.get("cheaper", ()), _SWAP_TAIL):
        return Command("cheaper", target)
    if _near_end(lowered, words.get("swap", ()), _SWAP_TAIL):
        return Command("swap", target)
    return None


def _without(per_kind: dict[str, list[str]], drop: dict[str, list[str]], kinds: list[str]) -> dict[str, list[str]]:
    out = {k: [v for v in items if v not in drop.get(k, [])] if k in kinds else list(items) for k, items in per_kind.items()}
    return {k: v for k, v in out.items() if v}


def remove(interp: Interpretation, text: str, named: list[str], rules: dict | None = None) -> Interpretation | None:
    """문장에서 읽은 조건을 해석에서 뺀다. 조건을 하나도 못 읽었으면 이름이 나온 품목을 뺀다. 뺄 것이 없으면 None.

    조건은 이름이 나온 품목에서만 뺀다(없으면 모든 품목에서). "예산"이라고만 하면 그 품목(없으면 전부)의 예산을 지운다."""
    rules = rules or load_peripheral_rules()
    scope = named or interp.kinds
    reading = pi.interpret_by_words(text, rules, scope)
    lowered = pi.normalize_text(text)
    budget_word = any(w in lowered for w in _commands(rules).get("budget_words", ()))
    changes: dict = {}
    if reading.stated:
        changes["stated"] = _without(interp.stated, reading.stated, scope)
    if reading.purposes:
        changes["purposes"] = [p for p in interp.purposes if p not in reading.purposes]
    if reading.situations:
        changes["situations"] = [s for s in interp.situations if s not in reading.situations]
    if reading.emphasis:
        changes["emphasis"] = _without(interp.emphasis, reading.emphasis, scope)
    if reading.hand_size:
        changes["hand_size"] = None
    if budget_word:
        changes["budget"] = {k: v for k, v in interp.budget.items() if named and k not in named}
        changes["budget_min"] = {k: v for k, v in interp.budget_min.items() if named and k not in named}
        if not named:
            changes["budget_total"] = None
    if not changes and named:
        kinds = [k for k in interp.kinds if k not in named]
        if not kinds or kinds == interp.kinds:
            return None
        keep = lambda d: {k: v for k, v in d.items() if k in kinds}  # noqa: E731
        changes = {"kinds": kinds, "stated": keep(interp.stated), "budget": keep(interp.budget), "budget_min": keep(interp.budget_min),
                   "emphasis": keep(interp.emphasis), "brand_like": keep(interp.brand_like), "brand_avoid": keep(interp.brand_avoid),
                   "exclude": keep(interp.exclude)}
    if not changes:
        return None
    out = interp.model_copy(update={**changes, "question": None})
    return None if out == interp.model_copy(update={"question": None}) else out


def reset(interp: Interpretation) -> Interpretation:
    """조건을 모두 지운다 — 고른 품목만 남긴다."""
    return Interpretation(kinds=list(interp.kinds))
