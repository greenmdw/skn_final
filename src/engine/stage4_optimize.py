"""[4] 세트 최적화 (컴퓨터).

슬롯별 top-N 조합을 완전탐색 + 가지치기(link_rules, 예산) → 완성 세트 1개.
재탐색 시 exclude 된 (slot, product_key) 는 후보에서 제외하고 재최적화한다.
"""
from __future__ import annotations

import math
from itertools import product

from src.dto import BuildItem, BuildResult, Candidate, RankResult, RequirementSpec
from src.engine import LogFn
from src.engine.compat_parse import (cpu_supported, gpu_connector_fit, gpu_power_count_fit, parse_module_count, parse_pcie_gens,
                                     parse_size_list, psu_fits_case, slots_needed, socket_supported)
from src.engine.stage2_requirement import load_computer_rules

# Requirements/candidate pools this size or smaller get an exact branch-and-bound
# search over every valid candidate. Above it, only the top-N ranked candidates per
# requirement enter the search — CONTRACTS ALGORITHM step 4 requires that this
# truncation be reported as a bounded-search approximation, never silently claimed
# as a global optimum.
BASKET_SEARCH_TOP_N = 8

# Node budget for the widened PC search (all hard-filter survivors, not just top-N). Keeps a
# pathological catalog from stalling a request; hitting it is reported as counts["capped"].
WIDEN_NODE_CAP = 150_000

# v3 (develop `da79839`, DEVELOP_DB_TRANSITION.md "Candidate edits and confirmation"):
# engine.recommendation_candidate.qty is a purchase pack count, integer 1-99. Applies to
# any to_purchase qty this module produces or re-validates — not a domain-required-qty
# cap (owned coverage / a requirement's own required_qty are unbounded).
PURCHASE_QTY_MIN, PURCHASE_QTY_MAX = 1, 99


def _purchase_qty_out_of_range(qty: float) -> bool:
    return not math.isfinite(qty) or not float(qty).is_integer() or not (PURCHASE_QTY_MIN <= qty <= PURCHASE_QTY_MAX)


def _pack_count_for(need: float, unit_qty: float, req_unit_code: str) -> int | None:
    """P4 review R4: two different requirement unit conventions coexist (P2/P4
    contract) and must not be collapsed into one formula:

    - `req_unit_code == "pack"`: required_qty already counts purchase packs (e.g.
      "2 packs of diapers") — the conversion factor is 1 (OP04/OP08 fixtures fix
      this: qty stays == the remaining pack count, never divided by unit_qty).
      `unit_qty` there is a pure content-count statistic (how many individual
      diapers per pack), not a purchase divisor.
    - anything else (e.g. "each"): required_qty counts base units, so the purchase
      pack count is ceil(need/unit_qty) for THAT candidate's pack size.

    Returns None (candidate excluded, not silently clamped) when the inputs are
    unusable or the resulting count falls outside the develop 1-99 pack range (P4
    review R2 — applies uniformly regardless of timing, including soon/later)."""
    if not math.isfinite(need) or need <= 0:
        return None
    if req_unit_code == "pack":
        count = math.ceil(need)
    else:
        if not math.isfinite(unit_qty) or unit_qty <= 0:
            return None
        count = math.ceil(need / unit_qty)
    return count if PURCHASE_QTY_MIN <= count <= PURCHASE_QTY_MAX else None


def _ranked(rank: RankResult, slot: str) -> list[Candidate]:
    return [Candidate.model_validate(c) for c in rank.slots.get(slot, {}).get("ranked", [])]


def _full_pool(rank: RankResult, slot: str) -> list[Candidate]:
    """Every hard-filter survivor for ``slot`` (stage3b's "pool"); top-N only if absent."""
    info = rank.slots.get(slot, {})
    return [Candidate.model_validate(c) for c in (info.get("pool") or info.get("ranked", []))]


def _compat_filter(pool: list[Candidate], key: str, wanted: str) -> list[Candidate]:
    """호환 속성(key)이 wanted와 같은 후보만 남긴다. 속성이 없는 후보는 "정보 없음"이라
    통과시킨다(호환 안 됨으로 단정하지 않는다) — override 표가 일부 부품만 채워져 있어서다.
    남는 게 없으면 필터를 걸지 않은 원래 풀로 되돌린다(빈 슬롯보다는 낫다)."""
    kept = [c for c in pool if c.specs.get(key) in (None, wanted)]
    return kept or pool


def _apply_mainboard_compat(pools: dict[str, list[Candidate]], mb: Candidate) -> None:
    """실제로 확정된 메인보드 mb를 호환 기준점으로 삼아 CPU(소켓)·RAM(메모리 타입)·
    케이스(폼팩터) 풀을 좁힌다(요청 R1).

    호출자는 반드시 "이번 빌드에서 실제로 선택될" 후보를 넘겨야 한다 — 랭킹 1위가
    아니라 예산에 맞는 실제 픽이어야 하는 이유는 build_computer의 버그 설명 참고."""
    rules = load_computer_rules()["verification"]
    socket = mb.specs.get(rules["socket"]["mainboard_spec"])
    mem_type = mb.specs.get(rules["memory"]["mainboard_spec"])
    form = mb.specs.get(rules["motherboard_case"]["mainboard_spec"])
    if socket and "CPU" in pools:
        pools["CPU"] = _compat_filter(pools["CPU"], rules["socket"]["cpu_spec"], socket)
    if mem_type and "RAM" in pools:
        pools["RAM"] = _compat_filter(pools["RAM"], rules["memory"]["ram_spec"], mem_type)
    if form and "케이스" in pools:
        pools["케이스"] = [c for c in pools["케이스"]
                          if form in (c.specs.get(rules["motherboard_case"]["case_spec"]) or [form])] or pools["케이스"]


def _pick_cheapest_fit(pool: list[Candidate], budget: int, running: int) -> Candidate:
    """풀의 랭킹 1위를 기본으로, 예산 안에 들어오는 첫 후보로 대체한다(공용 그리디 픽)."""
    cand = pool[0]
    for c in pool:
        if budget == 0 or running + c.price <= budget:
            return c
    return cand


def _is_definite_mismatch(pool: list[Candidate], key: str, wanted: str) -> bool:
    """wanted가 있고, pool 안에 key값이 알려진 후보가 하나 이상 있는데 전부 wanted와
    다르면 True(확정 비호환). key값을 아는 후보가 하나도 없으면 판단 보류(False) —
    정보 없음을 비호환으로 단정하지 않는다는 _compat_filter와 같은 원칙."""
    if not wanted:
        return False
    known = [c for c in pool if c.specs.get(key)]
    return bool(known) and all(c.specs.get(key) != wanted for c in known)


def _pick_mainboard(pools: dict[str, list[Candidate]], budget: int, running: int) -> Candidate:
    """예산에 맞는 후보 중, CPU 풀([3-B] 랭킹으로 이미 top-N만 남은 상태)과 확실히
    소켓이 안 맞는 보드는 건너뛰고 고른다.

    stage3b_rank.py가 카테고리별로 top-N만 남긴 뒤에 이 함수가 호출되기 때문에,
    "이 보드에 맞는 CPU가 원래는 있지만 랭킹 상위 N개에는 안 들었다" 같은 경우까지
    다 구해주진 못한다 — 그런 보드는 여기서도 건너뛴다(둘 다 top-N 안에서 서로 맞는
    조합을 찾는 것까지가 이 근사의 한계). 맞는 보드가 하나도 없으면(전부 확정
    비호환이거나 정보 없음) 예산에 맞는 첫 후보로 되돌아간다 — 빈 슬롯보다는 낫다."""
    mb_pool = pools.get("메인보드") or []
    cpu_pool = pools.get("CPU") or []
    socket_rule = load_computer_rules()["verification"]["socket"]
    fallback: Candidate | None = None
    for c in mb_pool:
        if not (budget == 0 or running + c.price <= budget):
            continue
        if fallback is None:
            fallback = c
        if _is_definite_mismatch(cpu_pool, socket_rule["cpu_spec"], c.specs.get(socket_rule["mainboard_spec"])):
            continue
        return c
    return fallback if fallback is not None else mb_pool[0]


def _pick_with_limit(pool: list[Candidate], budget: int, running: int, *,
                     key: str, limit: float | None, max_allowed: bool) -> Candidate:
    """예산에 맞는 후보 중, limit(있으면)을 확실히 어기는 건 건너뛰고 고른다.

    max_allowed=True: 후보의 key값이 limit 이하여야 통과(예: GPU 길이 <= 케이스
    허용 길이). max_allowed=False: key값이 limit 이상이어야 통과(예: PSU 용량 >=
    필요 전력). 둘 중 하나라도 값을 모르면 위반으로 단정하지 않는다(그냥 통과)."""
    fallback: Candidate | None = None
    for c in pool:
        if not (budget == 0 or running + c.price <= budget):
            continue
        if fallback is None:
            fallback = c
        value = c.specs.get(key)
        if limit is not None and value is not None:
            violates = (value > limit) if max_allowed else (value < limit)
            if violates:
                continue
        return c
    return fallback if fallback is not None else pool[0]


def _pick_cooler(pools: dict[str, list[Candidate]], budget: int, running: int,
                 max_height_mm: float | None, cpu_socket: str | None) -> Candidate:
    """케이스 허용 높이 + CPU 소켓, 두 축 다 확실히 어기지 않는 쿨러를 고른다.
    쿨러의 supported_socket은 "LGA1851/1700/1200/115x, AM5/AM4"처럼 여러 소켓을 약어로 한
    문자열에 나열해서 compat_parse.socket_supported 로 풀어서 비교한다(부분 문자열 포함은 오판한다)."""
    pool = pools.get("쿨러") or []
    rules = load_computer_rules()["verification"]
    fallback: Candidate | None = None
    for c in pool:
        if not (budget == 0 or running + c.price <= budget):
            continue
        if fallback is None:
            fallback = c
        height = c.specs.get(rules["cooler_height"]["cooler_spec"])
        if max_height_mm is not None and height is not None and height > max_height_mm:
            continue
        supported = c.specs.get(rules["cooler_socket"]["cooler_spec"])
        if socket_supported(cpu_socket, supported) is False:
            continue
        return c
    return fallback if fallback is not None else pool[0]


# 메인보드 크기 위계. 케이스가 "ATX" 를 지원한다고 적어 두면 그보다 작은 mATX·ITX 보드도 들어간다
# (이전엔 정확 일치만 봐서 mATX 보드 22개가 ATX 케이스 23개와 "비호환"으로 판정됐다).
_FORM_RANK = {"itx": 1, "miniitx": 1, "matx": 2, "microatx": 2, "atx": 3, "eatx": 4, "extendedatx": 4}


def _form_rank(text) -> int | None:
    key = "".join(ch for ch in str(text).lower() if ch.isalnum())
    return _FORM_RANK.get(key)


def _form_fits(board_form, case_forms) -> bool | None:
    """보드가 케이스에 들어가는가. 표기를 못 읽으면 None(판정 보류) — 비호환으로 단정하지 않는다."""
    board = _form_rank(board_form)
    listed = case_forms if isinstance(case_forms, (list, tuple)) else str(case_forms).replace(",", "/").split("/")
    ranks = [r for r in (_form_rank(f) for f in listed) if r is not None]
    if board is None or not ranks:
        return None
    return board <= max(ranks)


def _pc_known_failures(chosen: dict[str, Candidate], spec: RequirementSpec, rules: dict) -> set[str]:
    """선택된 부품 사이에서 *확정된* 비호환만 돌려준다. 모르는 스펙은 보류한다."""
    owned = spec.owned

    def value(slot: str, key: str):
        candidate = chosen.get(slot)
        if candidate is not None:
            return candidate.specs.get(key)
        # 업그레이드: 견적에 안 넣는(사용자가 그대로 쓰는) 부품의 스펙. 모르면 None → 판정 보류.
        return ((owned.get(slot) or {}).get("specs") or {}).get(key)

    failures: set[str] = set()
    socket = rules["socket"]
    cpu_socket = value("CPU", socket["cpu_spec"])
    board_socket = value("메인보드", socket["mainboard_spec"])
    if cpu_socket and board_socket and cpu_socket != board_socket:
        failures.add("socket")

    memory = rules["memory"]
    ram_type = value("RAM", memory["ram_spec"])
    board_memory = value("메인보드", memory["mainboard_spec"])
    if ram_type and board_memory and ram_type != board_memory:
        failures.add("memory")

    board_case = rules["motherboard_case"]
    board_form = value("메인보드", board_case["mainboard_spec"])
    case_forms = value("케이스", board_case["case_spec"])
    if board_form and case_forms and _form_fits(board_form, case_forms) is False:
        failures.add("motherboard_case")

    gpu_length = rules["gpu_length"]
    gpu_mm = value("GPU", gpu_length["gpu_spec"])
    case_gpu_mm = value("케이스", gpu_length["case_spec"])
    if gpu_mm is not None and case_gpu_mm is not None and gpu_mm > case_gpu_mm:
        failures.add("gpu_len")

    cooler_height = rules["cooler_height"]
    cooler_mm = value("쿨러", cooler_height["cooler_spec"])
    case_cooler_mm = value("케이스", cooler_height["case_spec"])
    if cooler_mm is not None and case_cooler_mm is not None and cooler_mm > case_cooler_mm:
        failures.add("cooler_height")

    cooler_socket = rules["cooler_socket"]
    supported = value("쿨러", cooler_socket["cooler_spec"])
    if socket_supported(cpu_socket, supported) is False:
        failures.add("cooler_socket")

    # BIOS 축: CPU 이름의 세대·계열이 메인보드의 지원 계열 목록에 없으면 확정된 비호환이다(예: Ryzen 2000 번대를
    # A520/B550 보드에). 목록에 있어도 보드가 출고 때 그 BIOS 를 싣는지는 데이터에 없다 — 그건 보드 사용 가이드가 맡는다.
    # 소켓이 이미 안 맞으면 계열도 안 맞기 마련이라 같은 원인을 두 번 세지 않는다.
    if "socket" not in failures and \
            cpu_supported(_cpu_name(chosen, spec), value("메인보드", rules["bios"]["mainboard_spec"])) is False:
        failures.add("bios")

    # 파워 폼팩터: ATX 파워는 SFX 전용 케이스에 물리적으로 안 들어간다(더 작은 파워를 큰 케이스에 넣는 건 어댑터가 있으면 된다).
    psu_case = rules["psu_form"]
    if psu_fits_case(value("파워", psu_case["psu_spec"]), value("케이스", psu_case["case_spec"])) == "fail":
        failures.add("psu_form")

    power = rules["power"]
    cpu_w = value("CPU", power.get("cpu_peak_spec", "")) or value("CPU", power["cpu_spec"])   # 최대 전력(PL2/PPT)이 있으면 그것으로
    gpu_w = value("GPU", power["gpu_spec"])
    psu_w = value("파워", power["psu_spec"])
    required_w = ((cpu_w + gpu_w) / power["psu_capacity_factor"]
                  if cpu_w is not None and gpu_w is not None
                  else spec.targets.get("파워", {}).get("wattage_min"))
    if psu_w is not None and required_w is not None and psu_w < required_w:
        failures.add("power")
    # 업그레이드: GPU 와 파워 중 *하나만* 견적에 들어가면 다른 쪽은 유지 부품이다. 유지하는 CPU 전력을 모르면
    # 위 합산 검사가 안 돌아서, 제조사 권장 파워(GPU 스펙에 있음)를 유지 파워 용량과 직접 비교한다.
    if power.get("use_gpu_recommended_psu", True) and (("GPU" in chosen) != ("파워" in chosen)):
        recommended = value("GPU", "recommended_psu_w")
        if recommended and psu_w is not None and psu_w < recommended:
            failures.add("power")

    # ── 아래는 원본 엑셀의 확장 열(0018)이 채워진 만큼만 판정한다. 값이 없으면 보류(통과로도 실패로도 세지 않는다).
    gc = rules["gpu_connector"]
    count_state, _ = gpu_power_count_fit(value("GPU", gc["gpu_spec"]), value("GPU", gc["aux_spec"]),
                                        value("파워", gc["psu_pcie_count_spec"]), value("파워", gc["psu_16_count_spec"]))
    if count_state == "fail":
        failures.add("gpu_connector")

    r = rules["psu_length"]
    length, limit = value("파워", r["psu_spec"]), value("케이스", r["case_spec"])
    if length is not None and limit is not None and length > limit:
        failures.add("psu_length")

    r = rules["gpu_slots"]
    need, have = slots_needed(value("GPU", r["gpu_spec"])), value("케이스", r["case_spec"])
    if need is not None and have is not None and need > have:
        failures.add("gpu_slots")

    r = rules["radiator"]
    radiator = value("쿨러", r["cooler_spec"])
    if radiator is not None and "liquid" in str(value("쿨러", "cooling_type") or "").lower():
        sizes = {n for key in r["case_specs"] for n in parse_size_list(value("케이스", key))}
        if sizes and int(radiator) not in sizes:
            failures.add("radiator")

    r = rules["ram_slots"]
    modules, dimm = parse_module_count(value("RAM", r["ram_module_spec"])), value("메인보드", r["board_slots_spec"])
    capacity, max_capacity = value("RAM", r["ram_capacity_spec"]), value("메인보드", r["board_max_capacity_spec"])
    if (modules is not None and dimm is not None and modules > dimm) or \
            (capacity is not None and max_capacity is not None and capacity > max_capacity):
        failures.add("ram_slots")

    r = rules["m2"]
    ssd_form = str(value("저장장치", r["ssd_form_spec"]) or "")
    if "M.2" in ssd_form and "SATA" not in ssd_form.upper():
        m2_slots = value("메인보드", r["board_slots_spec"])
        if m2_slots is not None and m2_slots == 0:
            failures.add("m2")
    return failures


class _NodeCap(Exception):
    """Raised inside a widened search when it exceeds its node budget."""


def _max_score_search(
    pools: dict[str, list[Candidate]], order: list[str], slots: list[str], budget: int,
    spec: RequirementSpec, rules: dict, counts: dict[str, int], node_cap: int | None = None,
) -> dict[str, Candidate]:
    """Exact branch-and-bound over ``pools``: best total score among compatible sets within
    budget. With ``node_cap`` the search stops early (keeping the best set found so far)."""
    min_price = [0] * (len(order) + 1)
    max_score = [0.0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        pool = pools[order[i]]
        min_price[i] = min_price[i + 1] + min(c.price for c in pool)
        max_score[i] = max_score[i + 1] + max(c.score for c in pool)

    best: dict[str, Candidate] = {}
    best_key: tuple | None = None
    chosen: dict[str, Candidate] = {}

    def key(score: float, price: int) -> tuple:
        return (-score, price, tuple(chosen[s].product_key for s in slots))

    def visit(i: int, price: int, score: float) -> None:
        nonlocal best, best_key
        counts["visited"] += 1
        if node_cap is not None and counts["visited"] > node_cap:
            raise _NodeCap
        if budget and price + min_price[i] > budget:
            counts["pruned_budget"] += 1
            return
        if best_key is not None and score + max_score[i] < -best_key[0] - 1e-9:
            counts["pruned_score"] += 1
            return
        if i == len(order):
            counts["valid"] += 1
            candidate_key = key(score, price)
            if best_key is None or candidate_key < best_key:
                best, best_key = chosen.copy(), candidate_key
            return
        slot = order[i]
        for candidate in pools[slot]:
            chosen[slot] = candidate
            if _pc_known_failures(chosen, spec, rules):
                counts["pruned_compat"] += 1
            else:
                visit(i + 1, price + candidate.price, score + candidate.score)
            del chosen[slot]

    try:
        visit(0, 0, 0.0)
    except _NodeCap:
        counts["capped"] = 1
    return best


def _cheapest_compatible(
    pools: dict[str, list[Candidate]], order: list[str], spec: RequirementSpec, rules: dict,
    counts: dict[str, int], node_cap: int,
) -> dict[str, Candidate]:
    """Lowest-price set with no *known* incompatibility, ignoring the budget. Used when no
    compatible set fits the budget: the budget is soft, compatibility is not, so the
    least-over-budget compatible set is the honest answer."""
    by_price = {s: sorted(pools[s], key=lambda c: (c.price, c.product_key)) for s in order}
    min_price = [0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        min_price[i] = min_price[i + 1] + by_price[order[i]][0].price

    best: dict[str, Candidate] = {}
    best_price: int | None = None
    chosen: dict[str, Candidate] = {}
    nodes = 0

    def visit(i: int, price: int) -> None:
        nonlocal best, best_price, nodes
        nodes += 1
        if nodes > node_cap:
            raise _NodeCap
        if i == len(order):
            if best_price is None or price < best_price:
                best, best_price = chosen.copy(), price
            return
        slot = order[i]
        for candidate in by_price[slot]:
            if best_price is not None and price + candidate.price + min_price[i + 1] >= best_price:
                break  # sorted ascending: nothing later in this slot can beat the incumbent
            chosen[slot] = candidate
            if not _pc_known_failures(chosen, spec, rules):
                visit(i + 1, price + candidate.price)
            del chosen[slot]

    try:
        visit(0, 0)
    except _NodeCap:
        counts["capped"] = 1
    counts["widened_visited"] = nodes
    return best


def _search_pc_build(
    pools: dict[str, list[Candidate]], slots: list[str], budget: int,
    spec: RequirementSpec, rules: dict, wide_pools: dict[str, list[Candidate]] | None = None,
) -> tuple[dict[str, Candidate], dict[str, int], bool]:
    """Search the supplied (already top-N) pools exactly for maximum total score.

    When no compatible in-budget set exists there, the search is repeated over
    ``wide_pools`` (every hard-filter survivor, not just top-N) — the top-N cut is made
    before cross-slot compatibility is known, so it can strand every compatible pair.
    If that still finds nothing in budget, the cheapest *compatible* set is returned with
    the budget marked failed. Only when no compatible set exists at all does a least-bad
    set over the top-N pools come back, explicitly marked failed.
    """
    order = [s for s in ("메인보드", "케이스", "CPU", "RAM", "GPU", "쿨러", "파워", "저장장치") if s in pools]
    order.extend(s for s in slots if s not in order)
    counts = {"considered": math.prod(len(pools[s]) for s in slots), "valid": 0,
              "visited": 0, "pruned_budget": 0, "pruned_compat": 0,
              "pruned_score": 0, "feasible": 0, "compatible": 0}
    if not all(pools[s] for s in slots):
        return {}, counts, False

    best = _max_score_search(pools, order, slots, budget, spec, rules, counts)
    if best:
        counts["feasible"] = counts["compatible"] = 1
        return best, counts, True

    if (wide_pools and all(wide_pools.get(s) for s in slots)
            and any(len(wide_pools[s]) > len(pools[s]) for s in slots)):
        counts["widened"] = 1
        wide_counts = {"visited": 0, "pruned_budget": 0, "pruned_compat": 0, "pruned_score": 0, "valid": 0}
        best = _max_score_search(wide_pools, order, slots, budget, spec, rules, wide_counts, WIDEN_NODE_CAP)
        counts["widened_visited"] = wide_counts["visited"]
        if best:
            if wide_counts.get("capped"):
                counts["capped"] = 1
            counts["feasible"] = counts["compatible"] = 1
            return best, counts, True
        cheapest = _cheapest_compatible(wide_pools, order, spec, rules, counts, WIDEN_NODE_CAP)
        if cheapest:
            counts["compatible"] = 1
            return cheapest, counts, True

    # No compatible set anywhere: distinguish budget shortage from incompatible pools.
    # This bounded diagnostic pass cannot be mistaken for a successful solution.
    fallback_key: tuple | None = None
    compatible = False
    for combination in product(*(pools[s] for s in slots)):
        option = dict(zip(slots, combination))
        failures = _pc_known_failures(option, spec, rules)
        price = sum(c.price for c in combination)
        score = sum(c.score for c in combination)
        option_key = (len(failures), 0 if not budget or price <= budget else 1,
                      price if not failures else -score, -score, price,
                      tuple(c.product_key for c in combination))
        if fallback_key is None or option_key < fallback_key:
            fallback_key, best = option_key, option
            compatible = not failures
    counts["compatible"] = int(compatible)
    return best, counts, compatible


def _cpu_name(chosen: dict[str, Candidate], spec: RequirementSpec) -> str | None:
    """견적에 넣은 CPU 의 이름, 없으면 사용자가 그대로 쓰는 CPU(업그레이드)가 적은 이름."""
    cand = chosen.get("CPU")
    return cand.name if cand is not None else (spec.owned.get("CPU") or {}).get("name")


def _chosen_specs(chosen: dict[str, Candidate], spec: RequirementSpec, slot: str) -> dict:
    """slot 에 뽑힌 후보의 specs — 없으면 사용자가 그대로 쓰는 부품(업그레이드)의 specs.
    정보 없는 부품(합성 카탈로그·override 미기재)은 빈 dict, 즉 호환 체크가 "정보 없음 → 근사"로 자연 강등한다."""
    cand = chosen.get(slot)
    if cand is None:
        return dict((spec.owned.get(slot) or {}).get("specs") or {})
    return cand.specs


_STATE_TEXT = {"ok": "ok", "unknown": "ok (근사)", "fail": "fail"}
# 0018 확장 열로 새로 생긴 검사 — 원본 엑셀에 값이 아직 없어서 못 본 경우는 감점·"확인 못 한 항목"으로 세지 않는다(화면 검사 상세에는 남는다).
# 값이 채워지면 자동으로 판정이 되고, 값이 있어서 나온 경고(속도 초과 등)는 그대로 센다.
_QUIET_WHEN_DATA_MISSING = {"psu_length", "gpu_slots", "radiator", "ram_slots", "ram_speed", "m2"}


def _show(value) -> str:
    if value is None or value == "" or value == []:
        return "정보 없음"
    return " / ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)


def pc_compat_details(chosen: dict[str, Candidate], spec: RequirementSpec, rules: dict) -> list[dict]:
    """호환 검사별 결과 — 무엇을 무엇과 비교했고 결과가 어땠는지. 화면의 "호환성 점검 상세"와 pc_link_check 가 같이 쓴다.

    각 항목: {axis, label, state, detail}. state 는 ok(통과) / unknown(스펙을 몰라 확인 못 함) / fail(확정된 비호환) /
    skipped(이번 견적에서 바뀌는 부품이 없어 보지 않음 — 업그레이드에서 GPU 만 바꾸는데 CPU 소켓을 묻지 않는다).
    상세 문장은 코드가 아는 값만 옮긴다. `rules` 는 규칙 문서의 verification 절.
    """
    from src.engine.stage3c_verify import axis_label

    specs_of = lambda slot: _chosen_specs(chosen, spec, slot)  # noqa: E731

    def name_of(slot: str) -> str:
        cand = chosen.get(slot)
        return cand.name if cand is not None else ((spec.owned.get(slot) or {}).get("name") or f"현재 {slot}")

    rows: list[dict] = []

    def add(axis: str, slots: tuple[str, ...], state: str, detail: str, data_missing: bool = False) -> None:
        # data_missing: 스펙 데이터가 비어 있어 못 본 것 — pc_link_check 가 이 중 확장 열 검사는 감점·이슈로 세지 않는다.
        if not any(s in chosen for s in slots):
            state, detail = "skipped", "이번 견적에서 바뀌는 부품이 아니라 확인하지 않았습니다."
            data_missing = False
        rows.append({"axis": axis, "label": axis_label(axis), "state": state, "detail": detail, "data_missing": data_missing})

    def missing(*pairs: tuple[str, object]) -> str:
        return " · ".join(f"{name}: {_show(value)}" for name, value in pairs) + " — 스펙 정보가 부족해 확인하지 못했습니다."

    # 소켓
    r = rules["socket"]
    cs, bs = specs_of("CPU").get(r["cpu_spec"]), specs_of("메인보드").get(r["mainboard_spec"])
    if cs and bs:
        add("socket", ("CPU", "메인보드"), "ok" if cs == bs else "fail",
            f"CPU {name_of('CPU')}({cs}) {'=' if cs == bs else '≠'} 메인보드 {name_of('메인보드')}({bs})")
    else:
        add("socket", ("CPU", "메인보드"), "unknown", missing(("CPU 소켓", cs), ("메인보드 소켓", bs)))
    socket_failed = bool(cs and bs and cs != bs)

    # 메모리 규격
    r = rules["memory"]
    rt, bm = specs_of("RAM").get(r["ram_spec"]), specs_of("메인보드").get(r["mainboard_spec"])
    if rt and bm:
        add("memory", ("RAM", "메인보드"), "ok" if rt == bm else "fail",
            f"RAM {rt} {'=' if rt == bm else '≠'} 메인보드 {bm}")
    else:
        add("memory", ("RAM", "메인보드"), "unknown", missing(("RAM 규격", rt), ("메인보드 메모리", bm)))

    # 메인보드 ↔ 케이스 크기
    r = rules["motherboard_case"]
    bf, cf = specs_of("메인보드").get(r["mainboard_spec"]), specs_of("케이스").get(r["case_spec"])
    fits = _form_fits(bf, cf) if bf and cf else None
    if fits is None:
        add("motherboard_case", ("메인보드", "케이스"), "unknown", missing(("메인보드 크기", bf), ("케이스 지원 크기", cf)))
    else:
        add("motherboard_case", ("메인보드", "케이스"), "ok" if fits else "fail",
            f"메인보드 {bf} {'→ 케이스가 지원' if fits else '은(는) 케이스가 지원하지 않는'} {_show(cf)}")

    # GPU 길이
    r = rules["gpu_length"]
    gl, mg = specs_of("GPU").get(r["gpu_spec"]), specs_of("케이스").get(r["case_spec"])
    if gl is not None and mg is not None:
        add("gpu_len", ("GPU", "케이스"), "ok" if gl <= mg else "fail",
            f"GPU 길이 {gl}mm {'≤' if gl <= mg else '>'} 케이스 허용 {mg}mm")
    else:
        add("gpu_len", ("GPU", "케이스"), "unknown", missing(("GPU 길이", gl), ("케이스 허용 길이", mg)))

    # 쿨러 높이
    r = rules["cooler_height"]
    ch, mc = specs_of("쿨러").get(r["cooler_spec"]), specs_of("케이스").get(r["case_spec"])
    if ch is not None and mc is not None:
        add("cooler_height", ("쿨러", "케이스"), "ok" if ch <= mc else "fail",
            f"쿨러 높이 {ch}mm {'≤' if ch <= mc else '>'} 케이스 허용 {mc}mm")
    elif ch is None and "liquid" in str(specs_of("쿨러").get("cooling_type") or "").lower():
        add("cooler_height", ("쿨러", "케이스"), "unknown",
            "수랭(AIO) 쿨러는 높이 대신 라디에이터 크기로 확인해야 하는데 케이스의 라디에이터 지원 정보가 없어 확인하지 못했습니다.")
    else:
        add("cooler_height", ("쿨러", "케이스"), "unknown", missing(("쿨러 높이", ch), ("케이스 허용 높이", mc)))

    # 쿨러 지원 소켓
    r = rules["cooler_socket"]
    sup = specs_of("쿨러").get(r["cooler_spec"])
    ok_socket = socket_supported(cs, sup)
    if ok_socket is None:
        add("cooler_socket", ("CPU", "쿨러"), "unknown", missing(("CPU 소켓", cs), ("쿨러 지원 소켓", sup)))
    else:
        add("cooler_socket", ("CPU", "쿨러"), "ok" if ok_socket else "fail",
            f"CPU 소켓 {cs} {'∈' if ok_socket else '∉'} 쿨러 지원 소켓 {sup}")

    # CPU 계열 ↔ 메인보드 지원 계열(BIOS)
    board_family = specs_of("메인보드").get(rules["bios"]["mainboard_spec"])
    family_ok = cpu_supported(_cpu_name(chosen, spec), board_family)
    if socket_failed:
        add("bios", ("CPU", "메인보드"), "skipped", "소켓이 맞지 않아 계열은 따로 보지 않았습니다.")
    elif family_ok is None:
        add("bios", ("CPU", "메인보드"), "unknown",
            missing(("CPU", _cpu_name(chosen, spec)), ("메인보드 지원 CPU 계열", board_family))
            .replace("스펙 정보가 부족해", "CPU 이름의 세대·계열을 읽지 못했거나 보드의 지원 목록이 없어"))
    else:
        add("bios", ("CPU", "메인보드"), "ok" if family_ok else "fail",
            f"CPU {_cpu_name(chosen, spec)} {'∈' if family_ok else '∉'} 메인보드 지원 계열 {board_family}"
            + (" (출고 BIOS 버전은 데이터에 없어 확인하지 않음)" if family_ok else ""))

    # 전력
    r = rules["power"]
    peak = specs_of("CPU").get(r.get("cpu_peak_spec", ""))
    cw = peak if peak is not None else specs_of("CPU").get(r["cpu_spec"])       # 최대 전력(PL2/PPT)이 있으면 그것으로
    cpu_label = "CPU 최대" if peak is not None else "CPU"
    gw, pw = specs_of("GPU").get(r["gpu_spec"]), specs_of("파워").get(r["psu_spec"])
    factor = r["psu_capacity_factor"]
    recommended = specs_of("GPU").get("recommended_psu_w")
    one_side = ("GPU" in chosen) != ("파워" in chosen)
    if cw is not None and gw is not None and pw is not None:
        total, limit = cw + gw, pw * factor
        add("power", ("CPU", "GPU", "파워"), "ok" if total <= limit else "fail",
            f"{cpu_label} {cw}W + GPU {gw}W = {total}W {'≤' if total <= limit else '>'} 파워 {pw}W × {factor} = {limit:.0f}W")
    elif r.get("use_gpu_recommended_psu", True) and one_side and recommended and pw is not None:
        # 권장 파워를 넘으면 실패는 아니지만 CPU 전력을 몰라 완전한 확인은 아니다 — "근사"로 남긴다(실패면 확정 비호환).
        add("power", ("CPU", "GPU", "파워"), "unknown" if pw >= recommended else "fail",
            f"제조사 권장 파워 {recommended}W {'≤' if pw >= recommended else '>'} 파워 {pw}W"
            + (" — 그러나 CPU 전력을 몰라 전체 소비전력은 확인하지 못했습니다." if pw >= recommended else ""))
    elif pw is not None and (spec.targets.get("파워") or {}).get("wattage_min") and pw < spec.targets["파워"]["wattage_min"]:
        add("power", ("CPU", "GPU", "파워"), "fail", f"파워 {pw}W < 요구 최소 {spec.targets['파워']['wattage_min']}W")
    else:
        add("power", ("CPU", "GPU", "파워"), "unknown", missing(("CPU 전력", cw), ("GPU 전력", gw), ("파워 용량", pw)))

    # 파워 폼팩터 ↔ 케이스
    r = rules["psu_form"]
    pf, cpf = specs_of("파워").get(r["psu_spec"]), specs_of("케이스").get(r["case_spec"])
    verdict = psu_fits_case(pf, cpf)
    if verdict is None:
        add("psu_form", ("파워", "케이스"), "unknown", missing(("파워 크기", pf), ("케이스 지원 파워", cpf)))
    elif verdict == "adapter":
        add("psu_form", ("파워", "케이스"), "unknown",
            f"파워 {pf}은(는) 케이스 지원 {cpf}보다 작아 어댑터 브래킷이 있어야 들어갑니다.")
    else:
        add("psu_form", ("파워", "케이스"), verdict,
            f"파워 {pf} {'→ 케이스가 지원' if verdict == 'ok' else '은(는) 케이스가 지원하는 가장 큰 크기보다 큽니다'} {cpf}")

    # GPU 전원 커넥터 ↔ 파워 — 종류와 개수. 개수 데이터(파워 PCIe 8핀·16핀 개수)가 있으면 개수까지, 없으면 표기(종류)만 본다.
    r = rules["gpu_connector"]
    gc, ga = specs_of("GPU").get(r["gpu_spec"]), specs_of("GPU").get(r["aux_spec"])
    pc = specs_of("파워").get(r["psu_spec"])
    n_pcie, n_16 = specs_of("파워").get(r["psu_pcie_count_spec"]), specs_of("파워").get(r["psu_16_count_spec"])
    count_state, count_detail = gpu_power_count_fit(gc, ga, n_pcie, n_16)
    if count_state in ("ok", "fail"):
        add("gpu_connector", ("GPU", "파워"), count_state, f"GPU {gc} — {count_detail}")
    elif count_state == "adapter":
        add("gpu_connector", ("GPU", "파워"), "unknown", f"GPU {gc} — {count_detail}")
    else:
        verdict = gpu_connector_fit(gc, ga, pc)
        if verdict is None:
            add("gpu_connector", ("GPU", "파워"), "unknown", missing(("GPU 전원 커넥터", gc), ("파워 제공 커넥터", pc)))
        elif verdict == "adapter":
            add("gpu_connector", ("GPU", "파워"), "unknown",
                f"GPU는 {gc}인데 파워는 {pc}만 제공합니다 — GPU에 동봉된 어댑터로 연결해야 합니다.")
        else:
            need = "보조 전원 불필요" if (str(ga or "").upper() == "X" or "슬롯" in str(gc)) else f"GPU {gc} ← 파워 {pc}"
            add("gpu_connector", ("GPU", "파워"), "ok", need + " (파워의 커넥터 개수 데이터가 없어 개수는 확인하지 않음)")

    # 파워 길이 ↔ 케이스
    r = rules["psu_length"]
    pl, cl = specs_of("파워").get(r["psu_spec"]), specs_of("케이스").get(r["case_spec"])
    if pl is not None and cl is not None:
        add("psu_length", ("파워", "케이스"), "ok" if pl <= cl else "fail",
            f"파워 길이 {pl}mm {'≤' if pl <= cl else '>'} 케이스 허용 {cl}mm")
    else:
        add("psu_length", ("파워", "케이스"), "unknown", missing(("파워 길이", pl), ("케이스 허용 파워 길이", cl)), data_missing=True)

    # GPU 두께 ↔ 케이스 확장 슬롯
    r = rules["gpu_slots"]
    thick, expansion = specs_of("GPU").get(r["gpu_spec"]), specs_of("케이스").get(r["case_spec"])
    need_slots = slots_needed(thick)
    if need_slots is not None and expansion is not None:
        add("gpu_slots", ("GPU", "케이스"), "ok" if need_slots <= expansion else "fail",
            f"GPU 두께 {thick}슬롯 → {need_slots}칸 {'≤' if need_slots <= expansion else '>'} 케이스 확장 슬롯 {expansion}칸")
    else:
        add("gpu_slots", ("GPU", "케이스"), "unknown", missing(("GPU 두께", thick), ("케이스 확장 슬롯", expansion)), data_missing=True)

    # 수랭(AIO) 라디에이터 ↔ 케이스
    r = rules["radiator"]
    cool = specs_of("쿨러")
    cooling = str(cool.get("cooling_type") or "")
    if cooling and "liquid" not in cooling.lower():
        rows.append({"axis": "radiator", "label": axis_label("radiator"), "state": "skipped", "data_missing": False,
                     "detail": "공랭 쿨러라 라디에이터 검사를 하지 않았습니다."})
    else:
        rad = cool.get(r["cooler_spec"])
        places = {name: parse_size_list(specs_of("케이스").get(key)) for name, key in zip(("전면", "상단", "후면"), r["case_specs"])}
        sizes = {n for v in places.values() for n in v}
        if rad is not None and sizes:
            where = [name for name, v in places.items() if int(rad) in v]
            add("radiator", ("쿨러", "케이스"), "ok" if where else "fail",
                f"라디에이터 {rad}mm → 케이스 " + (f"{'·'.join(where)} 장착 가능" if where else f"지원 크기 {sorted(sizes)}mm 에 없음"))
        else:
            add("radiator", ("쿨러", "케이스"), "unknown",
                missing(("쿨러 라디에이터", rad), ("케이스 라디에이터 지원", sorted(sizes) or None)), data_missing=True)

    # RAM 모듈 수·총용량 ↔ 메인보드 슬롯·최대 용량
    r = rules["ram_slots"]
    modules, dimm = parse_module_count(specs_of("RAM").get(r["ram_module_spec"])), specs_of("메인보드").get(r["board_slots_spec"])
    capacity, max_capacity = specs_of("RAM").get(r["ram_capacity_spec"]), specs_of("메인보드").get(r["board_max_capacity_spec"])
    parts, bad = [], False
    if modules is not None and dimm is not None:
        parts.append(f"RAM 모듈 {modules}개 {'≤' if modules <= dimm else '>'} 메인보드 DIMM 슬롯 {dimm}개")
        bad = bad or modules > dimm
    if capacity is not None and max_capacity is not None:
        parts.append(f"RAM 총 {capacity}GB {'≤' if capacity <= max_capacity else '>'} 메인보드 최대 {max_capacity}GB")
        bad = bad or capacity > max_capacity
    if parts:
        add("ram_slots", ("RAM", "메인보드"), "fail" if bad else "ok", " · ".join(parts))
    else:
        add("ram_slots", ("RAM", "메인보드"), "unknown",
            missing(("RAM 모듈 구성", specs_of("RAM").get(r["ram_module_spec"])), ("메인보드 DIMM 슬롯", dimm)), data_missing=True)

    # RAM 속도 ↔ 메인보드 최대 속도 (넘어도 비호환이 아니라 낮은 속도로 동작)
    r = rules["ram_speed"]
    speed, max_speed = specs_of("RAM").get(r["ram_spec"]), specs_of("메인보드").get(r["board_spec"])
    if speed is not None and max_speed is not None:
        if speed <= max_speed:
            add("ram_speed", ("RAM", "메인보드"), "ok", f"RAM {speed}MT/s ≤ 메인보드 최대 {max_speed}MT/s")
        else:
            add("ram_speed", ("RAM", "메인보드"), "unknown",
                f"RAM {speed}MT/s 가 메인보드 최대 {max_speed}MT/s 를 넘어 낮은 속도로 동작할 수 있습니다.")
    else:
        add("ram_speed", ("RAM", "메인보드"), "unknown", missing(("RAM 속도", speed), ("메인보드 최대 메모리 속도", max_speed)), data_missing=True)

    # M.2 SSD ↔ 메인보드 M.2 슬롯·세대
    r = rules["m2"]
    ssd = specs_of("저장장치")
    ssd_form, ssd_iface = str(ssd.get(r["ssd_form_spec"]) or ""), ssd.get(r["ssd_interface_spec"])
    board = specs_of("메인보드")
    m2_slots, board_gens = board.get(r["board_slots_spec"]), parse_pcie_gens(board.get(r["board_gen_spec"]))
    if ssd_form and "M.2" not in ssd_form:
        rows.append({"axis": "m2", "label": axis_label("m2"), "state": "skipped", "data_missing": False,
                     "detail": f"SSD({ssd_form})는 M.2 슬롯을 쓰지 않아 검사하지 않았습니다."})
    elif not ssd_form or m2_slots is None:
        add("m2", ("저장장치", "메인보드"), "unknown", missing(("SSD 폼팩터", ssd_form or None), ("메인보드 M.2 슬롯", m2_slots)), data_missing=True)
    elif m2_slots == 0 and "SATA" not in ssd_form.upper():
        add("m2", ("저장장치", "메인보드"), "fail", f"M.2 SSD({ssd_form})인데 메인보드에 M.2 슬롯이 없습니다.")
    else:
        ssd_gens = parse_pcie_gens(ssd_iface)
        if ssd_gens and board_gens and max(board_gens) < max(ssd_gens):
            add("m2", ("저장장치", "메인보드"), "unknown",
                f"SSD는 PCIe {max(ssd_gens):g} 지원인데 메인보드 M.2 는 최대 PCIe {max(board_gens):g} 이라 낮은 속도로 동작합니다.")
        else:
            add("m2", ("저장장치", "메인보드"), "ok",
                f"M.2 슬롯 {m2_slots}개" + (f" · SSD PCIe {max(ssd_gens):g} ≤ 슬롯 최대 {max(board_gens):g}" if ssd_gens and board_gens else ""))
    return rows


def pc_link_check(chosen: dict[str, Candidate], spec: RequirementSpec, rules: dict) -> dict[str, str]:
    """고른 부품들 사이의 호환 점검 결과 — 검사(axis)별 "ok" / "ok (근사)"(스펙을 몰라 정밀 검사를 못 함) / "fail".

    [4] 최적화가 결과를 만들 때와 교체·담기 뒤 세트 전체를 다시 점검할 때 같은 함수를 쓴다. 이번 견적에서 바뀌는
    부품이 없는 검사(skipped)는 넣지 않는다. 검사별 상세는 pc_compat_details.
    """
    link_check = {row["axis"]: _STATE_TEXT[row["state"]] for row in pc_compat_details(chosen, spec, rules)
                  if row["state"] != "skipped"
                  and not (row["state"] == "unknown" and row.get("data_missing") and row["axis"] in _QUIET_WHEN_DATA_MISSING)}
    for failure in _pc_known_failures(chosen, spec, rules):
        link_check[failure] = "fail"
    return link_check


def build_computer(
    rank: RankResult,
    spec: RequirementSpec,
    log: LogFn,
    *,
    exclude: set[tuple[str, str]] | None = None,
    round_no: int = 1,
) -> BuildResult:
    log(f"[4] 세트 최적화 ... (라운드 {round_no})")
    rules = load_computer_rules()["verification"]
    exclude = exclude or set()
    slots = list(spec.targets.keys())
    pools = {s: [c for c in _ranked(rank, s) if (s, c.product_key) not in exclude] for s in slots}
    budget = spec.budget.get("total", 0)
    wide_pools = {s: [c for c in _full_pool(rank, s) if (s, c.product_key) not in exclude] for s in slots}
    selected, search, compatible = _search_pc_build(pools, slots, budget, spec, rules, wide_pools)

    def _make_item(s: str, cand: Candidate) -> BuildItem:
        return BuildItem(
            slot=s, product_key=cand.product_key, name=cand.name, price=cand.price,
            variant_id=cand.variant_id,
            offer_observation_id=cand.offer_observation_id,
            perf_tier=float(cand.specs.get("perf_tier", 0)), score=cand.score,
            rank_from_3b=cand.rank or 1,
        )

    picked: list[BuildItem] = [_make_item(s, selected[s]) for s in slots if s in selected]

    total = sum(i.price for i in picked)
    used_pct = round(total / budget * 100, 1) if budget else 0.0
    def _tier(slot: str) -> float | None:
        picked_tier = next((i.perf_tier for i in picked if i.slot == slot), None)
        if picked_tier is not None:
            return picked_tier
        owned_tier = ((spec.owned.get(slot) or {}).get("specs") or {}).get("perf_tier")
        return float(owned_tier) if owned_tier is not None else None

    tiers_known = _tier("GPU") is not None and _tier("CPU") is not None
    gpu_t, cpu_t = _tier("GPU") or 0, _tier("CPU") or 0

    log(f"      상위 후보 {search['considered']:,} 조합 분기한정 탐색 "
        f"({search['visited']:,} 노드, 예산 적합 {search['valid']:,}개)"
        + ("" if search["feasible"] else " → 적합 세트 없음"))
    log(f"      총액 {total:,}원 / 예산 {used_pct}% / GPU tier {gpu_t} · CPU tier {cpu_t}")

    link_check = pc_link_check(selected, spec, rules)
    power_rule = rules["power"]
    cpu_w = _chosen_specs(selected, spec, "CPU").get(power_rule["cpu_spec"])
    gpu_w = _chosen_specs(selected, spec, "GPU").get(power_rule["gpu_spec"])
    if not compatible or len(picked) != len(slots):
        link_check["set"] = "fail"
    if budget and total > budget:
        link_check["budget"] = "fail"

    return BuildResult(
        list_id=spec.list_id,
        items=picked,
        totals={"price": total, "power_w": (cpu_w + gpu_w) if cpu_w is not None and gpu_w is not None else None, "avg_score": round(
            sum(i.score for i in picked) / max(1, len(picked)), 3)},
        budget={"max": budget, "used": total, "used_pct": used_pct,
                "slack": (budget - total) if budget else 0},
        link_check=link_check,
        balance={"gpu_tier": gpu_t, "cpu_tier": cpu_t,
                 "verdict": ("판단 보류" if not tiers_known else
                             "균형" if abs(gpu_t - cpu_t) <= rules["balance_max_tier_gap"] else "불균형")},
        alternatives=search,
        round=round_no,
    )


def run(rank: RankResult, spec: RequirementSpec, log: LogFn, **kw) -> BuildResult:
    if spec.category == "computer":
        return build_computer(rank, spec, log, **kw)
    raise NotImplementedError(f"stage4: 지원하지 않는 카테고리입니다: {spec.category}")

