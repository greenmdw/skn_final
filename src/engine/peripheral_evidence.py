"""체감 근거 표시 — 화면에 보여 줄 문구와 근거 문장(개발_확정사양.md 6.6, 7장).

`peripheral_feel` 이 계산한 `FeelDetail` 을 사람이 읽는 말로 바꾼다. 계산은 하지 않고 숫자도 바꾸지 않는다.
화면은 이 결과의 `text` 를 그대로 보여 주면 된다. 서버에 없는 값은 만들어 넣지 않고 빼서 숨긴다(사양 7장).

| 상태 | 문구 |
|---|---|
| 같은 조건의 글이 `same_condition_many` 편 이상 | "손이 큰 사용자 5명 중 4명이 좋게 평가했습니다" |
| 같은 조건의 글이 1~2편 | 사람 수와 "근거가 적습니다" |
| 다른 조건의 글만 있음 | "전체 12명 중 10명 · 손이 큰 사용자의 글은 아직 없습니다" |
| 평가가 갈림 | "의견이 갈립니다"와 양쪽 수 |
| 성향이 갈림 | "성향 평가가 갈립니다"와 쪽별 사람 수 |
| 성향이 취향과 다름 | "고르신 취향과 다릅니다" |
| 외부 리뷰만 있음 | "외부 리뷰 기준" |
| 근거 없음 | 그 속성은 낸 값이 없다. 속성이 전부 없으면 체감 블록 자체가 없다(None) |
"""
from __future__ import annotations

from typing import Any

from src.dto import FeelAttributeDetail, FeelDetail
from src.engine.peripheral_feel import feel_group_phrase
from src.engine.peripheral_intent import Interpretation, ResolvedKind
from src.engine.peripheral_rules import feel_attributes, feel_config, load_peripheral_rules

BASIS_TEXT = {"example": "예시 글 기준", "external_only": "외부 리뷰 기준", "community": None}
NO_EVIDENCE_NOTE = "스펙과 가격 기준 추천"


def _people(n: int) -> str:
    return f"{n}명"


def attribute_text(
    detail: FeelAttributeDetail, attr_def: dict, phrase: str | None, many: int,
) -> tuple[str, str] | None:
    """속성 하나의 (상태 코드, 문구). 보여 줄 근거가 없으면 None."""
    is_taste = detail.type == "taste"
    verb = "고르신 쪽이라고 했습니다" if is_taste else "좋게 평가했습니다"
    same_n = detail.same_good + detail.same_bad
    rest_n = detail.rest_good + detail.rest_bad
    total = same_n + rest_n

    if detail.mismatch:
        return "mismatch", "고르신 취향과 다릅니다"
    if detail.split and total:
        if is_taste:
            sides = attr_def.get("sides", {})
            parts = " · ".join(f"{sides.get(side, side)} {_people(n)}" for side, n in detail.side_counts.items() if n)
            return "split", f"성향 평가가 갈립니다 ({parts})" if parts else "성향 평가가 갈립니다"
        good, bad = detail.side_counts.get("good", 0), detail.side_counts.get("bad", 0)
        return "split", f"의견이 갈립니다 (좋음 {_people(good)} · 아쉬움 {_people(bad)})"
    if detail.state == "same_condition":
        if same_n >= many:
            return "same_condition", f"{phrase} {_people(same_n)} 중 {_people(detail.same_good)}이 {verb}"
        return "few_same_condition", f"{phrase} {_people(same_n)} 중 {_people(detail.same_good)} · 근거가 적습니다"
    if detail.state == "other_condition":
        good = detail.rest_good + detail.same_good
        if phrase:
            return "other_condition", f"전체 {_people(total)} 중 {_people(good)} · {phrase}의 글은 아직 없습니다"
        return "all_authors", f"전체 {_people(total)} 중 {_people(good)}이 {verb}"
    if detail.state == "external_only":
        return "external_only", BASIS_TEXT["external_only"]
    return None


def build_feel_block(
    detail: FeelDetail | None, interp: Interpretation, resolved: ResolvedKind | None, kind: str,
    rules: dict | None = None,
) -> dict[str, Any] | None:
    """제품 하나의 체감 근거 블록. 보여 줄 근거가 하나도 없으면 None(화면은 "스펙과 가격 기준 추천"만 쓴다)."""
    rules = rules or load_peripheral_rules()
    cfg = feel_config(rules)
    if detail is None or cfg is None:
        return None
    attrs = feel_attributes(kind, rules)
    rows: list[dict[str, Any]] = []
    for d in sorted(detail.attributes, key=lambda a: -a.alpha):
        entry = attrs.get(d.code, {})
        phrase = feel_group_phrase(entry.get("group", "none"), interp, resolved, rules)
        text = attribute_text(d, entry, phrase, cfg["same_condition_many"])
        if text is None:
            continue
        state, sentence = text
        rows.append({
            "code": d.code, "label": d.label, "type": d.type, "state": state, "text": sentence,
            "alpha": d.alpha, "split": d.split, "mismatch": d.mismatch,
            "good": d.same_good + d.rest_good, "bad": d.same_bad + d.rest_bad,   # 만족 막대용 인원수(같은 조건+그 밖)
            "quotes": [q.model_dump(mode="json") for q in d.quotes],
        })
    if not rows:
        return None
    return {
        "value": detail.value,
        "basis": detail.basis,
        "basis_text": BASIS_TEXT[detail.basis],
        "recent_authors": detail.recent_authors or None,        # 0 이면 표시하지 않는다(사양 6.6)
        "attributes": rows,
    }
