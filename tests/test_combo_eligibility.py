"""조합 적격성(4a단계, 정책 §2.3·§5.2~§5.4, 구현계획 §3.1) — 필수 호환 정보·위반 탈락·검증·재탐색.

신뢰도 산식·80점 기준은 그대로이고 적격성은 그와 별도다: 확인된 호환 위반 1건·예산 초과·필수 정보 누락·사용자 필수 요구 미충족이면
점수와 무관하게 해당 조합은 정상 추천이 아니다. DB가 필요한 테스트(맨 아래)만 @pytest.mark.db.
"""
from __future__ import annotations

import os
import random
import uuid

import pytest

from src.config import CONFIDENCE_THRESHOLD
from src.dto import BuildResult, Candidate, RankResult, RequirementSpec, VerificationResult, VerificationTarget
from src.engine import eligibility as elig
from src.engine import research_loop, stage3c_verify
from src.engine.stage2_requirement import load_computer_rules
from src.engine.stage4_optimize import (_pc_required_missing, _pc_requirement_unmet, _search_pc_build, build_computer,
                                        pc_compat_details, pc_link_check, required_info_findings)

_noop = lambda _m: None  # noqa: E731
RULES = load_computer_rules()["verification"]
SLOTS = ("CPU", "메인보드", "RAM", "GPU", "쿨러", "케이스", "파워", "저장장치")

# 모든 필수 호환 정보가 있고 서로 맞는 기준 세트 — 테스트는 여기서 키를 지우거나(None) 바꿔 한 가지씩 확인한다.
BASE: dict[str, dict] = {
    "CPU": {"socket": "AM5", "tdp_w": 105, "max_power_w": 142, "perf_tier": 7},
    "메인보드": {"socket": "AM5", "mem_type": "DDR5", "form_factor": "ATX", "dimm_slots": 4, "max_memory_gb": 192,
              "m2_slots": 3, "supported_cpu_family": "Ryzen 7000 / 8000G / 9000 계열", "max_memory_speed_mts": 6400},
    "RAM": {"mem_type": "DDR5", "module_config": "16GB × 2", "capacity_gb": 32, "speed_mts": 6000},
    "GPU": {"length_mm": 300, "slot_thickness": 2.5, "power_w": 200, "power_connector": "1× 8-pin", "aux_power": "O",
            "perf_tier": 7},
    "쿨러": {"cooling_type": "Air (Single-Tower)", "height_mm": 150, "supported_socket": "AM5/AM4"},
    "케이스": {"supports_form_factors": ["ATX", "mATX"], "max_gpu_len_mm": 350, "max_cooler_height_mm": 170,
            "expansion_slots": 7, "psu_form_factor": "ATX", "max_psu_length_mm": 200,
            "radiator_front_mm": "240;280", "radiator_top_mm": "240", "radiator_rear_mm": "120"},
    "파워": {"form_factor": "ATX", "length_mm": 160, "wattage_w": 750, "gpu_power_connector": "PCIe 8-pin / 12V-2x6",
            "pcie_8pin_count": 3, "connector_12v2x6_count": 1},
    "저장장치": {"form_factor": "M.2 2280", "interface": "PCIe 4.0 x4"},
}
NAMES = {"CPU": "AMD Ryzen 7 7700X"}


def part(slot: str, key: str | None = None, *, price: int = 10_000, score: float = 0.5, name: str | None = None,
         **over) -> Candidate:
    """기준 specs 에 over 를 덮어쓴 후보. 값을 None 으로 주면 그 키를 뺀다."""
    specs = {**BASE[slot], **over}
    specs = {k: v for k, v in specs.items() if v is not None}
    key = key or f"{slot}-x"
    return Candidate(product_key=key, slot=slot, name=name or NAMES.get(slot, key), brand="b", price=price,
                     score=score, specs=specs)


def full(**over_by_slot) -> dict[str, Candidate]:
    return {s: part(s, **over_by_slot.get(s, {})) for s in SLOTS}


def spec_of(targets=SLOTS, *, mode="build", owned=None, budget=10_000_000, ram=None) -> RequirementSpec:
    t = {s: {} for s in targets}
    if ram is not None:
        t["RAM"] = ram
    return RequirementSpec(list_id="t", category="computer", mode=mode, targets=t, budget={"total": budget}, owned=owned or {})


def rows_of(chosen, spec=None):
    return {r["axis"]: r for r in pc_compat_details(chosen, spec or spec_of(), RULES)}


def findings_of(chosen, spec=None):
    return {f["axis"]: f for f in required_info_findings(chosen, spec or spec_of(), RULES)}


def missing_keys(chosen, spec=None, axis=None):
    out = [(m["slot"], m["key"]) for f in required_info_findings(chosen, spec or spec_of(), RULES)
           if axis is None or f["axis"] == axis for m in f["missing"]]
    return out


def rank_of(pools: dict[str, list[Candidate]]) -> RankResult:
    return RankResult(slots={s: {"ranked": [c.model_dump() for c in cands]} for s, cands in pools.items()})


def build_of(pools, *, budget=10_000_000, spec=None, exclude=None):
    spec = spec or spec_of(tuple(pools), budget=budget)
    return build_computer(rank_of(pools), spec, _noop, exclude=exclude), spec


# ── 기준 세트 ─────────────────────────────────────────────────────────────────────

def test_base_set_is_eligible_and_has_no_required_gaps():
    chosen, spec = full(), spec_of()
    assert _pc_required_missing(chosen, spec, RULES) == set() and _pc_requirement_unmet(chosen, spec, RULES) == set()
    assert not [r for r in pc_compat_details(chosen, spec, RULES) if r["state"] == "fail"]
    assert all(r["required_missing"] is False for r in pc_compat_details(chosen, spec, RULES))
    build, _ = build_of({s: [c] for s, c in chosen.items()})
    assert build.eligibility == {"status": "recommendable", "reasons": []}
    result = stage3c_verify.verify_build(build, "computer", _noop, chosen=chosen, spec=spec, rules=RULES)
    assert result.targets[0].eligible and result.targets[0].passed and result.targets[0].blocking == []


# ── verify_build: 위반·예산은 신뢰도와 별개로 탈락 ─────────────────────────────────────

def _verify(link_check=None, budget=None, **kw):
    build = BuildResult(list_id="t", link_check=link_check or {}, budget=budget or {})
    return stage3c_verify.verify_build(build, "computer", _noop, **kw).targets[0]


def test_single_violation_at_confidence_80_is_not_passed_and_not_eligible():
    chosen, spec = full(), spec_of()
    target = _verify({"socket": "fail"}, chosen=chosen, spec=spec, rules=RULES)
    assert target.confidence == 80 == CONFIDENCE_THRESHOLD     # 신뢰도 산식·기준은 그대로
    assert target.passed is False and target.eligible is False
    assert target.blocking == [{"code": "compat_violation", "axis": "socket"}]


def test_several_violations_all_blocking_and_a_high_score_does_not_cancel_them():
    chosen, spec = full(), spec_of()
    target = _verify({"socket": "fail", "gpu_len": "fail", "power": "fail"}, chosen=chosen, spec=spec, rules=RULES)
    assert target.eligible is False
    assert {b["axis"] for b in target.blocking if b["code"] == "compat_violation"} == {"socket", "gpu_len", "power"}
    # 점수가 높은 비호환 조합은 탐색에서 점수가 낮은 호환 조합에 진다(점수로 위반을 상쇄하지 않는다).
    good = part("쿨러", "good", score=0.1)
    bad = part("쿨러", "bad", score=0.99, supported_socket="LGA1851")
    pools = {s: [part(s)] for s in SLOTS if s != "쿨러"} | {"쿨러": [bad, good]}
    build, _ = build_of(pools)
    assert {i.slot: i.product_key for i in build.items}["쿨러"] == "good"
    assert build.eligibility["status"] == "recommendable"


def test_budget_violation_alone_is_ineligible():
    chosen, spec = full(), spec_of()
    target = _verify({"budget": "fail"}, {"max": 100, "used": 105, "used_pct": 105.0}, chosen=chosen, spec=spec, rules=RULES)
    assert target.confidence == 80 and target.passed is False and target.eligible is False
    assert target.blocking == [{"code": "budget_exceeded", "axis": "budget"}]
    over = _verify({}, {"max": 100, "used": 115, "used_pct": 115.0}, chosen=chosen, spec=spec, rules=RULES)
    assert over.eligible is False and over.blocking[0]["code"] == "budget_exceeded"


def test_set_failure_is_no_compatible_set():
    target = _verify({"set": "fail"}, chosen=full(), spec=spec_of(), rules=RULES)
    assert {"code": "no_compatible_set", "axis": "set"} in target.blocking and target.eligible is False


@pytest.mark.parametrize("kw", [{}, {"chosen": {}}, {"chosen": {}, "spec": spec_of()}, {"spec": spec_of(), "rules": RULES}])
def test_missing_verification_inputs_are_never_eligible(kw):
    target = _verify(**kw)
    assert target.confidence == 100 and target.passed is False and target.eligible is False
    assert {"code": "verification_inputs_missing"} in target.blocking


def test_required_missing_blocks_even_when_the_penalty_accounting_is_quiet():
    # 파워 길이(_QUIET_WHEN_DATA_MISSING)는 감점·쟁점으로 세지 않지만 필수 누락이라 탈락시킨다.
    chosen = full(파워={"length_mm": None})
    spec = spec_of()
    link_check = pc_link_check(chosen, spec, RULES)
    assert "psu_length" not in link_check
    target = _verify(link_check, chosen=chosen, spec=spec, rules=RULES)
    assert target.confidence == 100 and target.passed is False
    assert target.blocking == [{"code": "required_info_missing", "axis": "psu_length",
                                "missing": [{"slot": "파워", "key": "length_mm", "side": "purchase",
                                             "name": "파워-x", "product_key": "파워-x"}]}]


# ── 탐색: 필수 정보 누락 조합은 빠지고 다른 유효 조합이 선택된다 ─────────────────────────────

def _pools(**replace):
    pools = {s: [part(s)] for s in SLOTS}
    pools.update(replace)
    return pools


def test_search_skips_combos_missing_required_info_and_counts_the_pruning():
    no_height = part("쿨러", "no-height", score=0.99, height_mm=None)
    ok = part("쿨러", "ok", score=0.2)
    build, _ = build_of(_pools(쿨러=[no_height, ok]))
    assert {i.slot: i.product_key for i in build.items}["쿨러"] == "ok"
    assert build.alternatives["pruned_required_missing"] >= 1
    assert build.eligibility["status"] == "recommendable"


def test_no_valid_combo_reports_not_recommendable_with_slot_and_key():
    build, _ = build_of(_pools(케이스=[part("케이스", "c1", max_psu_length_mm=None), part("케이스", "c2", max_psu_length_mm=None)]))
    assert build.eligibility["status"] == "not_recommendable"
    reason = build.eligibility["reasons"][0]
    assert reason["code"] == "required_info_missing" and reason["axes"] == ["psu_length"]
    assert {(m["slot"], m["key"], m["side"]) for m in reason["missing"]} == {("케이스", "max_psu_length_mm", "purchase")}
    assert len(build.items) == 8                      # 진단용 구성은 부품표를 그대로 보여 준다


def test_required_key_empty_for_every_candidate_is_still_checked():
    """모든 후보에 같은 키가 비어 있어도 검사를 생략하지 않는다(카탈로그 보유율로 필수 여부를 바꾸지 않는다)."""
    pools = _pools(파워=[part("파워", f"p{i}", length_mm=None, price=1000 * (i + 1)) for i in range(4)])
    build, _ = build_of(pools)
    assert build.eligibility["status"] == "not_recommendable"
    assert build.alternatives["pruned_required_missing"] >= 4
    assert any(m["key"] == "length_mm" for m in build.eligibility["reasons"][0]["missing"])


def test_widened_search_also_prunes_and_merges_counters():
    top = _pools(쿨러=[part("쿨러", "bad", height_mm=None)])
    wide = _pools(쿨러=[part("쿨러", "bad", height_mm=None), part("쿨러", "good")])
    chosen, counts, compatible = _search_pc_build(
        {s: list(c) for s, c in top.items()}, list(SLOTS), 10_000_000, spec_of(), RULES, wide_pools=wide)
    assert compatible and chosen["쿨러"].product_key == "good"
    assert counts["widened"] == 1 and counts["pruned_required_missing"] >= 1


def test_partial_combo_is_not_pruned_for_slots_not_chosen_yet():
    spec = spec_of()
    partial = {"쿨러": part("쿨러", height_mm=None)}            # 케이스가 아직 안 정해졌다 → 쿨러 높이는 판정을 미룬다
    assert _pc_required_missing(partial, spec, RULES) == set()
    assert findings_of(partial, spec)["cooler_height"]["deferred"] is True
    with_case = {**partial, "케이스": part("케이스")}
    assert _pc_required_missing(with_case, spec, RULES) == {"cooler_height"}


def test_partial_flags_are_a_subset_of_the_complete_result_for_random_orders():
    rng = random.Random(7)
    for _ in range(40):
        chosen = _random_chosen(rng)
        spec = spec_of()
        total = _pc_required_missing(chosen, spec, RULES)
        order = list(SLOTS)
        rng.shuffle(order)
        part_set: dict[str, Candidate] = {}
        for slot in order:
            part_set[slot] = chosen[slot]
            assert _pc_required_missing(part_set, spec, RULES) <= total


def test_a_slot_blocked_for_every_candidate_skips_the_search_entirely():
    """한 슬롯의 후보가 모두 자기 값 때문에 막혀 있으면 조합을 탐색하지 않는다(카탈로그 전체 확대 탐색에 몇 분이 걸리지 않게)."""
    pools = _pools(쿨러=[part("쿨러", f"c{i}", height_mm=None) for i in range(3)])
    chosen, counts, compatible = _search_pc_build(
        {s: list(c) for s, c in pools.items()}, list(SLOTS), 10_000_000, spec_of(), RULES,
        wide_pools={s: list(c) for s, c in pools.items()})
    assert counts["visited"] == 0 and counts.get("widened_visited", 0) == 0
    assert counts["pruned_required_missing"] >= 3
    assert len(chosen) == 8 and compatible is True           # 진단용 구성(부적격)은 그래도 만든다
    build, _ = build_of(pools)
    assert build.eligibility["status"] == "not_recommendable" and len(build.items) == 8


def test_unary_block_ignores_gaps_that_another_partner_could_avoid():
    """자기 값이 비어도 상대에 따라 필요 없는 값은 막지 않는다 — 케이스의 쿨러 높이는 수랭 쿨러와 짝이면 쓰지 않는다."""
    from src.engine.stage4_optimize import _unary_blocked

    spec = spec_of()
    assert _unary_blocked("케이스", part("케이스", max_cooler_height_mm=None), spec, RULES) is None
    assert _unary_blocked("쿨러", part("쿨러", height_mm=None), spec, RULES) == "missing"
    assert _unary_blocked("파워", part("파워", length_mm=None), spec, RULES) == "missing"
    assert _unary_blocked("저장장치", part("저장장치", form_factor="2.5-inch SATA"), spec, RULES) is None


def test_owned_part_gap_blocks_every_candidate_without_searching():
    spec = _upgrade(owned=_owned(파워={"wattage_w": None}))
    pools = {"GPU": [part("GPU", f"g{i}") for i in range(4)]}
    _, counts, _ = _search_pc_build(pools, ["GPU"], 10_000_000, spec, RULES)
    assert counts["visited"] == 0 and counts["pruned_required_missing"] == 4


# ── 호환 점검 상세: ram_slots·수랭 높이·SATA·라디에이터 ───────────────────────────────────

def test_ram_slots_partial_knowledge_is_unknown_and_required_missing():
    chosen = full(메인보드={"max_memory_gb": None})            # 모듈 수 ≤ DIMM 은 알지만 총용량 ≤ 최대 용량을 모른다
    row = rows_of(chosen)["ram_slots"]
    assert row["state"] == "unknown" and row["required_missing"] is True
    assert row["missing_keys"] == [{"slot": "메인보드", "key": "max_memory_gb"}]
    assert row["missing_slots"] == ("메인보드",)                 # 모르는 쪽만
    assert "ram_slots" not in pc_link_check(chosen, spec_of(), RULES)      # 감점·쟁점으로는 세지 않는 기존 규칙 그대로
    other = rows_of(full(RAM={"module_config": None}))["ram_slots"]
    assert other["state"] == "unknown" and other["missing_slots"] == ("RAM",)
    assert {k["key"] for k in other["missing_keys"]} == {"module_config"}


def test_ram_slots_known_violation_is_fail_even_if_the_other_half_is_missing():
    row = rows_of(full(RAM={"capacity_gb": 512}, 메인보드={"dimm_slots": None}))["ram_slots"]
    assert row["state"] == "fail" and row["required_missing"] is True


def test_ram_slots_both_known_is_ok():
    row = rows_of(full())["ram_slots"]
    assert row["state"] == "ok" and row["required_missing"] is False and row["missing_keys"] == []


def test_liquid_cooler_height_is_skipped_and_radiator_is_checked():
    chosen = full(쿨러={"cooling_type": "Liquid (AIO)", "height_mm": None, "radiator_mm": 280})
    rows = rows_of(chosen)
    assert rows["cooler_height"]["state"] == "skipped" and "라디에이터 검사가 대신함" in rows["cooler_height"]["detail"]
    assert rows["cooler_height"]["applicable"] is False and rows["cooler_height"]["required_missing"] is False
    assert rows["radiator"]["state"] == "ok" and rows["radiator"]["applicable"] is True
    assert "cooler_height" not in pc_link_check(chosen, spec_of(), RULES)
    assert _pc_required_missing(chosen, spec_of(), RULES) == set()


def test_air_cooler_height_missing_is_required_missing_and_radiator_is_skipped():
    chosen = full(쿨러={"height_mm": None})
    rows = rows_of(chosen)
    assert rows["cooler_height"]["required_missing"] is True
    assert rows["cooler_height"]["missing_keys"] == [{"slot": "쿨러", "key": "height_mm"}]
    assert rows["radiator"]["state"] == "skipped" and rows["radiator"]["applicable"] is False


def test_liquid_cooler_without_any_case_radiator_info_is_required_missing():
    chosen = full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 240},
                  케이스={"radiator_front_mm": None, "radiator_top_mm": None, "radiator_rear_mm": None})
    row = rows_of(chosen)["radiator"]
    assert row["required_missing"] is True
    assert {k["key"] for k in row["missing_keys"]} == {"radiator_front_mm", "radiator_top_mm", "radiator_rear_mm"}
    # 한 곳이라도 지원 크기가 있으면 충분하다
    ok = rows_of(full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 120},
                      케이스={"radiator_front_mm": None, "radiator_top_mm": None}))["radiator"]
    assert ok["required_missing"] is False and ok["state"] == "ok"


def test_cooling_type_unknown_is_itself_the_missing_key():
    f = findings_of(full(쿨러={"cooling_type": None}))
    assert [(m["slot"], m["key"]) for m in f["cooler_height"]["missing"]] == [("쿨러", "cooling_type")]


def test_sata_ssd_makes_m2_not_applicable_even_without_board_m2_info():
    chosen = full(저장장치={"form_factor": "2.5-inch SATA"}, 메인보드={"m2_slots": None})
    row = rows_of(chosen)["m2"]
    assert row["state"] == "skipped" and row["applicable"] is False and row["required_missing"] is False
    assert _pc_required_missing(chosen, spec_of(), RULES) == set()


def test_m2_ssd_requires_board_m2_slots():
    chosen = full(메인보드={"m2_slots": None})
    row = rows_of(chosen)["m2"]
    assert row["required_missing"] is True and row["missing_keys"] == [{"slot": "메인보드", "key": "m2_slots"}]
    assert rows_of(full(저장장치={"form_factor": None}))["m2"]["missing_keys"] == [{"slot": "저장장치", "key": "form_factor"}]


def test_pcie_generation_difference_stays_a_plain_warning_not_a_required_gap():
    chosen = full(저장장치={"interface": "PCIe 5.0 x4"}, 메인보드={"m2_pcie_gen": "PCIe 4.0"})
    row = rows_of(chosen)["m2"]
    assert row["state"] == "unknown" and row["required_missing"] is False


def test_row_state_and_detail_are_otherwise_unchanged_by_required_flags():
    rows = rows_of(full())
    assert all({"applicable", "required", "missing_keys", "required_missing"} <= set(r) for r in rows.values())
    assert rows["socket"]["state"] == "ok" and rows["socket"]["required"] is True and rows["socket"]["applicable"] is True


# ── gpu_connector: 종류·개수 ──────────────────────────────────────────────────────

def test_connector_count_missing_on_the_needed_path_is_required_missing():
    chosen = full(GPU={"power_connector": "2× 8-pin"}, 파워={"pcie_8pin_count": None})
    row = rows_of(chosen)["gpu_connector"]
    assert row["required_missing"] is True and row["missing_keys"] == [{"slot": "파워", "key": "pcie_8pin_count"}]
    assert row["state"] == "ok"                       # 종류 표기만 본 기존 판정은 그대로(개수 데이터가 없어 개수는 확인 안 함)
    assert _pc_required_missing(chosen, spec_of(), RULES) == {"gpu_connector"}


def test_confirmed_connector_shortage_is_a_violation_not_a_gap():
    chosen = full(GPU={"power_connector": "2× 8-pin"}, 파워={"pcie_8pin_count": 1})
    assert rows_of(chosen)["gpu_connector"]["state"] == "fail"
    assert rows_of(chosen)["gpu_connector"]["required_missing"] is False
    assert _pc_required_missing(chosen, spec_of(), RULES) == set()
    assert pc_link_check(chosen, spec_of(), RULES)["gpu_connector"] == "fail"


def test_gpu_without_aux_power_makes_connector_checks_not_applicable():
    chosen = full(GPU={"power_connector": "슬롯 전력", "aux_power": "X"},
                  파워={"gpu_power_connector": None, "pcie_8pin_count": None, "connector_12v2x6_count": None})
    row = rows_of(chosen)["gpu_connector"]
    assert row["applicable"] is False and row["required_missing"] is False
    assert _pc_required_missing(chosen, spec_of(), RULES) == set()


def test_unused_connector_count_is_not_required_when_another_path_is_ok():
    chosen = full(GPU={"power_connector": "1× 16-pin 또는 2× 8-pin"}, 파워={"pcie_8pin_count": None, "connector_12v2x6_count": 1})
    assert findings_of(chosen)["gpu_connector_count"]["missing"] == []
    only_pcie = full(GPU={"power_connector": "1× 16-pin 또는 2× 8-pin"}, 파워={"pcie_8pin_count": 2, "connector_12v2x6_count": None})
    assert findings_of(only_pcie)["gpu_connector_count"]["missing"] == []       # 8핀 경로로 충족 — 16핀 개수는 쓰지 않는다


def test_sixteen_pin_gpu_needs_the_counts_for_its_path():
    chosen = full(GPU={"power_connector": "1× 16-pin (12V-2x6)"}, 파워={"pcie_8pin_count": 3, "connector_12v2x6_count": None})
    assert ("파워", "connector_12v2x6_count") in missing_keys(chosen, axis="gpu_connector_count")


def test_connector_kind_missing_or_unreadable_is_required_missing():
    assert ("파워", "gpu_power_connector") in missing_keys(full(파워={"gpu_power_connector": None}), axis="gpu_connector")
    assert ("GPU", "power_connector") in missing_keys(full(GPU={"power_connector": "제조사 모델별 상이"}), axis="gpu_connector")


# ── ram_speed ─────────────────────────────────────────────────────────────────────

def test_ram_speed_without_user_requirement_keeps_the_existing_caution_and_is_not_required():
    chosen = full(RAM={"speed_mts": 7200})                      # 보드 최대 6400 보다 빠름 → 낮은 속도로 동작(기존 '확인 필요')
    row = rows_of(chosen)["ram_speed"]
    assert row["state"] == "unknown" and row["required"] is False and row["required_missing"] is False
    assert pc_link_check(chosen, spec_of(), RULES)["ram_speed"] == "ok (근사)"
    # CPU 에 지원 속도 키가 없어도 일반 요청은 그대로(기본 기준 세트에는 CPU 키가 없다)
    assert rows_of(full())["ram_speed"]["required_missing"] is False


def test_ram_speed_user_requirement_needs_cpu_supported_speed():
    spec = spec_of(ram={"speed_mts_min": 6000})
    row = rows_of(full(), spec)["ram_speed"]
    assert row["required"] is True and row["required_missing"] is True
    assert row["missing_keys"] == [{"slot": "CPU", "key": "max_memory_speed_mts"}]
    assert _pc_required_missing(full(), spec, RULES) == {"ram_speed"}


def test_ram_speed_user_requirement_met_when_all_three_support_it():
    spec = spec_of(ram={"speed_mts_min": 6000})
    chosen = full(CPU={"max_memory_speed_mts": 6400})
    assert _pc_required_missing(chosen, spec, RULES) == set() and _pc_requirement_unmet(chosen, spec, RULES) == set()


def test_ram_speed_confirmed_shortfall_is_requirement_unmet_even_if_something_else_is_missing():
    spec = spec_of(ram={"speed_mts_min": 6000})
    chosen = full(RAM={"speed_mts": 5200})                       # RAM 이 이미 모자라다 — CPU 값이 없어도 미달은 확인된 것
    assert _pc_requirement_unmet(chosen, spec, RULES) == {"ram_speed"}
    board = full(CPU={"max_memory_speed_mts": 5600}, 메인보드={"max_memory_speed_mts": 6400})
    assert _pc_requirement_unmet(board, spec, RULES) == {"ram_speed"}   # 지원 속도의 최솟값(CPU 5600)이 요구에 모자람
    build, _ = build_of({s: [c] for s, c in chosen.items()}, spec=spec)
    assert any(r["code"] == "requirement_unmet" for r in build.eligibility["reasons"])
    assert build.alternatives["pruned_requirement_unmet"] + build.alternatives["pruned_required_missing"] >= 1


def test_search_prefers_the_combo_that_meets_the_user_speed():
    spec = spec_of(ram={"speed_mts_min": 6000})
    slow = part("RAM", "slow", score=0.9, speed_mts=4800)
    fast = part("RAM", "fast", score=0.1, speed_mts=6000)
    pools = _pools(CPU=[part("CPU", max_memory_speed_mts=6400)], RAM=[slow, fast])
    build, _ = build_of(pools, spec=spec)
    assert {i.slot: i.product_key for i in build.items}["RAM"] == "fast"
    assert build.alternatives["pruned_requirement_unmet"] >= 1 and build.eligibility["status"] == "recommendable"


# ── 업그레이드(D2): 유지 부품도 같은 기준 ─────────────────────────────────────────────

def _owned(**over_by_slot):
    out = {}
    for slot in SLOTS:
        specs = {**BASE[slot], **over_by_slot.get(slot, {})}
        out[slot] = {"name": f"기존 {slot}", "specs": {k: v for k, v in specs.items() if v is not None}, "source": "text"}
    return out


def _upgrade(targets=("GPU",), owned=None):
    keep = {s: o for s, o in (owned or _owned()).items() if s not in targets}
    return spec_of(targets, mode="upgrade", owned=keep)


def test_upgrade_with_every_needed_kept_part_value_is_eligible():
    spec = _upgrade()
    chosen = {"GPU": part("GPU")}
    assert _pc_required_missing(chosen, spec, RULES) == set()
    build, _ = build_of({"GPU": [part("GPU")]}, spec=spec)
    assert build.eligibility["status"] == "recommendable"


def test_upgrade_kept_psu_without_wattage_holds_the_combo_and_names_the_owned_part():
    spec = _upgrade(owned=_owned(파워={"wattage_w": None}))
    chosen = {"GPU": part("GPU")}
    assert _pc_required_missing(chosen, spec, RULES) == {"power"}
    build, _ = build_of({"GPU": [part("GPU")]}, spec=spec)
    assert build.eligibility["status"] == "not_recommendable"
    reason = build.eligibility["reasons"][0]
    assert reason["code"] == "required_info_missing"
    assert {"slot": "파워", "key": "wattage_w", "side": "owned", "name": "기존 파워"} in reason["missing"]
    assert "쓰고 계신 파워" in elig.eligibility_notice(build.eligibility)


def test_upgrade_kept_case_without_gpu_length_holds_but_a_known_length_is_fine():
    chosen = {"GPU": part("GPU")}
    assert ("케이스", "max_gpu_len_mm") in missing_keys(chosen, _upgrade(owned=_owned(케이스={"max_gpu_len_mm": None})))
    assert missing_keys(chosen, _upgrade(), axis="gpu_len") == []


def test_upgrade_slot_with_no_information_at_all_counts_as_missing_kept_part_info():
    owned = {s: o for s, o in _owned().items() if s != "케이스"}
    spec = spec_of(("GPU",), mode="upgrade", owned={s: o for s, o in owned.items() if s != "GPU"})
    found = findings_of({"GPU": part("GPU")}, spec)
    assert {"slot": "케이스", "key": "max_gpu_len_mm", "side": "owned"} in found["gpu_len"]["missing"]


def test_upgrade_axes_without_a_purchased_part_are_not_applicable():
    spec = _upgrade(owned=_owned(쿨러={"height_mm": None}, 케이스={"max_cooler_height_mm": None}))
    found = findings_of({"GPU": part("GPU")}, spec)
    assert found["cooler_height"]["applicable"] is False and found["cooler_height"]["missing"] == []
    assert found["socket"]["applicable"] is False      # CPU·메인보드 모두 유지 — 이번 견적에서 바뀌는 부품이 아니다


def test_new_build_removed_part_makes_the_axis_not_applicable_instead_of_a_gap():
    partial = {s: part(s) for s in SLOTS if s != "저장장치"}      # 견적에서 뺀 항목(재검증) — 세트 완성 여부는 set 검사가 본다
    assert findings_of(partial, spec_of(()))["m2"]["applicable"] is False      # 재검증의 spec 은 targets 가 비어 있다


# ── 세 판정(탐색용·상세·최종 검증)의 일치 ─────────────────────────────────────────────

def _random_chosen(rng: random.Random) -> dict[str, Candidate]:
    chosen = {}
    for slot in SLOTS:
        over = {}
        for key in BASE[slot]:
            roll = rng.random()
            if roll < 0.15:
                over[key] = None
            elif roll < 0.2 and isinstance(BASE[slot][key], (int, float)):
                over[key] = 1
        if slot == "쿨러" and rng.random() < 0.4:
            over.update(cooling_type="Liquid (AIO)", radiator_mm=rng.choice([None, 120, 240, 360]))
        if slot == "저장장치" and rng.random() < 0.3:
            over["form_factor"] = "2.5-inch SATA"
        if slot == "GPU" and rng.random() < 0.3:
            over["power_connector"] = rng.choice(["2× 8-pin", "1× 16-pin 또는 2× 8-pin", "슬롯 전력", "1× 16-pin (12V-2x6)"])
            if over["power_connector"] == "슬롯 전력":
                over["aux_power"] = "X"
        chosen[slot] = part(slot, **over)
    return chosen


def _three_way(chosen, spec):
    search = _pc_required_missing(chosen, spec, RULES)
    rows = {r["axis"] for r in pc_compat_details(chosen, spec, RULES) if r["required_missing"]}
    build = BuildResult(list_id="t", link_check=pc_link_check(chosen, spec, RULES))
    target = stage3c_verify.verify_build(build, "computer", _noop, chosen=chosen, spec=spec, rules=RULES).targets[0]
    blocking = {b["axis"] for b in target.blocking if b["code"] == "required_info_missing"}
    return search, rows, blocking


def test_search_detail_and_verification_agree_on_fixed_and_random_new_builds():
    cases = [full(), full(쿨러={"height_mm": None}), full(파워={"length_mm": None}),
             full(GPU={"power_connector": "2× 8-pin"}, 파워={"pcie_8pin_count": None}),
             full(메인보드={"max_memory_gb": None})]
    cases += [_random_chosen(random.Random(seed)) for seed in range(30)]
    for chosen in cases:
        search, rows, blocking = _three_way(chosen, spec_of())
        assert search == rows == blocking
        assert _pc_required_missing(chosen, spec_of(), RULES, memo={}) == search      # 탐색용 캐시가 결과를 바꾸지 않는다


def test_search_detail_and_verification_agree_on_random_upgrades_with_kept_parts():
    rng = random.Random(2026)
    for _ in range(40):
        pool = _random_chosen(rng)
        buy = rng.sample(SLOTS, rng.randint(1, 4))
        owned = {s: {"name": f"기존 {s}", "specs": dict(pool[s].specs), "source": "text"} for s in SLOTS if s not in buy}
        if rng.random() < 0.3 and owned:                          # 정보가 아예 없는 유지 부품
            owned.pop(rng.choice(sorted(owned)))
        spec = spec_of(tuple(buy), mode="upgrade", owned=owned)
        chosen = {s: pool[s] for s in buy}
        search, rows, blocking = _three_way(chosen, spec)
        assert search == rows == blocking


# ── 재탐색: 부적격 라운드를 채택하지 않는다 ───────────────────────────────────────────

def _record(round_no, confidence, *, eligible, blocking=None, build=None):
    target = VerificationTarget(subject="세트 전체", confidence=confidence, passed=eligible and confidence >= 80,
                                eligible=eligible, blocking=blocking or [])
    return research_loop.RoundRecord(
        round=round_no, build=build or BuildResult(list_id="t", round=round_no),
        verification=VerificationResult(list_id="t", category="computer", mode="set", targets=[target]))


def test_pick_best_prefers_an_eligible_round_over_a_higher_confidence_ineligible_one():
    records = [_record(1, 100, eligible=False), _record(2, 70, eligible=True), _record(3, 90, eligible=False)]
    assert research_loop._pick_best(records).round == 2
    # 같은 적격성이면 신뢰도, 그것도 같으면 앞 라운드
    assert research_loop._pick_best([_record(1, 90, eligible=True), _record(2, 95, eligible=True)]).round == 2
    assert research_loop._pick_best([_record(1, 90, eligible=True), _record(2, 90, eligible=True)]).round == 1


def test_loop_adopts_the_eligible_round_and_marks_nothing_when_one_exists(monkeypatch):
    builds = {1: 100, 2: 70, 3: 95}                               # 라운드별 (신뢰도, 적격): 1·3 부적격, 2 적격
    monkeypatch.setattr(research_loop.stage4_optimize, "run",
                        lambda _r, _s, _l, **kw: BuildResult(list_id="t", round=kw["round_no"]))

    def verify(build, _i):
        return VerificationResult(list_id="t", category="computer", mode="set", targets=[VerificationTarget(
            subject="세트 전체", confidence=builds[build.round], passed=False, eligible=build.round == 2,
            blocking=[] if build.round == 2 else [{"code": "compat_violation", "axis": "socket"}])])

    build, verification, rounds = research_loop.run_set_with_research(
        RankResult(), spec_of(), _noop, verify=verify, choose_exclusion=lambda b, v: ("쿨러", f"k{b.round}", "x"))
    assert build.round == 2 and verification.targets[0].eligible is True
    assert build.eligibility["status"] == "recommendable"


def test_loop_without_any_eligible_round_marks_the_adopted_build_not_recommendable(monkeypatch):
    monkeypatch.setattr(research_loop.stage4_optimize, "run",
                        lambda _r, _s, _l, **kw: BuildResult(list_id="t", round=kw["round_no"]))

    def verify(build, _i):
        return VerificationResult(list_id="t", category="computer", mode="set", targets=[VerificationTarget(
            subject="세트 전체", confidence=95, passed=False, eligible=False,
            blocking=[{"code": "required_info_missing", "axis": "psu_length",
                       "missing": [{"slot": "파워", "key": "length_mm", "side": "purchase"}]}])])

    build, _verification, rounds = research_loop.run_set_with_research(
        RankResult(), spec_of(), _noop, verify=verify, choose_exclusion=None)
    assert len(rounds) == 1
    assert build.eligibility["status"] == "not_recommendable"
    assert build.eligibility["reasons"][0]["code"] == "required_info_missing"
    assert build.eligibility["reasons"][0]["missing"][0]["key"] == "length_mm"      # 사유 보존


def test_loop_keeps_the_eligibility_reasons_build_computer_already_recorded(monkeypatch):
    recorded = elig.make_eligibility([{"code": "budget_exceeded", "axis": "budget"}])
    monkeypatch.setattr(research_loop.stage4_optimize, "run",
                        lambda _r, _s, _l, **kw: BuildResult(list_id="t", round=kw["round_no"], eligibility=recorded))

    def verify(build, _i):
        return VerificationResult(list_id="t", category="computer", mode="set", targets=[VerificationTarget(
            subject="세트 전체", confidence=60, passed=False, eligible=False,
            blocking=[{"code": "budget_exceeded", "axis": "budget"}, {"code": "compat_violation", "axis": "socket"}])])

    build, _v, _r = research_loop.run_set_with_research(RankResult(), spec_of(), _noop, verify=verify, choose_exclusion=None)
    assert build.eligibility == recorded


# ── 사유 코드·안내 문장 ───────────────────────────────────────────────────────────────

def test_build_computer_reports_every_reason_code():
    chosen = full(GPU={"length_mm": 400}, 파워={"length_mm": None})        # 위반(gpu_len) + 필수 누락(psu_length)
    build, _ = build_of({s: [c] for s, c in chosen.items()}, budget=10)       # + 예산 초과
    codes = [r["code"] for r in build.eligibility["reasons"]]
    assert codes == ["compat_violation", "required_info_missing", "budget_exceeded"] or "set" in str(build.link_check)
    assert build.eligibility["status"] == "not_recommendable"
    assert "budget_exceeded" in codes and "required_info_missing" in codes


def test_eligibility_notice_is_code_built_and_only_for_ineligible():
    assert elig.eligibility_notice({"status": "recommendable", "reasons": []}) is None
    notice = elig.eligibility_notice(elig.make_eligibility([
        {"code": "required_info_missing", "axis": "psu_length",
         "missing": [{"slot": "파워", "key": "wattage_w", "side": "owned", "name": "RM750"}]}]))
    assert notice.startswith("정상 추천 조건을 만족하는 구성을 찾지 못해 확인용 구성을 보여 드려요: ")
    assert "쓰고 계신 파워(RM750)의 '파워 용량'" in notice


# ── 설정 검증 ─────────────────────────────────────────────────────────────────────

def _rules_file(tmp_path, mutate):
    import yaml
    from src.engine import stage2_requirement as s2

    data = yaml.safe_load(s2._COMPUTER_RULES_PATH.read_text(encoding="utf-8"))
    mutate(data["verification"]["required_checks"])
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c.update({"warp_drive": {"keys": [{"slot": "CPU", "key": "x"}]}}), "알 수 없는 축"),
    (lambda c: c["socket"].update({"keys": []}), "키 목록이 비어"),
    (lambda c: c["socket"]["keys"].append({"slot": "모니터", "key": "x"}), "슬롯/키"),
    (lambda c: c["socket"]["keys"].append({"slot": "CPU", "key": " "}), "슬롯/키"),
    (lambda c: c["socket"].update({"when": "someday"}), "적용 조건"),
    (lambda c: c["socket"]["keys"].append({"slot": "CPU", "key": "x", "parse": "magic"}), "해석 방식"),
    (lambda c: c.pop("m2"), "빠진 축"),
])
def test_required_checks_loader_rejects_bad_rules(tmp_path, mutate, message):
    from src.engine.stage2_requirement import RequirementRuleError

    with pytest.raises(RequirementRuleError, match=message):
        load_computer_rules(_rules_file(tmp_path, mutate))


def test_removed_data_gap_ranking_key_is_rejected_if_it_comes_back(tmp_path):
    import yaml
    from src.engine import stage2_requirement as s2
    from src.engine.stage2_requirement import RequirementRuleError

    data = yaml.safe_load(s2._COMPUTER_RULES_PATH.read_text(encoding="utf-8"))
    assert "data_gap" not in data["ranking"]
    data["ranking"]["data_gap"] = {"penalty_per_key": 0.1}
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(RequirementRuleError, match="data_gap"):
        load_computer_rules(path)


# ── S_final = S_base ──────────────────────────────────────────────────────────────

def test_score_is_the_plain_clipped_weighted_sum_with_no_gap_penalty():
    import math

    from src.dto import ReviewRequirementProfile, ReviewScoreDetail
    from src.engine import stage3b_rank
    from src.engine.score_policy import AXES, clip01, price_axis

    ranking = load_computer_rules()["ranking"]
    detail = ReviewScoreDetail(profile=ReviewRequirementProfile(profile_version="t", analysis_version="t", part_type="case"), value=0.6)
    # 검사용 스펙이 하나도 없는 케이스와 모두 있는 케이스 — 점수는 같다(가격만 같게 둔다)
    empty = Candidate(product_key="a", slot="케이스", name="a", price=70_000, specs={})
    filled = empty.model_copy(update={"product_key": "b", "specs": BASE["케이스"]})
    a = stage3b_rank._score(empty, 100_000.0, "케이스", review_detail=detail)
    b = stage3b_rank._score(filled, 100_000.0, "케이스", review_detail=detail)
    expected = clip01(math.fsum(ranking["weights"][ax] * v for ax, v in
                                zip(AXES, [price_axis(70_000, 100_000.0), 0.5, 0.6])))
    assert a.score == b.score == pytest.approx(expected, abs=1e-12)


# ── DB: 조합 단계 정보 보완(한 번)·부적격 저장·재검증 ────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
_db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

if DSN:
    import psycopg

    @pytest.fixture()
    def conn():
        connection = psycopg.connect(DSN, prepare_threshold=None, autocommit=True)
        try:
            yield connection
        finally:
            for key in _CACHED_KEYS:
                connection.execute("DELETE FROM catalog.live_spec_lookup_cache WHERE lookup_key=%s", (key,))
            _CACHED_KEYS.clear()
            connection.close()


_CACHED_KEYS: list[str] = []


def _cache_cooling_type(conn, name_key: str, cooling_type: str):
    import json

    _CACHED_KEYS.append(name_key)
    conn.execute(
        "INSERT INTO catalog.live_spec_lookup_cache (lookup_key, query_text, relevant, supported_fields, source_url, fetched_at, status) "
        "VALUES (%s, %s, true, %s::jsonb, 'https://spec.example/cooler', now(), 'unreviewed') "
        "ON CONFLICT (lookup_key) DO UPDATE SET supported_fields=EXCLUDED.supported_fields, relevant=true, status='unreviewed', fetched_at=now()",
        (name_key, name_key, json.dumps({"cooling_type": cooling_type})))


def _strip_cooling_type(monkeypatch):
    """카탈로그의 모든 쿨러에서 냉각 방식(cooling_type)을 지워 조합 단계의 필수 정보 누락을 만든다."""
    from src.repo import catalog_repo

    real = catalog_repo.load_candidates_by_slot_from_db

    def stripped(conn, *a, **k):
        by_slot = real(conn, *a, **k)
        by_slot["쿨러"] = [c.model_copy(update={"specs": {x: y for x, y in c.specs.items() if x != "cooling_type"}})
                          for c in by_slot["쿨러"]]
        return by_slot

    monkeypatch.setattr(catalog_repo, "load_candidates_by_slot_from_db", stripped)


def _count_hardfilter_runs(monkeypatch):
    from src.engine import stage3a_hardfilter

    calls = {"n": 0}
    real = stage3a_hardfilter.run

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(stage3a_hardfilter, "run", counting)
    return calls


def _recommend(conn):
    from src.auth.deps import Principal
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service as rs
    from src.services import session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 2_000_000), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = rs.start_recommendation(conn, revision_id, strategy="default")
    run_id = uuid.UUID(accepted["run_id"])
    rs.execute_recommendation(revision_id, run_id)
    return rs, revision_id, run_id


def _step(conn, run_id):
    from src.repo.engine_repo import EngineRepo

    return EngineRepo(conn).get_run_step(run_id, elig.ELIGIBILITY_STEP)


@_db
@pytest.mark.db
def test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run(conn, monkeypatch):
    _strip_cooling_type(monkeypatch)
    calls = _count_hardfilter_runs(monkeypatch)
    rs, revision_id, run_id = _recommend(conn)

    assert calls["n"] == 1                                             # 채울 값이 없으면 다시 돌지 않는다
    step = _step(conn, run_id)
    assert step["status"] == "not_recommendable" and step["title"] == "추천 적격성"
    assert step["reasons"][0]["code"] == "required_info_missing"
    assert {(m["slot"], m["key"]) for m in step["reasons"][0]["missing"]} == {("쿨러", "cooling_type")}
    assert step["enrichment"]["rerun"] is False and step["enrichment"]["filled"] == 0
    assert step["enrichment"]["attempts"] and all(a["status"] != "filled" for a in step["enrichment"]["attempts"])

    result = rs.get_stored_result(conn, revision_id)
    assert result["status"] == "done" and len(result["items"]) == 8      # 부적격이어도 부품표는 저장한다
    assert result["explanation"]["text"].startswith("정상 추천 조건을 만족하는 구성을 찾지 못해 확인용 구성을 보여 드려요: ")
    assert any(s.get("step") == "추천 적격성" for s in result["reasoning_log"])


@_db
@pytest.mark.db
def test_filled_missing_info_reruns_once_and_becomes_eligible(conn, monkeypatch):
    from src.engine.stage2_requirement import load_computer_rules as load_rules
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    from src.services.live_spec_lookup import normalize_lookup_key

    cooler_names = [c.name for c in load_candidates_by_slot_from_db(conn)["쿨러"]
                    if "air" in str(c.specs.get("cooling_type", "")).lower() and c.specs.get("height_mm")]
    assert cooler_names
    for name in cooler_names:                                              # 공랭 쿨러 전부가 저장소에 있으면 한 번의 재실행으로 풀린다
        _cache_cooling_type(conn, normalize_lookup_key(name), "Air (Single-Tower)")
    _strip_cooling_type(monkeypatch)
    calls = _count_hardfilter_runs(monkeypatch)
    rs, revision_id, run_id = _recommend(conn)
    assert load_rules()

    assert calls["n"] == 2                                              # 한 번 보완하고 한 번만 다시 돈다
    step = _step(conn, run_id)
    assert step["status"] == "recommendable" and step["reasons"] == []
    assert step["enrichment"]["rerun"] is True and step["enrichment"]["filled"] >= 1
    result = rs.get_stored_result(conn, revision_id)
    assert not result["explanation"]["text"].startswith("정상 추천 조건을")


@_db
@pytest.mark.db
def test_reverify_replaces_the_eligibility_step(conn, monkeypatch):
    from src.repo.engine_repo import EngineRepo

    _strip_cooling_type(monkeypatch)
    rs, revision_id, run_id = _recommend(conn)
    assert _step(conn, run_id)["status"] == "not_recommendable"
    before = EngineRepo(conn).get_run_trace(run_id)

    monkeypatch.undo()                                                    # 이제 지금 선택된 부품(실제 카탈로그 값)으로 다시 계산한다
    rs.reverify_set(conn, revision_id, EngineRepo(conn).get_run(run_id))
    step = _step(conn, run_id)
    assert step["status"] == "recommendable" and step["reasons"] == []
    assert step["enrichment"]["attempted"] >= 1                           # 처음 보완 시도 기록은 이어 둔다
    after = EngineRepo(conn).get_run_trace(run_id)
    assert [s["step"] for s in after].count("추천 적격성") == 1 and len(after) == len(before)
