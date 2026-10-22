"""게임 요구 사양 표와 한 PC 구성을 비교한다 — 새 PC 결과 채팅과 받은 견적 점검 채팅이 같이 쓴다.

판정은 표의 요구 등급·용량과 구성의 값을 숫자로 견주는 것뿐이다(fps·프레임은 계산하지 않는다). 성능 등급(perf_tier) 숫자는
문장에 넣지 않는다 — 사용자가 뜻을 모르는 내부 눈금이라 "GPU 성능 등급 요구 3 / 지금 6"이 그대로 답에 옮겨졌다(10/22).
CPU·GPU 는 권장 이상/미달만, RAM·VRAM 은 사용자가 아는 GB 로 적는다. 구성의 값은 호출하는 쪽이 만들어
`have` 로 준다 — 지금 구성이든, "이 GPU 로 바꾸면" 같은 가정한 구성이든 같은 함수가 같은 문장을 낸다.
DB·LLM 없이 도는 순수 함수다."""
from __future__ import annotations

import re
from typing import Any, Mapping

from src.engine.stage2_requirement import game_title_label, game_title_status, load_computer_rules, match_games

_LABEL = {"gpu": "그래픽카드 성능", "cpu": "CPU 성능", "ram_gb": "RAM 용량", "vram_gb": "그래픽 메모리(VRAM)"}
_TIER_KEYS = ("gpu", "cpu")      # 값이 성능 등급이라 숫자를 말하지 않는 항목


def requirement_phrase(key: str, need: float, have: Any, subject: str = "지금") -> str:
    """한 요구 항목의 비교 문장 — 성능 등급은 숫자 없이 권장 이상/미달, 용량은 GB. 미달 표시(⚠)는 붙이지 않는다."""
    label = _LABEL[key]
    if key in _TIER_KEYS:
        if have is None:
            return f"{label} {subject} 정보 없음"
        return f"{label} {subject} 권장 이상" if float(have) >= float(need) else f"{label} {subject} 권장보다 낮음"
    if have is None:
        return f"{label} {subject} 정보 없음(권장 {float(need):g}GB)"
    return f"{label} {subject} {float(have):g}GB(권장 {float(need):g}GB)"


def have_from_specs(gpu: Mapping[str, Any] | None, cpu: Mapping[str, Any] | None, ram_specs: Mapping[str, Any] | None = None,
                    ram_qty: int = 1) -> dict[str, Any]:
    """부품 스펙 → 비교에 쓰는 값. 모르는 값은 None(표에서 "지금 정보 없음")."""
    gpu, cpu, ram_specs = gpu or {}, cpu or {}, ram_specs or {}
    ram_gb = (ram_specs.get("capacity_gb") or 0) * max(1, int(ram_qty or 1)) if ram_specs else None
    return {"gpu": gpu.get("perf_tier"), "cpu": cpu.get("perf_tier"), "ram_gb": ram_gb or None, "vram_gb": gpu.get("vram_gb")}


def check_games(game: str, have: Mapping[str, Any], *, subject: str = "지금", integrated_graphics: bool = False) -> str:
    """`game`(게임 이름이 든 글)의 요구 사양과 `have` 를 비교한 문장들. `subject` 는 값 앞의 말("지금"·"바꾼 뒤").
    `integrated_graphics` — 그래픽카드를 일부러 넣지 않은 내장 그래픽 구성이라 GPU·VRAM 기준은 비교하지 않는다."""
    rules = load_computer_rules()
    keys, tiers, unknown = match_games(game, rules)
    if not keys:
        return (f"'{game}'은(는) 게임 요구 사양 표에 없어 비교할 수 없습니다. "
                "해당 게임의 공식 권장 사양을 확인해 주세요.")
    lines = []
    for key, need in zip(keys, tiers):
        status = game_title_status(key, rules)["status"]
        parts, short, skipped = [], [], []
        for k in ("gpu", "cpu", "ram_gb", "vram_gb"):
            if need.get(k) is None:
                continue
            if k in ("gpu", "vram_gb") and integrated_graphics:
                parts.append(f"{_LABEL[k]}: 그래픽카드를 넣지 않은 내장 그래픽 구성이라 비교하지 않음")
                skipped.append(_LABEL[k])
                continue
            h = have.get(k)
            ok = h is None or float(h) >= float(need[k])
            parts.append(requirement_phrase(k, need[k], h, subject) + ("" if ok else " ⚠ 미달"))
            if not ok:
                short.append(_LABEL[k])
        verdict = (f"권장 사양 미달: {', '.join(short)}" if short else
                   "비교한 권장 사양을 모두 채움(그래픽카드가 없는 내장 그래픽 구성이라 그래픽카드·VRAM 기준은 비교하지 않음)" if skipped else
                   "표의 권장 사양을 모두 채움")
        src = "배급사 권장 사양 확인값" if status == "approved" else "권장 사양을 대략 옮긴 잠정값이라 공식 권장 사양 확인 필요"
        aliases = (rules["requirements"]["game_titles"].get(key) or {}).get("aliases") or []
        names = "/".join(dict.fromkeys(a for a in aliases if re.search(r"[가-힣]", a))) or game_title_label(key, rules)
        lines.append(f"{names}: {verdict} — " + " · ".join(parts) + f" ({src})")
    if unknown:
        lines.append(f"표에 없는 게임: {', '.join(unknown)}")
    lines.append("표의 기준은 권장 사양 수준이며 실제 프레임(fps)은 계산하지 않습니다.")
    return "\n".join(lines)


_SLOT_OF = {"gpu": "GPU", "cpu": "CPU", "ram_gb": "RAM", "vram_gb": "GPU"}


def requirement_status(game: str, have: Mapping[str, Any]) -> list[dict[str, Any]]:
    """게임마다 요구 기준 항목의 충족 여부 — 교체 추천이 어느 부품을 바꿔야 하는지 읽는 구조화된 결과.
    [{game, key, slot, need, have, state('met'|'unmet'|'unknown')}]. 표에 없는 게임은 빈 목록이다. 판정 기준은 `check_games` 와 같다."""
    rules = load_computer_rules()
    keys, tiers, _unknown = match_games(game, rules)
    out: list[dict[str, Any]] = []
    for key, need in zip(keys, tiers):
        label = game_title_label(key, rules)
        for k in ("gpu", "cpu", "ram_gb", "vram_gb"):
            if need.get(k) is None:
                continue
            h = have.get(k)
            state = "unknown" if h is None else "met" if float(h) >= float(need[k]) else "unmet"
            out.append({"game": label, "key": k, "slot": _SLOT_OF[k], "label": _LABEL[k], "need": need[k], "have": h, "state": state})
    return out
