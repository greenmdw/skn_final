"""사용기 분석 결과를 예시 글 정답표와 맞춰 보는 평가 로직(순수 함수, DB·모델 호출 없음).

정답은 `docs/local/예시_사용기_작성_기획.md` 의 표에서 읽는다.
- 4장 "작성자별 목적과 상황" 표: 글쓴이의 손 크기, 종류별 목적·상황
- 5장 제품별 표: 글마다 성향 열("무게: 매우 가벼움 / 크기: 적당")

여기서 확인하는 것은 **구조화된 값**이다 — 손 크기, 목적·상황, 성향 쪽. "좋게 쓸 것"처럼 문장으로 적힌 평가 속성은
속성 코드와 1:1로 대응하지 않아 이 도구가 판정하지 않는다(추출된 속성 목록을 보고서에 함께 내어 사람이 읽는다).
성향 열의 값을 쪽으로 바꾸는 표(`TASTE`)는 마우스만 채웠다. 다른 종류는 손 크기·목적·상황만 본다.
정답표 값은 "글쓴이가 이렇게 쓰도록 기획한 것"이지 실제 정답이 아니다 — 불일치는 추출 오류일 수도, 글이 기획과 다르게
쓰였을 수도 있어 사람이 원문과 대조한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KIND_BY_PREFIX = {"A": "mouse", "B": "keyboard", "C": "monitor", "D": "speaker"}
HAND = {"작은 편": "small", "보통": "medium", "큰 편": "large"}
# 정답표 문구 → 설정의 목적·상황 코드가 안 맞는 말(설정 라벨의 앞부분으로 못 찾는 것)
_ALIASES = {"조용한 곳": "quiet_place", "좁은 책상": "small_desk"}

# 종류별 성향 열: 이름 → (속성 코드, [(문구에 들어 있는 낱말, 쪽 코드)…]). 위에서부터 먼저 맞는 것을 쓴다.
TASTE: dict[str, dict[str, tuple[str, list[tuple[str, str]]]]] = {
    "mouse": {
        "무게": ("weight_feel", [("가벼", "light"), ("묵직", "heavy"), ("무거", "heavy")]),
        "크기": ("size_feel", [("작", "small"), ("큼", "big"), ("큰", "big"), ("크", "big")]),
        "클릭 소리": ("click_sound", [("조용", "quiet"), ("또렷", "loud"), ("큼", "loud")]),
        "미끄러짐": ("glide", [("빠", "fast"), ("제동", "brake")]),
    },
}


@dataclass
class Gold:
    post_id: str
    author: str
    kind: str
    hand: str | None = None
    purposes: set[str] = field(default_factory=set)
    situations: set[str] = field(default_factory=set)
    unmapped: list[str] = field(default_factory=list)
    taste: dict[str, str] = field(default_factory=dict)      # 속성 코드 → 쪽 코드(중간값은 넣지 않는다)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _split_labels(text: str) -> list[str]:
    text = text.strip()
    if text in ("", "—", "-"):
        return []
    return [t.strip() for t in re.split(r"[,，]", text) if t.strip()]


def _match_label(token: str, labels: dict[str, str]) -> str | None:
    """정답표 문구가 설정 라벨과 같거나 라벨의 앞부분이면 그 코드. ("사무" → "사무·문서")"""
    for code, label in labels.items():
        if token == label or label.startswith(token):
            return code
    return None


def parse_taste(text: str, kind: str) -> dict[str, str]:
    table = TASTE.get(kind, {})
    out: dict[str, str] = {}
    for part in re.split(r"\s*/\s*", text.strip()):
        name, _, value = part.partition(":")
        spec = table.get(name.strip())
        if not spec or not value:
            continue
        code, words = spec
        value = value.strip()
        if value.startswith("적당") or value.startswith("보통"):
            continue
        for word, side in words:
            if word in value:
                out[code] = side
                break
    return out


def parse_gold(markdown: str, purposes_by_kind: dict[str, dict[str, str]], situations: dict[str, str]) -> dict[str, Gold]:
    """정답표 Markdown → {글 번호: Gold}. `purposes_by_kind`·`situations` 는 {코드: 라벨}."""
    author_rows: dict[str, dict[str, Any]] = {}
    gold: dict[str, Gold] = {}
    lines = markdown.splitlines()

    # 4장 목적·상황 표 — 머리글에 "손 크기 | 공통 상황" 이 있는 표
    for i, line in enumerate(lines):
        if line.startswith("|") and "손 크기" in line and "공통 상황" in line:
            header = _cells(line)
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                cells = _cells(row)
                if cells and re.fullmatch(r"P\d+", cells[0]):
                    author_rows[cells[0]] = dict(zip(header, cells))
            break

    for line in lines:
        m = re.match(r"^\|\s*([A-F]\d+-\d+)\s*\|\s*(P\d+)\s*\|", line)
        if not m:
            continue
        post_id, author = m.group(1), m.group(2)
        kind = KIND_BY_PREFIX.get(post_id[0])
        if kind is None:
            continue
        cells = _cells(line)
        g = Gold(post_id=post_id, author=author, kind=kind)
        row = author_rows.get(author, {})
        g.hand = HAND.get(row.get("손 크기", "").strip())
        kind_label = {"mouse": "마우스", "keyboard": "키보드", "monitor": "모니터", "speaker": "스피커"}[kind]
        tokens = _split_labels(row.get("공통 상황", "")) + _split_labels(row.get(kind_label, ""))
        for token in tokens:
            purpose = _match_label(token, purposes_by_kind.get(kind, {}))
            situation = _match_label(token, situations) or _ALIASES.get(token)
            if purpose:
                g.purposes.add(purpose)
            elif situation:
                g.situations.add(situation)
            else:
                g.unmapped.append(token)
        if len(cells) >= 8:
            g.taste = parse_taste(cells[7], kind)
        gold[post_id] = g
    return gold


@dataclass
class PostResult:
    post_id: str
    evidence: int
    hand: tuple[str | None, str | None] | None = None          # (정답, 추출) — 정답이 없으면 None
    purposes_missing: set[str] = field(default_factory=set)
    purposes_extra: set[str] = field(default_factory=set)
    purposes_other_kind: set[str] = field(default_factory=set)   # 추출됐지만 그 종류의 목적 목록에 없는 코드(예: 마우스 글의 docs)
    situations_missing: set[str] = field(default_factory=set)
    situations_extra: set[str] = field(default_factory=set)
    taste: dict[str, str] = field(default_factory=dict)       # 속성 코드 → match | conflict | mixed | missing
    attributes: dict[str, int] = field(default_factory=dict)  # 추출된 속성별 문장 수(other 포함)


def compare_post(gold: Gold, rows: list[dict[str, Any]], kind_purposes: set[str] | None = None) -> PostResult:
    """rows = 그 글에서 저장된 근거 행들({attribute, direction, side, hand_size, purposes, situations})."""
    res = PostResult(post_id=gold.post_id, evidence=len(rows))
    for r in rows:
        res.attributes[r["attribute"]] = res.attributes.get(r["attribute"], 0) + 1
    if not rows:
        res.taste = {a: "missing" for a in gold.taste}
        res.purposes_missing, res.situations_missing = set(gold.purposes), set(gold.situations)
        return res
    first = rows[0]
    if gold.hand is not None:
        res.hand = (gold.hand, first.get("hand_size"))
    got_p, got_s = set(first.get("purposes") or []), set(first.get("situations") or [])
    if kind_purposes is not None:
        res.purposes_other_kind = got_p - kind_purposes
        got_p = got_p & kind_purposes
    res.purposes_missing, res.purposes_extra = gold.purposes - got_p, got_p - gold.purposes
    res.situations_missing, res.situations_extra = gold.situations - got_s, got_s - gold.situations
    for attr, side in gold.taste.items():
        sides = {r["side"] for r in rows if r["attribute"] == attr and r.get("side")}
        if not sides:
            res.taste[attr] = "missing"
        elif sides == {side}:
            res.taste[attr] = "match"
        elif side in sides:
            res.taste[attr] = "mixed"
        else:
            res.taste[attr] = "conflict"
    return res


def summarize(results: list[PostResult]) -> dict[str, Any]:
    posts = len(results)
    hands = [r.hand for r in results if r.hand is not None]
    taste: dict[str, int] = {}
    for r in results:
        for v in r.taste.values():
            taste[v] = taste.get(v, 0) + 1
    return {
        "posts": posts,
        "posts_without_evidence": sum(1 for r in results if r.evidence == 0),
        "evidence_total": sum(r.evidence for r in results),
        "other_total": sum(r.attributes.get("other", 0) for r in results),
        "hand_checked": len(hands), "hand_match": sum(1 for g, e in hands if g == e),
        "purposes_missing": sum(len(r.purposes_missing) for r in results),
        "purposes_extra": sum(len(r.purposes_extra) for r in results),
        "purposes_other_kind": sum(len(r.purposes_other_kind) for r in results),
        "situations_missing": sum(len(r.situations_missing) for r in results),
        "situations_extra": sum(len(r.situations_extra) for r in results),
        "taste": taste,
    }


__all__ = ["Gold", "PostResult", "compare_post", "parse_gold", "parse_taste", "summarize"]
