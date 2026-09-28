"""선언형 규칙 평가기 — 추천엔진 구현계획 §3.3 E11.

주변기기 하드 필터([3-A])·선호 적합도([3-B])·검증 쟁점([3-C])이 공유하는 최소 단위
연산이다. 조건 하나(pref = {key, op, value})를 후보 specs 와 비교해 Pass/Fail/Pending과
사람이 읽을 짧은 이유 문자열을 낸다.

**PC(stage3a_hardfilter.py)는 이 평가기로 옮기지 않는다** — 계획 §3.3에서 그 작업은
선택 과제 E14로 미뤄졌다. 지금은 주변기기 전용이다.

## 값이 없으면 Pending

`key`가 specs에 없거나 값이 None이면 Fail이 아니라 Pending이다 — 파싱 실패·컬럼 없음을
"조건 미달"로 단정하지 않는다(계획 §4 원칙 2). Fail은 값이 있고 조건을 실제로 어겼을 때만.

## 여러 조건의 채택 — Fail > Pending > Pass

`evaluate_all`은 stage3a_hardfilter._judge_computer와 같은 의미로 가장 나쁜 판정을
채택한다: 하나라도 Fail이면 Fail, Fail 없이 하나라도 Pending이면 Pending, 전부 Pass면 Pass.

## 중복 pref 제거

`config/peripherals.yaml`의 요구사양 룩업(E10)은 서로 다른 `when` 조건이 같은
(key, op, value) pref를 두 번 등재할 수 있다(예: `priority=quiet`와
`noise_sensitive=true`가 둘 다 `switch_clicky: false`를 낸다, peripheral_requirement.py
모듈 docstring 참고). 이 평가기가 그 중복을 한 번만 세지 않으면 점수가 두 배로 깎이거나
붙는다 — `dedupe_prefs`/`evaluate_all`이 (key, op, value) 동일 여부로 중복을 제거한다.
"""
from __future__ import annotations

from typing import Any

from src.dto import Verdict

OPS = ("min", "max", "equals", "member_of", "contains_any")

_ORDER = {"Fail": 0, "Pending": 1, "Pass": 2}


def _fmt(value: Any) -> str:
    """이유 문장에 값을 짧게 보여준다. 목록은 쉼표로 이어붙인다."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _pref_key(pref: dict[str, Any]) -> tuple[str, str, Any]:
    """(key, op, value) 동일 여부 판정용 해시 가능한 키. value가 list면 tuple로 바꾼다."""
    value = pref["value"]
    hashable_value = tuple(value) if isinstance(value, list) else value
    return (pref["key"], pref["op"], hashable_value)


def dedupe_prefs(prefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(key, op, value)가 같은 pref를 뒤에 나온 것부터 버리고 처음 순서를 유지한 채로 낸다."""
    seen: set[tuple[str, str, Any]] = set()
    out: list[dict[str, Any]] = []
    for pref in prefs:
        key = _pref_key(pref)
        if key in seen:
            continue
        seen.add(key)
        out.append(pref)
    return out


def evaluate(pref: dict[str, Any], specs: dict[str, Any]) -> tuple[Verdict, str]:
    """pref = {"key", "op", "value"} 하나를 specs와 비교한다.

    op: min(이상) / max(이하) / equals(일치) / member_of(목록 포함) /
    contains_any(문자열 부분일치, 대소문자 무시, value는 키워드 목록).
    """
    key, op, value = pref["key"], pref["op"], pref["value"]
    if op not in OPS:
        raise ValueError(f"알 수 없는 연산자: {op}")

    actual = specs.get(key)
    if key not in specs or actual is None:
        return "Pending", f"{key}: 값 없음"

    if op == "min":
        ok = actual >= value
        return ("Pass" if ok else "Fail"), f"{key} {_fmt(actual)} {'≥' if ok else '<'} {_fmt(value)}"
    if op == "max":
        ok = actual <= value
        return ("Pass" if ok else "Fail"), f"{key} {_fmt(actual)} {'≤' if ok else '>'} {_fmt(value)}"
    if op == "equals":
        ok = actual == value
        return ("Pass" if ok else "Fail"), f"{key} {_fmt(actual)} {'=' if ok else '≠'} {_fmt(value)}"
    if op == "member_of":
        ok = actual in value
        return ("Pass" if ok else "Fail"), f"{key} {_fmt(actual)} {'∈' if ok else '∉'} [{_fmt(value)}]"
    # contains_any — 원문 텍스트(actual)에 키워드 목록(value) 중 하나라도 부분일치하면 Pass.
    text = str(actual).lower()
    ok = any(str(v).lower() in text for v in value)
    return ("Pass" if ok else "Fail"), f"{key} '{actual}' {'포함' if ok else '미포함'}: [{_fmt(value)}]"


def evaluate_all(prefs: list[dict[str, Any]], specs: dict[str, Any]) -> tuple[Verdict, list[str]]:
    """여러 pref를 평가해 최악(Fail > Pending > Pass)을 채택하고, 그 수준의 이유만 모은다.

    (key, op, value) 중복은 한 번만 평가한다(모듈 docstring 참고). prefs가 비었으면
    판정할 조건이 없다는 뜻이라 Pass·이유 없음으로 낸다.
    """
    deduped = dedupe_prefs(prefs)
    if not deduped:
        return "Pass", []
    results = [evaluate(pref, specs) for pref in deduped]
    worst = min((v for v, _ in results), key=lambda v: _ORDER[v])
    reasons = [r for v, r in results if v == worst]
    return worst, reasons
