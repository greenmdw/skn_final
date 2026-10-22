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
        notes.extend(_follow_platform(spec, by_slot, hinted_socket=bool(cpu.get("socket") or board.get("socket")),
                                      hinted_mem=bool(ram.get("mem_type") or board.get("mem_type"))))
    return notes


def _socket_vendor(socket: str) -> str | None:
    text = str(socket).upper()
    if text.startswith("LGA"):
        return "intel"
    if text.startswith(("AM", "STR", "TR")):
        return "amd"
    return None


def _follow_platform(spec, by_slot: dict[str, list], *, hinted_socket: bool, hinted_mem: bool) -> list[str]:
    """한쪽 값(소켓 또는 메모리 규격)만 원했는데 기본 조건의 다른 쪽이 그 값의 보드와 어긋나 보드 후보가 0이 되면,
    다른 쪽을 카탈로그 보드가 실제로 쓰는 값으로 맞춘다(사전 필터가 Pass 0이면 추천이 후보 부족으로 끝나므로)."""
    target = spec.targets.get("메인보드")
    if not target or hinted_socket == hinted_mem:
        return []
    boards = by_slot.get("메인보드", [])
    forms, sockets, mem = target.get("form_in"), target.get("socket_in"), target.get("mem_type")

    def fits(c, *, sock, mem_type) -> bool:
        return ((not sock or c.specs.get("socket") in sock) and (not mem_type or c.specs.get("mem_type") == mem_type)
                and (not forms or c.specs.get("form_factor") in forms))

    if any(fits(c, sock=sockets, mem_type=mem) for c in boards):
        return []
    if hinted_socket:        # 소켓이 정해졌다 → 그 소켓 보드가 쓰는 메모리 규격이 하나면 그것으로
        kinds = {c.specs.get("mem_type") for c in boards if fits(c, sock=sockets, mem_type=None)} - {None}
        if len(kinds) != 1:
            return []
        (kind,) = kinds
        target["mem_type"] = kind
        if "RAM" in spec.targets:
            spec.targets["RAM"]["type"] = kind
        return [f"소켓에 맞는 메인보드가 모두 {kind}라 메모리 규격을 {kind}로 맞췄습니다."]
    sock_kinds = sorted({c.specs.get("socket") for c in boards if fits(c, sock=None, mem_type=mem)} - {None})
    # 기본 소켓 목록은 사용자가 고른 브랜드(brand_pref)에서 왔다 — 그 제조사를 벗어나는 소켓으로는 바꾸지 않는다.
    vendors = {_socket_vendor(s) for s in sockets or []}
    if vendors and None not in vendors:
        sock_kinds = [s for s in sock_kinds if _socket_vendor(s) in vendors]
    if not sock_kinds:
        return []
    target["socket_in"] = sock_kinds
    if "CPU" in spec.targets:
        spec.targets["CPU"]["socket_in"] = sock_kinds
    return [f"{mem} 메인보드의 소켓({', '.join(sock_kinds)})에 맞춰 소켓 조건을 정했습니다."]
