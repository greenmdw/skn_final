"""실시간 검색이 돌려준 자유 문장 값을 엔진이 읽는 표기로 맞춘다.

검색 결과의 값은 "일체형 수랭 CPU 쿨러", "DDR4 SDRAM", "Micro-ATX"처럼 문장이거나 표기가 제각각이다. 호환성 검사는
`"liquid" in cooling_type`, `board.mem_type == ram.mem_type`처럼 **카탈로그와 같은 표기**를 전제로 하므로 문장
그대로 넣으면 수랭을 공랭으로 검사하거나 같은 DDR4를 다르다고 판정한다(2026-10-05 점검에서 확인).

이미 있는 정규화(`owned_parts`의 `_cooler_specs`·`_board_form`·`_psu_form`·`_case_forms`와 소켓·DDR 정규식)를 그대로 쓴다 —
표기 규칙을 새로 만들지 않는다. 하나로 정해지지 않으면(소켓이 여러 개 등) None 을 돌려주고 호출자는 그 값을 버린다.
DB·LLM 없이 도는 순수 함수다."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from src.engine.owned_parts import _DDR, _SOCKET, _board_form, _case_forms, _cooler_specs, _psu_form


def _single(pattern: re.Pattern, text: Any, fmt: Callable[[re.Match], str]) -> str | None:
    found = {fmt(m) for m in pattern.finditer(str(text or ""))}
    return found.pop() if len(found) == 1 else None


def canonical_socket(text: Any) -> str | None:
    """"LGA 1700"·"am4" → "LGA1700"·"AM4". 소켓이 하나로 정해질 때만."""
    return _single(_SOCKET, text, lambda m: re.sub(r"[\s-]", "", m.group(1)).upper())


def canonical_ddr(text: Any) -> str | None:
    """"DDR4 SDRAM" → "DDR4". 세대가 하나로 정해질 때만("DDR4 / DDR5"는 None)."""
    return _single(_DDR, text, lambda m: f"DDR{m.group(1)}")


def canonical_cooling_type(text: Any) -> str | None:
    """공랭이면 "Air", 수랭(AIO)이면 "Liquid (AIO)" — 카탈로그·호환 검사가 쓰는 표기."""
    return _cooler_specs(str(text or ""))[0].get("cooling_type")


def canonical_board_form(text: Any) -> str | None:
    form, inferred = _board_form(str(text or ""))
    return None if inferred else form


def canonical_psu_form(text: Any) -> str | None:
    return _psu_form(str(text or ""))[0]


def canonical_case_forms(text: Any) -> list[str] | None:
    """지원하는 보드 크기 목록(["E-ATX", "ATX", "mATX", ...]). 읽히는 게 없으면 None."""
    return _case_forms(str(text or ""))[0]


_INTEL_SOCKET = re.compile(r"(?:LGA\s*)?(115x|\d{3,4}(?:-\d)?)", re.IGNORECASE)
_AMD_SOCKET = re.compile(r"\bAM([2-9])\b", re.IGNORECASE)
_INTEL_KNOWN = {"1851", "1700", "1200", "1151", "1150", "1155", "1156", "115x", "2066", "2011", "2011-3", "1366"}


def canonical_cooler_sockets(text: Any) -> str | None:
    """쿨러가 지원하는 소켓 목록 → 카탈로그 표기("LGA1851/1700/1200/115x, AM5/AM4"). 하나도 못 읽으면 None.

    검색 값은 "Intel 115x / 2011 / 1700, AMD AM4 / AM5"처럼 제조사 이름이 끼어 있고, 호환 검사의 소켓 파서는 이 모양을
    못 읽어 AM4 쿨러를 비호환으로 오판한다(실측). 알려진 소켓 번호만 골라 카탈로그와 같은 모양으로 다시 쓴다."""
    s = str(text or "")
    amd_part = re.split(r"\bAMD\b", s, maxsplit=1, flags=re.IGNORECASE)
    intel_text = amd_part[0] if len(amd_part) == 2 else re.sub(r"\bAM[2-9]\b", " ", s, flags=re.IGNORECASE)
    intel = {m.group(1).lower() for m in _INTEL_SOCKET.finditer(re.sub(r"\bAM[2-9]\b", " ", intel_text, flags=re.IGNORECASE))}
    intel = {x for x in intel if x in _INTEL_KNOWN}
    amd = sorted({m.group(1) for m in _AMD_SOCKET.finditer(s)}, reverse=True)
    parts = []
    if intel:
        # 최신 → 오래된 순, 115x 는 LGA 번호들 뒤에
        ordered = sorted((x for x in intel if x != "115x"), key=lambda x: -int(x.split("-")[0])) + (["115x"] if "115x" in intel else [])
        parts.append("LGA" + "/".join(ordered))
    if amd:
        parts.append("/".join(f"AM{v}" for v in amd))
    return ", ".join(parts) or None
