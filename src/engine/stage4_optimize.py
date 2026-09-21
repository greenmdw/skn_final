"""[4] 세트 최적화 (컴퓨터).

슬롯별 top-N 조합을 완전탐색 + 가지치기(link_rules, 예산) → 완성 세트 1개.
재탐색 시 exclude 된 (slot, product_key) 는 후보에서 제외하고 재최적화한다.
"""
from __future__ import annotations

import math
from itertools import product

from src.dto import BuildItem, BuildResult, Candidate, RankResult, RequirementSpec
from src.engine import LogFn
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
    쿨러의 supported_socket은 "LGA1700/1200/115x, AM5/AM4"처럼 여러 소켓을 한
    문자열에 나열해서 정확 일치가 아니라 부분 문자열 포함으로 봐야 한다."""
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
        if cpu_socket and supported and cpu_socket not in supported:
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
    if cpu_socket and supported and cpu_socket not in supported:
        failures.add("cooler_socket")

    power = rules["power"]
    cpu_w = value("CPU", power["cpu_spec"])
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

    def _picked_specs(slot: str) -> dict:
        """slot에 뽑힌 후보의 specs — 정보 없는 부품(합성 카탈로그·override 미기재)은
        빈 dict, 즉 아래 각 체크가 "정보 없음 → 근사"로 자연 강등한다."""
        item = next((i for i in picked if i.slot == slot), None)
        if item is None:
            return dict((spec.owned.get(slot) or {}).get("specs") or {})
        return next((c.specs for c in pools.get(slot, []) if c.product_key == item.product_key), {})

    cpu_specs, mb_specs = _picked_specs("CPU"), _picked_specs("메인보드")
    gpu_specs, case_specs = _picked_specs("GPU"), _picked_specs("케이스")
    cooler_specs, psu_specs = _picked_specs("쿨러"), _picked_specs("파워")

    cpu_socket = cpu_specs.get(rules["socket"]["cpu_spec"])
    mb_socket = mb_specs.get(rules["socket"]["mainboard_spec"])
    if cpu_socket and mb_socket:
        socket_status = "ok" if cpu_socket == mb_socket else "fail"
    else:
        socket_status = "ok (근사)"  # 호환 데이터가 없는 부품 — 아직 확인 안 됨, 위반 확정 아님

    gpu_len = gpu_specs.get(rules["gpu_length"]["gpu_spec"])
    max_gpu_len = case_specs.get(rules["gpu_length"]["case_spec"])
    if gpu_len is not None and max_gpu_len is not None:
        gpu_len_status = "ok" if gpu_len <= max_gpu_len else "fail"
    else:
        gpu_len_status = "ok (근사)"

    cooler_h = cooler_specs.get(rules["cooler_height"]["cooler_spec"])
    max_cooler_h = case_specs.get(rules["cooler_height"]["case_spec"])
    if cooler_h is not None and max_cooler_h is not None:
        cooler_status = "ok" if cooler_h <= max_cooler_h else "fail"
    else:
        cooler_status = "ok (근사)"

    # CPU/GPU 소비전력 실측이 둘 다
    # 있을 때만 판정한다(한쪽만 있으면 합이 실제보다 낮게 나와 거짓 통과가 될 수 있어서).
    power_rule = rules["power"]
    cpu_w = cpu_specs.get(power_rule["cpu_spec"])
    gpu_w = gpu_specs.get(power_rule["gpu_spec"])
    psu_w = psu_specs.get(power_rule["psu_spec"])
    if cpu_w is not None and gpu_w is not None and psu_w is not None:
        power_status = "ok" if (cpu_w + gpu_w) <= psu_w * power_rule["psu_capacity_factor"] else "fail"
    else:
        power_status = "ok (근사)"

    link_check = {"socket": socket_status, "power": power_status, "gpu_len": gpu_len_status,
                  "cooler_height": cooler_status, "bios": "ok (근사)"}
    for failure in _pc_known_failures(selected, spec, rules):
        link_check[failure] = "fail"
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

