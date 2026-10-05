"""사용자가 원하지만 카탈로그에 없는 부품(`wanted_parts`)을 추천의 호환성 제약으로만 쓴다.

DB에 없는 부품은 가격·성능 점수가 없어 추천 후보가 될 수 없다. 대신 실시간 검색으로 알아낸 플랫폼 값
(CPU·메인보드의 소켓, 메인보드·RAM의 메모리 규격)이 있으면, 신규 조립에서 나머지 부품이 그 플랫폼에 맞게
고르도록 대상 슬롯의 요구(`spec.targets`)에 걸어 준다. 업그레이드 모드가 유지 부품에 하는 것과 같은 규칙이다
(`owned_parts.constrain_targets` 재사용) — 판정 규칙을 새로 만들지 않는다.

- 호환성 규칙이 읽는 값은 소켓과 메모리 규격뿐이라, GPU·파워·케이스·쿨러·SSD를 원해도 추천은 달라지지 않는다.
- 값이 모호하면(소켓이 여러 개 나열됨 등) 걸지 않는다. 서로 모순되는 희망(CPU와 보드의 소켓이 다름)도 걸지 않는다.
- 그 조건을 만족하는 카탈로그 후보가 하나도 없으면 걸지 않는다 — 희망 사항 때문에 추천 자체가 실패하면 안 된다.
- 원한 부품이 속한 슬롯도 같은 플랫폼 값으로 맞춰 카탈로그에서 추천한다(그 부품을 견적에 넣지는 않는다). 맞추지 않으면
  그 슬롯의 기본 조건(예: RAM 기본 DDR5)이 방금 건 조건(보드 DDR4)과 어긋난다.
"""
from __future__ import annotations

from typing import Any

from src.engine.owned_parts import constrain_targets
from src.engine.part_values import canonical_ddr, canonical_socket
from src.engine.stage2_requirement import normalize_pc_slot


def platform_hints(wanted: Any) -> dict[str, dict[str, str]]:
    """wanted_parts → {슬롯: {socket?, mem_type?}}. 슬롯에 뜻이 있는 키만, 하나로 정해지는 값만 남긴다."""
    hints: dict[str, dict[str, str]] = {}
    if not isinstance(wanted, dict):
        return hints
    for raw_slot, item in wanted.items():
        slot = normalize_pc_slot(raw_slot) or str(raw_slot)
        fields = item.get("fields") if isinstance(item, dict) else None
        if not isinstance(fields, dict):
            continue
        out: dict[str, str] = {}
        if slot in ("CPU", "메인보드"):
            socket = canonical_socket(fields.get("socket"))
            if socket:
                out["socket"] = socket
        if slot in ("메인보드", "RAM"):
            ddr = canonical_ddr(fields.get("mem_type"))
            if ddr:
                out["mem_type"] = ddr
        if out:
            hints[slot] = out
    return hints


def describe_hints(hints: dict[str, dict[str, str]]) -> str:
    """사용자에게 "어떤 조건으로 나머지를 맞추는지" 알리는 한 줄. 걸 조건이 없으면 빈 문자열."""
    label = {"socket": "소켓", "mem_type": "메모리 규격"}
    return " · ".join(f"{slot} {label[key]} {value}" for slot, h in hints.items() for key, value in h.items())


def apply_wanted_constraints(spec, wanted: Any, by_slot: dict[str, list]) -> list[str]:
    """신규 조립의 `spec.targets`에 원한 미보유 부품의 플랫폼 제약을 건다. 적용하거나 건너뛴 이유를 문장으로 돌려준다."""
    hints = platform_hints(wanted)
    if not hints:
        return []
    notes: list[str] = []
    cpu, board, ram = dict(hints.get("CPU", {})), dict(hints.get("메인보드", {})), dict(hints.get("RAM", {}))

    if cpu.get("socket") and board.get("socket") and cpu["socket"] != board["socket"]:
        notes.append("원하는 CPU와 메인보드의 소켓이 서로 달라 소켓 조건은 걸지 않았습니다.")
        cpu.pop("socket"), board.pop("socket")
    if board.get("mem_type") and ram.get("mem_type") and board["mem_type"] != ram["mem_type"]:
        notes.append("원하는 메인보드와 RAM의 메모리 규격이 서로 달라 메모리 조건은 걸지 않았습니다.")
        board.pop("mem_type"), ram.pop("mem_type")

    def exists(slot: str, **want: str) -> bool:
        return any(all(c.specs.get(k) == v for k, v in want.items()) for c in by_slot.get(slot, []))

    # 각 희망이 제약하는 슬롯에 그 조건을 만족하는 카탈로그 후보가 있어야 건다.
    if cpu.get("socket") and "메인보드" in spec.targets and not exists("메인보드", socket=cpu["socket"]):
        notes.append(f"소켓 {cpu['socket']}에 맞는 메인보드가 카탈로그에 없어 소켓 조건은 걸지 않았습니다.")
        cpu.pop("socket")
    if board.get("socket") and "CPU" in spec.targets and not exists("CPU", socket=board["socket"]):
        notes.append(f"소켓 {board['socket']}에 맞는 CPU가 카탈로그에 없어 소켓 조건은 걸지 않았습니다.")
        board.pop("socket")
    if ram.get("mem_type") and "메인보드" in spec.targets and not exists("메인보드", mem_type=ram["mem_type"]):
        notes.append(f"{ram['mem_type']} 메인보드가 카탈로그에 없어 메모리 조건은 걸지 않았습니다.")
        ram.pop("mem_type")
    if board.get("mem_type") and "RAM" in spec.targets and not exists("RAM", mem_type=board["mem_type"]):
        notes.append(f"{board['mem_type']} RAM이 카탈로그에 없어 메모리 조건은 걸지 않았습니다.")
        board.pop("mem_type")
    # 메인보드 슬롯에는 CPU의 소켓과 RAM의 규격이 함께 걸린다 — 둘을 같이 만족하는 보드가 있어야 한다.
    if cpu.get("socket") and ram.get("mem_type") and not exists("메인보드", socket=cpu["socket"], mem_type=ram["mem_type"]):
        notes.append("원하는 CPU 소켓과 RAM 규격을 함께 만족하는 메인보드가 카탈로그에 없어 메모리 조건은 걸지 않았습니다.")
        ram.pop("mem_type")

    survivors = {slot: {"specs": h} for slot, h in (("CPU", cpu), ("메인보드", board), ("RAM", ram)) if h}
    if survivors:
        constrain_targets(spec, survivors)                       # 다른 슬롯(연결된 부품)을 그 플랫폼에 맞춘다
        # 원한 부품 자신의 슬롯도 같은 값으로 — 그 값을 만족하는 카탈로그 후보가 있을 때만
        if cpu.get("socket") and "CPU" in spec.targets and exists("CPU", socket=cpu["socket"]):
            spec.targets["CPU"]["socket_in"] = [cpu["socket"]]
        if ram.get("mem_type") and "RAM" in spec.targets and exists("RAM", mem_type=ram["mem_type"]):
            spec.targets["RAM"]["type"] = ram["mem_type"]
        if "메인보드" in spec.targets and board:
            socket, mem = board.get("socket"), board.get("mem_type")
            if socket and exists("메인보드", socket=socket) and not (mem and not exists("메인보드", socket=socket, mem_type=mem)):
                spec.targets["메인보드"]["socket_in"] = [socket]
            if mem and exists("메인보드", mem_type=mem) and not (socket and not exists("메인보드", socket=socket, mem_type=mem)):
                spec.targets["메인보드"]["mem_type"] = mem
        notes.append("원하는 미보유 부품 기준으로 나머지 부품의 호환 조건을 걸었습니다: "
                     + describe_hints({slot: v["specs"] for slot, v in survivors.items()}))
    return notes
