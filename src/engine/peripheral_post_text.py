"""커뮤니티 글 본문에서 서식을 걷어낸 "글자 본문" — 사용기 분석의 입력 텍스트.

커뮤니티 본문은 제한된 Markdown(소제목·굵게·목록·인용·표·링크)과 이미지 마커 `![설명](image:<id>)` 를 쓸 수 있다
(docs/local/개발요청_커뮤니티_본문_이미지_배치.md 3장). 분석은 서식이 아니라 글자만 봐야 한다.

- 이미지 마커는 줄째 지운다. 설명(alt)에 사용기 문장처럼 보이는 말을 넣어도 분석 근거가 되지 않는다.
- 서식이 없는 글(기존 일반 텍스트)은 **한 글자도 바뀌지 않는다(줄 맨 앞의 `#`·`-`·`1.`·`>` 같은 서식 기호가 없는 한).** 그래야 이미 분석한 글의 해시(`content_hash`)가
  그대로라 다시 분석하지 않는다. 그래서 줄 맨 앞의 서식 기호만 건드리고 공백·줄바꿈은 정리하지 않는다.
- 커뮤니티 `_excerpt` 의 정리 규칙과 같은 방향(기호·마커 제거)이지만 목적이 달라 따로 둔다. 원문 줄 순서는 유지한다.
"""
from __future__ import annotations

import re

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}[ \t]+")
_QUOTE = re.compile(r"^\s{0,3}>[ \t]?")
_BULLET = re.compile(r"^\s{0,3}[-*+][ \t]+")
_ORDERED = re.compile(r"^\s{0,3}\d{1,2}[.)][ \t]+")      # 1~2자리만: "2026. 10. 13" 같은 날짜 줄은 목록이 아니다
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|mailto:)[^)\s]*\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_STRIKE = re.compile(r"~~(.+?)~~")
_CODE = re.compile(r"`([^`\n]+)`")


def _table_cells(line: str) -> str:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return " ".join(c for c in cells if c)


def _inline(line: str) -> str:
    line = _IMAGE.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = _BOLD.sub(lambda m: m.group(1) or m.group(2), line)
    line = _STRIKE.sub(r"\1", line)
    return _CODE.sub(r"\1", line)


_EXAMPLE_NOTICE = re.compile(r"^\s*>?\s*가상 예시 사용기입니다")


def strip_example_notice(body: str | None) -> str:
    """예시 글 맨 앞의 면책 문구 줄("> 가상 예시 사용기입니다. 실제 구매자가 작성한 후기가 아닙니다.")을 뺀다. 예시 글에만 쓴다.

    독자에게 보이는 안내인데, 분석 입력에 두면 모델이 글을 "실제 후기가 아님"으로 보고 통째로 버린다."""
    if not body:
        return ""
    out: list[str] = []
    drop_blank = False
    for line in body.split("\n"):
        if _EXAMPLE_NOTICE.match(line):
            drop_blank = True
            continue
        if drop_blank and not line.strip():
            drop_blank = False
            continue
        drop_blank = False
        out.append(line)
    return "\n".join(out)


def plain_text(body: str | None) -> str:
    """서식을 걷어낸 글자 본문. 서식이 없는 글은 입력과 같다."""
    if not body:
        return ""
    lines = body.split("\n")
    out: list[str] = []
    skip_next_blank = False
    for line in lines:
        is_blank = not line.strip()
        if skip_next_blank and is_blank:
            skip_next_blank = False
            continue
        skip_next_blank = False
        if _IMAGE_LINE.match(line) or ("|" in line and _TABLE_SEP.match(line)):
            # 줄째 지운다. 앞뒤가 빈 줄이면 빈 줄이 두 겹이 되므로 한쪽을 같이 지운다.
            if out and not out[-1].strip():
                skip_next_blank = True
            continue
        if _TABLE_ROW.match(line):
            line = _table_cells(line)
        else:
            for pattern in (_HEADING, _QUOTE, _BULLET, _ORDERED):
                line = pattern.sub("", line, count=1)
        out.append(_inline(line))
    return "\n".join(out)


__all__ = ["plain_text", "strip_example_notice"]
