"""게임 요구 사양 표와 한 PC 구성을 비교한다 — 새 PC 결과 채팅과 받은 견적 점검 채팅이 같이 쓴다.

판정은 표의 요구 등급·용량과 구성의 값을 숫자로 견주는 것뿐이다(fps·프레임은 계산하지 않는다). 구성의 값은 호출하는 쪽이 만들어
`have` 로 준다 — 지금 구성이든, "이 GPU 로 바꾸면" 같은 가정한 구성이든 같은 함수가 같은 문장을 낸다.
DB·LLM 없이 도는 순수 함수다."""
from __future__ import annotations

import re
from typing import Any, Mapping

from src.engine.stage2_requirement import game_title_label, game_title_status, load_computer_rules, match_games

_LABEL = {"gpu": "GPU 성능 등급", "cpu": "CPU 성능 등급", "ram_gb": "RAM 용량(GB)", "vram_gb": "VRAM(GB)"}


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
                parts.append(f"{_LABEL[k]} 요구 {need[k]:g} / 그래픽카드를 넣지 않은 내장 그래픽 구성이라 비교하지 않음")
                skipped.append(_LABEL[k])
                continue
            h = have.get(k)
            if h is None:
                parts.append(f"{_LABEL[k]} 요구 {need[k]:g} / {subject} 정보 없음")
                continue
            ok = float(h) >= float(need[k])
            parts.append(f"{_LABEL[k]} 요구 {need[k]:g} / {subject} {float(h):g}" + ("" if ok else " ⚠ 미달"))
            if not ok:
                short.append(_LABEL[k])
        verdict = (f"요구 기준 미달: {', '.join(short)}" if short else
                   "비교한 요구 기준을 모두 채움(그래픽카드가 없는 내장 그래픽 구성이라 GPU·VRAM 기준은 비교하지 않음)" if skipped else
                   "표의 요구 기준을 모두 채움")
        src = "배급사 권장 사양 확인값" if status == "approved" else "권장 사양을 대략 옮긴 잠정값이라 공식 권장 사양 확인 필요"
        aliases = (rules["requirements"]["game_titles"].get(key) or {}).get("aliases") or []
        names = "/".join(dict.fromkeys(a for a in aliases if re.search(r"[가-힣]", a))) or game_title_label(key, rules)
        lines.append(f"{names}: {verdict} — " + " · ".join(parts) + f" ({src})")
    if unknown:
        lines.append(f"표에 없는 게임: {', '.join(unknown)}")
    lines.append("표의 기준은 권장 사양 수준이며 실제 프레임(fps)은 계산하지 않습니다.")
    return "\n".join(lines)
