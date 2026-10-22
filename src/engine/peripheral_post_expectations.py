"""예시 글 정답표(`data/community_examples/expectations.yaml`)와 분석 결과(근거 문장)를 맞춰 보는 순수 함수(DB·모델 호출 없음).

`peripheral_post_eval.py`(손 크기·목적·상황·성향 쪽을 기획 문서 표에서 읽어 맞춰 보는 도구)와 겹치지 않게, 여기서는
- 글마다 반드시 나와야 하는 **평가 속성·성향**(`must`)의 적중률,
- 규칙 위반(사용기가 아닌 글의 근거, 작성자 조건을 숨긴 글의 조건, 6개월 미만 글의 내구성, 짐작 문장, 본문에 없는 문장)
을 본다. 불일치는 추출 오류일 수도, 글이 기획과 다르게 쓰였을 수도 있어 사람이 원문과 대조한다.

근거 행(row)은 dict 로, 키는 `post_id`(글 번호) · `attribute` · `direction` · `side` · `hand_size` · `purposes` ·
`situations` · `sentence` 이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

# 짐작·가정 문장(겪은 일이 아니라 "~라면 ~일 것 같다"): 근거가 되면 안 된다(기획 7장 "짐작 문장이 점수에 들어가지 않는가").
_SPECULATION = re.compile(
    r"(?:라면|이라면|다면|았다면|었다면|했다면).{0,40}?(?:수 있|것 같|듯|겠)"
    r"|(?:수도|수 있을) 있을 것 같|있을 것 같습니다|있을 듯")
HIDDEN_SUFFIX = "-4"


def load_expectations(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    data.setdefault("posts", {})
    data.setdefault("no_evidence", [])
    data.setdefault("durability_allowed", [])
    return data


def value_of(row: dict) -> str | None:
    """평가 속성은 방향(good/bad/mixed), 성향 속성은 쪽 코드."""
    return row.get("direction") or row.get("side")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple, set)) else [str(value)]


def group_by_post(rows: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(str(row["post_id"]), []).append(row)
    return out


@dataclass
class PostResult:
    post_id: str
    hits: list[tuple[str, str]] = field(default_factory=list)
    misses: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)     # must_not 으로 적은 값이 나온 것

    @property
    def total(self) -> int:
        return len(self.hits) + len(self.misses)


def check_post(post_id: str, rows: list[dict], must: dict | None, must_not: dict | None = None) -> PostResult:
    present: dict[str, set[str]] = {}
    for row in rows:
        value = value_of(row)
        if row.get("attribute") and value:
            present.setdefault(row["attribute"], set()).add(value)
    result = PostResult(post_id)
    for attribute, wanted in (must or {}).items():
        for value in _as_list(wanted):
            (result.hits if value in present.get(attribute, set()) else result.misses).append((attribute, value))
    for attribute, unwanted in (must_not or {}).items():
        for value in _as_list(unwanted):
            if value in present.get(attribute, set()):
                result.conflicts.append((attribute, value))
    return result


def coverage(results: Iterable[PostResult]) -> tuple[int, int]:
    hit = total = 0
    for r in results:
        hit += len(r.hits)
        total += r.total
    return hit, total


def check_posts(rows_by_post: dict[str, list[dict]], expected_posts: dict[str, dict], *,
                only: set[str] | None = None) -> list[PostResult]:
    """분석된 글(근거가 한 건이라도 있거나 `only`에 있는 글)만 비교한다. 아직 분석 안 된 글은 빠진다."""
    out = []
    for post_id, spec in expected_posts.items():
        if only is not None and post_id not in only:
            continue
        out.append(check_post(post_id, rows_by_post.get(post_id, []), spec.get("must"), spec.get("must_not")))
    return out


# ── 규칙 위반 ────────────────────────────────────────────────────────────────
def check_no_evidence(rows_by_post: dict[str, list[dict]], post_ids: Iterable[str]) -> list[tuple[str, int]]:
    """사용기가 아닌 글인데 근거가 나온 글: [(글 번호, 근거 수)]"""
    return [(pid, len(rows_by_post[pid])) for pid in post_ids if rows_by_post.get(pid)]


def check_conditions_hidden(rows_by_post: dict[str, list[dict]], suffix: str = HIDDEN_SUFFIX,
                            *, include_situations: bool = False) -> list[tuple[str, str]]:
    """작성자 조건을 밝히지 않는 글(번호가 `-4`)인데 손 크기·목적이 잡힌 글: [(글 번호, 이유)].

    기획은 -4 글에서도 "밤에는", "마이크에"처럼 표에 적힌 **문장 속 상황**은 그대로 쓴다고 했으므로 상황(`situations`)은
    기본으로 보지 않는다(`include_situations=True` 로만 본다). 손 크기와 목적은 글쓴이가 밝히지 않았으면 비어야 한다."""
    out = []
    for pid, rows in rows_by_post.items():
        if not pid.endswith(suffix):
            continue
        reasons = []
        if any(r.get("hand_size") for r in rows):
            reasons.append("hand_size")
        if any(r.get("purposes") for r in rows):
            reasons.append("purposes")
        if include_situations and any(r.get("situations") for r in rows):
            reasons.append("situations")
        if reasons:
            out.append((pid, ",".join(reasons)))
    return sorted(out)


def check_durability(rows_by_post: dict[str, list[dict]], allowed: Iterable[str]) -> list[str]:
    """6개월 이상 사용을 밝히지 않은 글인데 내구성 근거가 나온 글."""
    ok = set(allowed)
    return sorted(pid for pid, rows in rows_by_post.items()
                  if pid not in ok and any(r.get("attribute") == "durability" for r in rows))


def find_speculation(rows_by_post: dict[str, list[dict]]) -> list[tuple[str, str, str]]:
    """짐작·가정 문장으로 보이는 근거: [(글 번호, 속성, 문장)]. 휴리스틱이라 사람이 확인한다."""
    out = []
    for pid, rows in rows_by_post.items():
        for r in rows:
            sentence = str(r.get("sentence") or "")
            if _SPECULATION.search(sentence):
                out.append((pid, str(r.get("attribute")), sentence))
    return out


def check_sentences_in_body(rows_by_post: dict[str, list[dict]], bodies: dict[str, str],
                            plain: Callable[[str | None], str]) -> list[tuple[str, str]]:
    """근거 문장이 글자 본문에 그대로 있는지: 없는 것 [(글 번호, 문장)]"""
    def squash(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    out = []
    for pid, rows in rows_by_post.items():
        if pid not in bodies:
            continue
        body = squash(plain(bodies[pid]))
        for r in rows:
            if squash(str(r.get("sentence") or "")) not in body:
                out.append((pid, str(r.get("sentence"))))
    return out


def validate_expectations(data: dict[str, Any], attributes: dict[str, dict]) -> list[str]:
    """정답표 파일 자체의 오류: 모르는 속성 코드, 가질 수 없는 값. [메시지]"""
    problems = []
    for pid, spec in (data.get("posts") or {}).items():
        for section in ("must", "must_not"):
            for attribute, wanted in (spec.get(section) or {}).items():
                meta = attributes.get(attribute)
                if meta is None:
                    problems.append(f"{pid}.{section}: 모르는 속성 {attribute}")
                    continue
                allowed = set(meta.get("sides") or {}) if meta.get("type") == "taste" else {"good", "bad", "mixed"}
                for value in _as_list(wanted):
                    if value not in allowed:
                        problems.append(f"{pid}.{section}.{attribute}: 값 {value} 은(는) {sorted(allowed)} 중 하나여야 한다")
    return problems
