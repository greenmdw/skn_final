"""추천 엔진 정책 고정 시나리오 — DB 없이 메모리 안의 작은 카탈로그로 같은 엔진 흐름을 돌려 기대와 실제를 JSON 으로 남긴다.

    MOCK_MODE=1 PYTHONPATH=. uv run python scripts/engine_policy_scenarios.py --out docs/validation/engine_policy_scenarios_20261013.json

흐름은 비교 스크립트(engine_policy_compare.engine_flow)와 같다: 사전 필터 → 3-B → 4 → 3-C 재탐색, 조합 필수 정보 누락이면 서비스의
`_enrich_combo_missing` 으로 한 번 보완하고 채워졌을 때만 한 번 다시 돈다. 정보 보완은 **대체 조회**(고정 표에서 값을 돌려주는 스텁,
`for_keys` 포함)로 재현한다 — 저장소 조회·웹 검색·LLM 은 연결하지 않는다. 리뷰 근거는 데모와 같은 중립 경로(catalog_source="mock").
시나리오는 회귀 비교용이고, 같은 성질의 정확성은 각 시나리오에 적힌 단위 테스트가 보장한다.
결과가 기대와 다르면 해당 항목에 mismatch: true 를 남긴다(스크립트는 실패 코드로 끝내지 않는다).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("MOCK_MODE") != "1":
    sys.exit("MOCK_MODE=1 환경변수를 명시해야 실행합니다.")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine_policy_compare as compare  # noqa: E402

from src.dto import Candidate  # noqa: E402

STUB_SOURCE = "stub:fixed-table"
CATEGORY = "computer"
NOOP = lambda _m: None  # noqa: E731


# ── 고정 카탈로그 ──────────────────────────────────────────────────────────────────

def _cand(slot: str, key: str, name: str, price: int, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=name, brand="b", price=price,
                     specs={k: v for k, v in specs.items() if v is not None})


def make_catalog() -> dict[str, list[Candidate]]:
    """모든 필수 호환 정보가 있고 서로 맞는 작은 카탈로그(슬롯당 2~3개). 시나리오는 여기서 키를 지우거나 바꾼다."""
    board = dict(socket="AM5", mem_type="DDR5", form_factor="ATX", dimm_slots=4, max_memory_gb=192, m2_slots=3,
                 supported_cpu_family="Ryzen 7000 / 8000G / 9000 계열", max_memory_speed_mts=6400)
    case = dict(supports_form_factors=["ATX", "mATX"], max_gpu_len_mm=350, max_cooler_height_mm=170, expansion_slots=7,
                psu_form_factor="ATX", max_psu_length_mm=200, radiator_front_mm="240;280", radiator_top_mm="240",
                radiator_rear_mm="120")
    psu = dict(form_factor="ATX", length_mm=160, gpu_power_connector="PCIe 8-pin / 12V-2x6", pcie_8pin_count=3,
               connector_12v2x6_count=1)
    gpu = dict(length_mm=300, slot_thickness=2.5, power_connector="1× 8-pin", aux_power="O")
    cooler = dict(cooling_type="Air (Single-Tower)", height_mm=150, supported_socket="AM5/AM4")
    ssd = dict(form_factor="M.2 2280", interface="PCIe 4.0 x4", protocol="NVMe", capacity_gb=1000)
    return {
        # 내장 그래픽·기본 쿨러(원문 O/X): 7600 은 둘 다 있고, 7700X 는 내장 그래픽만(기본 쿨러 없음·TDP 105W), 7500F 는 기본 쿨러만(내장 그래픽 없음).
        "CPU": [_cand("CPU", "cpu:r5-7600", "AMD Ryzen 5 7600", 220_000, socket="AM5", tdp_w=65, max_power_w=88, perf_tier=6,
                      integrated_graphics="O", cooler_included="O (정품 박스 기준)"),
                _cand("CPU", "cpu:r7-7700x", "AMD Ryzen 7 7700X", 330_000, socket="AM5", tdp_w=105, max_power_w=142, perf_tier=7,
                      integrated_graphics="O", cooler_included="X / SKU 확인"),
                _cand("CPU", "cpu:r5-7500f", "AMD Ryzen 5 7500F", 170_000, socket="AM5", tdp_w=65, max_power_w=88, perf_tier=5,
                      integrated_graphics="X", cooler_included="O (정품 박스 기준)")],
        "GPU": [_cand("GPU", "gpu:mid", "GPU Mid", 280_000, power_w=200, perf_tier=6, vram_gb=8, **gpu),
                _cand("GPU", "gpu:good", "GPU Good", 380_000, power_w=250, perf_tier=8, vram_gb=12, **gpu),
                _cand("GPU", "gpu:entry", "GPU Entry", 200_000, power_w=150, perf_tier=4, vram_gb=8, **gpu)],
        "RAM": [_cand("RAM", "ram:kit-16x2", "RAM Kit 16GBx2", 140_000, mem_type="DDR5", module_config="16GB × 2",
                      capacity_gb=32, speed_mts=6000),
                _cand("RAM", "ram:kit-8x2", "RAM Kit 8GBx2", 90_000, mem_type="DDR5", module_config="8GB × 2",
                      capacity_gb=16, speed_mts=6000)],
        "메인보드": [_cand("메인보드", "mb:b650", "Board B650", 120_000, **board),
                  _cand("메인보드", "mb:a620", "Board A620", 90_000, **board)],
        "저장장치": [_cand("저장장치", "ssd:1tb", "SSD 1TB", 80_000, **ssd),
                  _cand("저장장치", "ssd:2tb", "SSD 2TB", 110_000, **{**ssd, "capacity_gb": 2000})],
        "파워": [_cand("파워", "psu:750", "PSU 750", 90_000, wattage_w=750, efficiency_rating="80 Plus Gold", **psu),
               _cand("파워", "psu:850", "PSU 850", 130_000, wattage_w=850, efficiency_rating="80 Plus Platinum", **psu)],
        "케이스": [_cand("케이스", "case:a", "Case A", 50_000, **case), _cand("케이스", "case:b", "Case B", 70_000, **case)],
        "쿨러": [_cand("쿨러", "cooler:a", "Cooler A", 40_000, **cooler), _cand("쿨러", "cooler:b", "Cooler B", 60_000, **cooler)],
    }


def strip(catalog: dict, slot: str, *keys: str, only: set[str] | None = None) -> None:
    """slot 후보(only 가 있으면 그 상품만)의 스펙에서 keys 를 지운다."""
    for i, c in enumerate(catalog[slot]):
        if only is None or c.product_key in only:
            catalog[slot][i] = c.model_copy(update={"specs": {k: v for k, v in c.specs.items() if k not in keys}})


def update(catalog: dict, slot: str, product_key: str | None = None, **specs) -> None:
    """slot 후보(product_key 가 있으면 그 상품만)의 스펙을 덮어쓴다."""
    for i, c in enumerate(catalog[slot]):
        if product_key is None or c.product_key == product_key:
            catalog[slot][i] = c.model_copy(update={"specs": {**c.specs, **specs}})


def owned_parts(**missing_by_slot: tuple[str, ...]) -> dict:
    """업그레이드에서 그대로 쓰는 부품 — 완전한 기준값에서 missing_by_slot 의 키만 뺀다."""
    base = make_catalog()
    out = {}
    for slot in ("CPU", "메인보드", "RAM", "저장장치", "파워", "케이스", "쿨러"):
        specs = dict(base[slot][0].specs)
        if slot == "CPU":
            specs.pop("perf_tier", None)
        for key in missing_by_slot.get(slot, ()):
            specs.pop(key, None)
        out[slot] = {"name": f"기존 {slot}", "specs": specs, "source": "text"}
    return out


# ── 대체 조회(스텁) ────────────────────────────────────────────────────────────────

class StubEnricher:
    """고정 표 {(슬롯, product_key): {키: 값}} 에서 값을 돌려주는 보완 함수 — 사전 필터용 호출과 `for_keys` 를 모두 가진다.
    표에 없거나 값이 없으면 not_found, raise_slots 의 슬롯은 예외(사전 필터가 failed 로 기록한다). 호출은 calls 에 쌓는다."""

    def __init__(self, table: dict | None = None, *, raise_slots: tuple[str, ...] = ()):
        self.table, self.raise_slots = table or {}, raise_slots
        self.calls: list[tuple[str, str, int]] = []

    def _fill(self, slot: str, cand: Candidate, keys: list[str]) -> tuple[Candidate, dict]:
        values = self.table.get((slot, cand.product_key)) or {}
        filled = {k: values[k] for k in keys if k in values}
        record = {"slot": slot, "product_key": cand.product_key, "missing_keys": list(keys), "source": STUB_SOURCE}
        if not filled:
            return cand, {**record, "status": "not_found", "detail": "대체 조회에 값이 없습니다"}
        by_key = {**(cand.provenance.get("by_key") or {}), **{k: STUB_SOURCE for k in filled}}
        out = cand.model_copy(update={"specs": {**cand.specs, **filled}, "provenance": {**cand.provenance, "by_key": by_key}})
        return out, {**record, "status": "filled", "detail": "채움: " + ", ".join(sorted(filled))}

    def __call__(self, slot: str, pending: list[Candidate]):
        from src.engine.stage3a_hardfilter import missing_keys

        self.calls.append(("prefilter", slot, len(pending)))
        if slot in self.raise_slots:
            raise RuntimeError("대체 조회 실패")
        results = [self._fill(slot, c, missing_keys(c)) for c in pending]
        return [c for c, _ in results], [a for _, a in results]

    def for_keys(self, slot: str, requests: list[tuple[Candidate, list[str]]]):
        self.calls.append(("combo", slot, len(requests)))
        results = [self._fill(slot, c, list(keys)) for c, keys in requests]
        return [c for c, _ in results], [a for _, a in results]

    def count(self, kind: str) -> int:
        return sum(1 for k, _, _ in self.calls if k == kind)


# ── 실행 ───────────────────────────────────────────────────────────────────────────

# 기본 입력(사무 150만 원)은 GPU·쿨러를 원하는 부품으로 지정해 8개 슬롯을 모두 사는 구성으로 둔다 — computer-rules-v14 부터 사무 배분의
# GPU·쿨러가 0% 라 지정하지 않으면 두 슬롯이 견적에서 빠지는데(s17~), 시나리오 01~16 은 8개 슬롯 조합의 필수 정보·후보 판정을 보는 것이라
# 같은 구성을 유지한다(결정 D2: 원하는 부품으로 GPU 를 지정하면 GPU 가 돌아오고 기본 배분의 비율을 빌린다).
FULL_SET_VALUES = {"wanted_parts": {"GPU": {}, "쿨러": {}}}


def make_inputs(*, upgrade: bool = False, owned: dict | None = None, speed_min: int | None = None, values: dict | None = None):
    from src.categories import load_category
    from src.engine import stage2_requirement
    from src.engine.slots import slots_from_conditions

    cat_def = load_category(CATEGORY)
    if values is not None:
        values = {"category": CATEGORY, **values}
    elif upgrade:
        values = {"category": CATEGORY, "mode": "upgrade", "purpose": "game", "budget_max": 2_000_000, "upgrade_parts": ["GPU"]}
    else:
        values = {"category": CATEGORY, "mode": "build", "purpose": "office", "budget_max": 1_500_000, **FULL_SET_VALUES}
    slots = slots_from_conditions(CATEGORY, cat_def, values)
    spec = stage2_requirement.run(slots, cat_def, NOOP)
    if owned is not None:
        from src.engine.owned_parts import constrain_targets
        spec.owned = owned
        constrain_targets(spec)
    if speed_min is not None:
        spec.targets["RAM"]["speed_mts_min"] = speed_min
    return slots, spec


def run_flow(catalog: dict, *, enricher, upgrade: bool = False, owned: dict | None = None, speed_min: int | None = None,
             values: dict | None = None) -> dict:
    """한 케이스의 엔진 실행 → 요약(actual). 사전 필터 후보 부족은 outcome=candidate_shortage 로 요약한다."""
    from src.engine import feasibility as feasibility_engine
    from src.engine.stage3a_hardfilter import CandidateShortage

    slots, spec = make_inputs(upgrade=upgrade, owned=owned, speed_min=speed_min, values=values)
    feasibility = feasibility_engine.assess(spec, catalog)
    spec.budget["feasibility"] = feasibility["level"]
    spec.budget["feasibility_detail"] = feasibility
    try:
        flow = compare.engine_flow(spec, slots, catalog, enricher=enricher, conn=None, catalog_source="mock")
    except CandidateShortage as exc:
        return {"outcome": "candidate_shortage", "shortage": {s: {"pending_reasons": dict(sorted(i["pending_reasons"].items())),
                                                                 "fail_reasons": dict(sorted(i["fail_reasons"].items()))}
                                                             for s, i in sorted(exc.slots.items())},
                "prefilter_enrichment": _count_by([a["status"] for a in exc.enrichment]),
                "stub_calls": _stub_calls(enricher)}
    fields = compare.flow_fields(flow, frozenset())
    elig = fields["build"]["eligibility"]
    reasons = elig["reasons"]
    target = fields["verification"][0] if fields["verification"] else {}
    actual = {
        "outcome": elig["status"],
        "reason_codes": sorted(r["code"] for r in reasons),
        "axes": sorted({a for r in reasons for a in r.get("axes") or []}),
        "missing": sorted(f"{m.get('side')}:{m['slot']}.{m['key']}" for r in reasons for m in r.get("missing") or []),
        "selected": {i["slot"]: i["product_key"] for i in fields["build"]["items"]},
        "pass_counts": {s: st["pass"] for s, st in fields["hardfilter"].items()},
        "fail_counts": {s: st["fail"] for s, st in fields["hardfilter"].items()},
        "pending_counts": {s: st["pending"] for s, st in fields["hardfilter"].items()},
        "prefilter_enrichment": _count_by([a["status"] for a in fields["enrichment"]]),
        "returned_to_pass": sum(1 for a in fields["enrichment"] if a["returned_to_pass"]),
        "combo": ({"attempted": flow.combo["attempted"], "filled": flow.combo["filled"], "rerun": flow.combo["rerun"]}
                  if flow.combo else None),
        "passes": flow.passes,
        "stub_calls": _stub_calls(enricher),
        "confidence": target.get("confidence"), "passed": target.get("passed"), "eligible": target.get("eligible"),
        "counters": {k: v for k, v in fields["build"]["alternatives"].items() if k.startswith(("pruned_", "widened", "capped"))},
        "margins": {k: ({"status": v["status"]} | ({"reason": v["reason"]} if "reason" in v else {})
                        | ({"cpu_basis": v["cpu_basis"]} if "cpu_basis" in v else {}))
                    for k, v in (fields["build"]["margins"] or {}).items()},
        "items": {i["slot"]: {k: i[k] for k in ("price", "qty", "unit_price") if k in i} for i in fields["build"]["items"]},
        "totals_price": fields["build"]["totals"].get("price"),
        "omitted_slots": dict(spec.omitted_slots),
        "borrowed_alloc": {slot: dict(info) for slot, info in (spec.budget.get("borrowed_alloc") or {}).items()},
        "alloc": {slot: round(v, 4) for slot, v in spec.budget.get("alloc", {}).items()},
        "cpu_target_flags": sorted(k for k in spec.targets.get("CPU", {}) if k.endswith("_required")),
        "_flow": flow,
    }
    return actual


def _count_by(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _stub_calls(enricher) -> dict | None:
    return {"prefilter": enricher.count("prefilter"), "combo": enricher.count("combo")} if isinstance(enricher, StubEnricher) else None


def matches(expected: dict, actual: dict) -> bool:
    """expected 의 각 키가 actual 과 맞는가. 키 규칙: `x_min`=actual[x] 이상 · `x_has`=actual[x] 가 그 항목들을 모두 포함 ·
    `x_sub`=dict 부분 일치 · 그 밖에는 같아야 한다."""
    for key, want in expected.items():
        if key.endswith("_min"):
            got = actual.get(key[:-4])
            if got is None or got < want:
                return False
        elif key.endswith("_has"):
            got = actual.get(key[:-4]) or []
            if not set(want) <= set(got):
                return False
        elif key.endswith("_sub"):
            got = actual.get(key[:-4]) or {}
            if any(got.get(k) != v for k, v in want.items()):
                return False
        elif actual.get(key) != want:
            return False
    return True


def case(name: str, expected: dict, actual: dict) -> dict:
    shown = {k: v for k, v in actual.items() if not k.startswith("_")}
    return {"name": name, "expected": expected, "actual": shown, "mismatch": not matches(expected, actual)}


def scenario(sid: str, title: str, description: str, tests: list[str], cases: list[dict]) -> dict:
    return {"id": sid, "title": title, "description": description, "tests": tests, "cases": cases,
            "mismatch": any(c["mismatch"] for c in cases)}


# ── 시나리오 ───────────────────────────────────────────────────────────────────────

def s01():
    cat = make_catalog()
    strip(cat, "케이스", "max_psu_length_mm", only={"case:a"})       # 싼 쪽 케이스만 필수 정보 누락
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("01", "일부 후보의 필수 정보 누락", "더 싼 케이스 A 에 허용 파워 길이가 없다. 정보가 있는 케이스 B 로 정상 추천해야 한다.",
                    ["tests/test_combo_eligibility.py::test_search_skips_combos_missing_required_info_and_counts_the_pruning"],
                    [case("케이스 A 만 누락", {"outcome": "recommendable", "selected_sub": {"케이스": "case:b"}, "passes": 1}, a)])


def s02():
    cat = make_catalog()
    strip(cat, "케이스", "max_psu_length_mm")
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("02", "모든 후보의 같은 필수 정보 누락", "모든 케이스에 허용 파워 길이가 없다. 검사를 생략해 추천하지 않고 부적격 사유(필수 정보 누락)를 낸다.",
                    ["tests/test_combo_eligibility.py::test_required_key_empty_for_every_candidate_is_still_checked",
                     "tests/test_combo_eligibility.py::test_a_slot_blocked_for_every_candidate_skips_the_search_entirely"],
                    [case("모든 케이스 누락(보완 값 없음)", {"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"],
                                                          "axes_has": ["psu_length"], "missing_has": ["purchase:케이스.max_psu_length_mm"]}, a)])


def s03():
    cat = make_catalog()
    update(cat, "GPU", "gpu:mid", perf_tier=2)                      # 요구 등급 3 미만 2개, 통과 1개
    update(cat, "GPU", "gpu:entry", perf_tier=1)
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("03", "Pass 소수", "GPU 3개 중 1개만 요구 등급을 넘는다. Fail 후보를 끌어올리지 않고 그 하나로 추천한다.",
                    ["tests/test_candidate_eligibility.py::test_single_pass_does_not_promote_pending_into_keep"],
                    [case("GPU Pass 1개", {"outcome": "recommendable", "selected_sub": {"GPU": "gpu:good"},
                                           "pass_counts_sub": {"GPU": 1}, "fail_counts_sub": {"GPU": 2}}, a)])


def s04():
    out = []
    for name, enricher in (("보완 조회에 값 없음", StubEnricher()), ("보완 경로 없음", None)):
        cat = make_catalog()
        strip(cat, "GPU", "perf_tier")
        a = run_flow(cat, enricher=enricher)
        want = {"outcome": "candidate_shortage", "shortage_sub": {"GPU": {"pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 3},
                                                                          "fail_reasons": {}}}}
        want["prefilter_enrichment"] = {"not_found": 3} if enricher is not None else {"no_path": 3}
        out.append(case(name, want, a))
    return scenario("04", "전부 Pending", "GPU 모두 성능 등급이 없다. 보완 값이 없으면 승격 없이 후보 부족으로 끝난다.",
                    ["tests/test_candidate_eligibility.py::test_all_pending_without_enrich_is_shortage_with_no_path_records",
                     "tests/test_candidate_eligibility.py::test_not_found_keeps_candidate_held"], out)


def s05():
    cat = make_catalog()
    for key in ("gpu:mid", "gpu:good", "gpu:entry"):
        update(cat, "GPU", key, perf_tier=1)
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("05", "전부 Fail", "GPU 모두 요구 등급 미달이다. 승격 없이 후보 부족이고 보완 호출도 없다.",
                    ["tests/test_candidate_eligibility.py::test_all_fail_is_shortage_without_promotion_and_counts_fail_prefixes"],
                    [case("GPU 전부 등급 미달", {"outcome": "candidate_shortage",
                                                 "shortage_sub": {"GPU": {"pending_reasons": {}, "fail_reasons": {"FAIL_PERF_BELOW": 3}}},
                                                 "stub_calls": {"prefilter": 0, "combo": 0}}, a)])


def s06():
    cat = make_catalog()
    strip(cat, "CPU", "max_power_w")                                   # 최대 전력이 없으면 TDP 로 대체(누락 아님)
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("06", "선택적 정보만 부족", "CPU 최대 전력이 없어 TDP 로 대체한다. 기타 부하 근거·냉각 시험 자료가 없어 전체 전력·냉각 여유는 확인 불가이지만 적격이다.",
                    ["tests/test_build_margins.py::test_missing_max_power_falls_back_to_tdp_and_records_the_limit",
                     "tests/test_build_margins.py::test_total_is_unavailable_without_a_documented_other_load_and_keeps_the_known_load",
                     "tests/test_build_margins.py::test_cooling_is_always_unavailable_with_inputs_and_no_tdp_difference_value"],
                    [case("TDP 대체·여유 확인 불가", {"outcome": "recommendable",
                                                 "margins_sub": {"power.compat_check": {"status": "available", "cpu_basis": "tdp_fallback"},
                                                                 "power.total": {"status": "unavailable", "reason": "other_load_basis_missing"},
                                                                 "cooling": {"status": "unavailable", "reason": "no_comparable_thermal_test"}}}, a)])


def s07():
    cat = make_catalog()
    strip(cat, "쿨러", "cooling_type")
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("07", "조합 필수 정보만 부족", "사전 필터는 모든 쿨러를 통과시키지만(냉각 방식은 필터 조건이 아님) 조합에서 공랭/수랭을 알 수 없어 필수 정보 누락이다. 보완은 한 번 시도하고 값이 없으면 다시 돌지 않는다.",
                    ["tests/test_combo_eligibility.py::test_cooling_type_unknown_is_itself_the_missing_key",
                     "tests/test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run"],
                    [case("쿨러 냉각 방식 누락", {"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"],
                                                "pass_counts_sub": {"쿨러": 2}, "passes": 1,
                                                "combo_sub": {"filled": 0, "rerun": False}}, a)])


def s08():
    cat = make_catalog()
    strip(cat, "케이스", "max_psu_length_mm")
    a = run_flow(cat, enricher=StubEnricher())
    return scenario("08", "검증 신뢰도 통과지만 필수 호환 미확인", "신뢰도는 기준(80) 이상인데 필수 호환 정보가 빠져 적격이 아니다. passed 는 거짓이다.",
                    ["tests/test_combo_eligibility.py::test_required_missing_blocks_even_when_the_penalty_accounting_is_quiet",
                     "tests/test_combo_eligibility.py::test_single_violation_at_confidence_80_is_not_passed_and_not_eligible"],
                    [case("신뢰도 ≥ 80, 부적격", {"outcome": "not_recommendable", "confidence_min": 80, "passed": False, "eligible": False}, a)])


def s09():
    cat = make_catalog()
    strip(cat, "GPU", "perf_tier")
    table = {("GPU", k): {"perf_tier": t} for k, t in (("gpu:mid", 6), ("gpu:good", 8), ("gpu:entry", 4))}
    a = run_flow(cat, enricher=StubEnricher(table))
    cat_b = make_catalog()
    strip(cat_b, "케이스", "max_psu_length_mm")
    stub = StubEnricher({("케이스", "case:a"): {"max_psu_length_mm": 200}, ("케이스", "case:b"): {"max_psu_length_mm": 200}})
    b = run_flow(cat_b, enricher=stub)
    return scenario("09", "정보 보완 후 복귀", "(a) 사전 필터: Pending GPU 의 성능 등급을 대체 조회가 채워 Pass 로 복귀한다(GPU Entry 는 채워진 등급 4가 요구 3 이상). (b) 조합: 허용 파워 길이를 채운 뒤 한 번 다시 돌아 적격이 된다.",
                    ["tests/test_candidate_eligibility.py::test_enrichment_that_fills_the_missing_key_returns_the_candidate_to_pass_and_it_is_scored",
                     "tests/test_combo_eligibility.py::test_filled_missing_info_reruns_once_and_becomes_eligible"],
                    [case("사전 필터 보완 복귀", {"outcome": "recommendable", "prefilter_enrichment": {"filled": 3}, "returned_to_pass": 3,
                                                  "pass_counts_sub": {"GPU": 3}, "pending_counts_sub": {"GPU": 0}}, a),
                     case("조합 보완 뒤 재실행", {"outcome": "recommendable", "passes": 2,
                                                  "combo_sub": {"filled": 2, "rerun": True}}, b)])


def s10():
    cat = make_catalog()
    strip(cat, "GPU", "perf_tier")
    a = run_flow(cat, enricher=StubEnricher())
    cat_b = make_catalog()
    strip(cat_b, "GPU", "perf_tier")
    b = run_flow(cat_b, enricher=StubEnricher(raise_slots=("GPU",)))
    cat_c = make_catalog()
    strip(cat_c, "케이스", "max_psu_length_mm")
    c = run_flow(cat_c, enricher=StubEnricher())
    return scenario("10", "보완 실패(not_found)", "(a) 사전 필터에서 값을 못 찾으면 보류가 유지되어 후보 부족. (b) 조회가 예외를 내도 추천 전체가 죽지 않고 failed 로 기록한 뒤 후보 부족. (c) 조합 단계에서 값을 못 찾으면 다시 돌지 않고 진단 결과만 낸다.",
                    ["tests/test_candidate_eligibility.py::test_not_found_keeps_candidate_held",
                     "tests/test_candidate_eligibility.py::test_enrich_exception_is_recorded_as_failed_and_not_retried",
                     "tests/test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run"],
                    [case("사전 필터 not_found", {"outcome": "candidate_shortage", "prefilter_enrichment": {"not_found": 3}}, a),
                     case("조회 예외", {"outcome": "candidate_shortage", "prefilter_enrichment": {"failed": 3},
                                      "stub_calls": {"prefilter": 1, "combo": 0}}, b),
                     case("조합 not_found", {"outcome": "not_recommendable", "passes": 1, "combo_sub": {"filled": 0, "rerun": False}}, c)])


def s11():
    cat = make_catalog()
    strip(cat, "케이스", "max_psu_length_mm", "expansion_slots")     # 케이스 두 값이 비어 있고 조회는 한 값만 채운다
    stub = StubEnricher({("케이스", "case:a"): {"max_psu_length_mm": 200}, ("케이스", "case:b"): {"max_psu_length_mm": 200}})
    a = run_flow(cat, enricher=stub)
    return scenario("11", "보완 한도(조합 재실행 1회)", "조합 보완은 한 번만 시도하고, 채워진 값이 있어 한 번 다시 돈다. 재실행 뒤에도 남은 누락(확장 슬롯 수)은 더 시도하지 않고 부적격으로 끝난다.",
                    ["tests/test_combo_eligibility.py::test_filled_missing_info_reruns_once_and_becomes_eligible",
                     "tests/test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run"],
                    [case("부분 보완 뒤에도 누락", {"outcome": "not_recommendable", "passes": 2, "combo_sub": {"rerun": True},
                                                "stub_calls": {"prefilter": 0, "combo": 1}, "missing_has": ["purchase:케이스.expansion_slots"]}, a)])


def s12():
    complete = run_flow(make_catalog(), enricher=StubEnricher(), upgrade=True, owned=owned_parts())
    no_watt = run_flow(make_catalog(), enricher=StubEnricher(), upgrade=True, owned=owned_parts(파워=("wattage_w",)))
    no_len = run_flow(make_catalog(), enricher=StubEnricher(), upgrade=True, owned=owned_parts(케이스=("max_gpu_len_mm",)))
    return scenario("12", "업그레이드 유지 부품 필수 누락(D2)", "GPU 만 바꾸는 업그레이드에서 유지 파워의 정격 출력·유지 케이스의 GPU 허용 길이가 없으면 구매 부품과 같은 기준으로 보류한다(유지 부품은 입력 때 이미 확인한 값이라 조합 단계에서 다시 보완하지 않는다).",
                    ["tests/test_combo_eligibility.py::test_upgrade_kept_psu_without_wattage_holds_the_combo_and_names_the_owned_part",
                     "tests/test_combo_eligibility.py::test_upgrade_kept_case_without_gpu_length_holds_but_a_known_length_is_fine",
                     "tests/test_combo_eligibility.py::test_upgrade_with_every_needed_kept_part_value_is_eligible"],
                    [case("유지 부품 정보 완전", {"outcome": "recommendable"}, complete),
                     case("유지 파워 정격 출력 없음", {"outcome": "not_recommendable", "missing_has": ["owned:파워.wattage_w"],
                                                  "combo_sub": {"filled": 0, "rerun": False}}, no_watt),
                     case("유지 케이스 GPU 허용 길이 없음", {"outcome": "not_recommendable", "missing_has": ["owned:케이스.max_gpu_len_mm"]}, no_len)])


def s13():
    need_two = make_catalog()
    for g in ("gpu:mid", "gpu:good", "gpu:entry"):
        update(need_two, "GPU", g, power_connector="2× 8-pin")
    missing = make_catalog()
    for g in ("gpu:mid", "gpu:good", "gpu:entry"):
        update(missing, "GPU", g, power_connector="2× 8-pin")
    strip(missing, "파워", "pcie_8pin_count")
    a = run_flow(missing, enricher=StubEnricher())
    short = make_catalog()
    for g in ("gpu:mid", "gpu:good", "gpu:entry"):
        update(short, "GPU", g, power_connector="2× 8-pin")
    update(short, "파워", pcie_8pin_count=1)
    b = run_flow(short, enricher=StubEnricher())
    none = make_catalog()
    for g in ("gpu:mid", "gpu:good", "gpu:entry"):
        update(none, "GPU", g, power_connector="슬롯 전력", aux_power="X")
    strip(none, "파워", "gpu_power_connector", "pcie_8pin_count", "connector_12v2x6_count")
    c = run_flow(none, enricher=StubEnricher())
    return scenario("13", "GPU 커넥터 개수", "실제 연결 경로(2× 8-pin)에 필요한 개수 정보가 없으면 보류, 확인된 개수 부족은 호환 위반, 보조 전원이 필요 없으면 종류·개수 정보 없이도 적격이다.",
                    ["tests/test_combo_eligibility.py::test_connector_count_missing_on_the_needed_path_is_required_missing",
                     "tests/test_combo_eligibility.py::test_confirmed_connector_shortage_is_a_violation_not_a_gap",
                     "tests/test_combo_eligibility.py::test_gpu_without_aux_power_makes_connector_checks_not_applicable"],
                    [case("필요 개수 정보 누락(보류)", {"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"],
                                                    "missing_has": ["purchase:파워.pcie_8pin_count"]}, a),
                     case("확인된 부족(탈락)", {"outcome": "not_recommendable", "reason_codes_has": ["compat_violation"],
                                             "axes_has": ["gpu_connector"]}, b),
                     case("보조 전원 불필요(비적용)", {"outcome": "recommendable"}, c)])


def s14():
    def with_cpu(speed, ram_speed=None):
        cat = make_catalog()
        if speed is not None:
            update(cat, "CPU", max_memory_speed_mts=speed)
        if ram_speed is not None:
            update(cat, "RAM", speed_mts=ram_speed)
        return cat

    unknown = run_flow(with_cpu(None), enricher=StubEnricher(), speed_min=6000)
    unmet = run_flow(with_cpu(6400, ram_speed=4800), enricher=StubEnricher(), speed_min=6000)
    met = run_flow(with_cpu(6400), enricher=StubEnricher(), speed_min=6000)
    plain = run_flow(with_cpu(None), enricher=StubEnricher())
    return scenario("14", "사용자 필수 RAM 속도", "사용자가 RAM 속도 6000 이상을 요구하면 CPU·보드·RAM 지원 속도의 근거가 필요하다: 미확인은 보류, 확인된 미달은 요구 미충족, 충족은 적격. 요구가 없으면 속도 정보 없음이 필수 누락이 아니다.",
                    ["tests/test_combo_eligibility.py::test_ram_speed_user_requirement_needs_cpu_supported_speed",
                     "tests/test_combo_eligibility.py::test_ram_speed_confirmed_shortfall_is_requirement_unmet_even_if_something_else_is_missing",
                     "tests/test_combo_eligibility.py::test_ram_speed_user_requirement_met_when_all_three_support_it",
                     "tests/test_combo_eligibility.py::test_ram_speed_without_user_requirement_keeps_the_existing_caution_and_is_not_required"],
                    [case("CPU 지원 속도 미확인(보류)", {"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"],
                                                    "axes_has": ["ram_speed"], "missing_has": ["purchase:CPU.max_memory_speed_mts"]}, unknown),
                     case("RAM 속도 미달", {"outcome": "not_recommendable", "reason_codes_has": ["requirement_unmet"]}, unmet),
                     case("충족", {"outcome": "recommendable"}, met),
                     case("요구 없음(CPU 속도 미확인)", {"outcome": "recommendable"}, plain)])


def s15():
    from src.engine.score_policy import AXES, clip01
    from src.services.fit_score import avg_fit, display_points, fit_for_item

    weights = {"가격": 0.45, "성능": 0.30, "리뷰": 0.25}
    axes = {"가격": 0.8, "성능": 0.5, "리뷰": 0.61796}          # 가중합 ≈ 0.66449
    raw = clip01(math.fsum(weights[a] * axes[a] for a in AXES))
    stored = round(raw, 4)                                       # numeric(8,4) 저장값
    snapshot = {"candidates": {"v1": {"slot": "GPU", "product_id": "p1", "variant_id": "v1", "rank_score": raw,
                                      "rank_breakdown": axes, "rank_weights": weights, "score_method": "pc-fit-v4"}}}
    versions = {"pipeline": "computer-v1", "computer_rules": "computer-rules-v14", "score_method": "pc-fit-v4"}
    fit = fit_for_item(snapshot, versions, variant_id="v1", product_id="p1", slot="GPU")
    avg = avg_fit(snapshot, versions, [{"variant_id": "v1", "product_id": "p1", "slot": "GPU"}])
    missing = fit_for_item(None, versions, variant_id="v1", product_id="p1", slot="GPU")
    legacy = fit_for_item(snapshot, {"pipeline": "computer-v1"}, variant_id="v1", product_id="p1", slot="GPU")
    actual = {"raw": raw, "stored_four_digits": stored, "display_from_raw": fit["score"], "avg_fit": avg["score"],
              "display_from_stored_value_would_be": display_points(stored),
              "status_without_snapshot": missing["status"], "status_legacy_run": legacy["status"],
              "policy_examples": {"0.665": display_points(0.665), "0.605": display_points(0.605)}}
    expected = {"display_from_raw": 66.4, "avg_fit": 66.4, "stored_four_digits": 0.6645,
                "display_from_stored_value_would_be": 66.5, "status_without_snapshot": "unavailable",
                "status_legacy_run": "legacy_method", "policy_examples_sub": {"0.665": 66.5, "0.605": 60.5}}
    return scenario("15", "원본 점수 저장·표시 경계", "원본 0.66449 는 66.4점으로 한 번만 반올림한다. DB 네 자리 값 0.6645 로 66.5점을 만들지 않는다(참고로 저장값을 표시 원본으로 쓰면 66.5가 된다). snapshot 이 없으면 unavailable, 옛 방식 run 은 legacy_method.",
                    ["tests/test_fit_score.py::test_display_points_boundaries",
                     "tests/test_fit_score.py::test_raw_066449_shows_664_in_api_and_explanation_never_665",
                     "tests/test_fit_score.py::test_snapshot_missing_or_invalid_is_unavailable_never_the_stored_score"],
                    [case("0.66449 경계", expected, actual)])


def s16():
    cat = make_catalog()
    cat["RAM"] = [_cand("RAM", "ram:single-16", "RAM Single 16GB", 60_000, mem_type="DDR5", module_config="16GB × 1",
                        capacity_gb=16, speed_mts=6000),
                  _cand("RAM", "ram:kit-16x2", "RAM Kit 16GBx2", 140_000, mem_type="DDR5", module_config="16GB × 2",
                        capacity_gb=32, speed_mts=6000)]
    a = run_flow(cat, enricher=StubEnricher())
    flow = a["_flow"]
    pass_ram = {c.product_key: {"price": c.price, "capacity_gb": c.specs.get("capacity_gb"), "purchase_qty": c.purchase_qty,
                                "unit_price": c.unit_price} for c in flow.hf.slots["RAM"]}
    item = a["items"]["RAM"]
    actual = {**{k: v for k, v in a.items() if not k.startswith("_")},
              "ram_pass_pool": dict(sorted(pass_ram.items())), "ram_item": item,
              "items_price_sum": sum(i["price"] for i in a["items"].values())}
    return scenario("16", "RAM 단품 2개 구성 가격·용량", "단품 16GB(6만 원)는 2개 구성으로 12만 원·32GB 로 판정되어 14만 원 키트보다 싸다. 선택되면 가격은 구성 전체(12만 원)로 한 번만 합산되고 qty=2·개당 6만 원이 남는다. 키트에 2를 곱하지 않는다.",
                    ["tests/test_ram_pair_config.py::test_single_module_becomes_two_modules_without_touching_the_original",
                     "tests/test_ram_pair_config.py::test_as_pair_is_idempotent_so_price_and_capacity_are_never_summed_twice",
                     "tests/test_ram_pair_config.py::test_stage4_items_carry_qty_and_unit_price_and_totals_sum_the_pair_price"],
                    [case("단품 선택·중복 합산 없음", {
                        "outcome": "recommendable", "selected_sub": {"RAM": "ram:single-16"},
                        "ram_pass_pool_sub": {"ram:single-16": {"price": 120_000, "capacity_gb": 32, "purchase_qty": 2, "unit_price": 60_000},
                                              "ram:kit-16x2": {"price": 140_000, "capacity_gb": 32, "purchase_qty": 1, "unit_price": 140_000}},
                        "ram_item_sub": {"price": 120_000, "qty": 2, "unit_price": 60_000},
                        "totals_price": actual["items_price_sum"]}, actual | {"totals_price": a["totals_price"]})])


OFFICE = {"mode": "build", "purpose": "office", "budget_max": 1_500_000}


def s17():
    a = run_flow(make_catalog(), enricher=StubEnricher(), values=OFFICE)
    return scenario("17", "GPU·쿨러 미구매(사무 신규 조립)", "사무 배분의 GPU·쿨러가 0% 라 두 슬롯이 견적에서 빠지고 CPU 가 내장 그래픽·정품 박스 기본 쿨러(TDP 65W 이하)를 갖춰야 한다. "
                    "고정 카탈로그에서는 7600 만 둘 다 갖춰(7700X 는 기본 쿨러 없음, 7500F 는 내장 그래픽 없음) 그것이 선택된다. 6개 슬롯 견적이 정상 추천되고 위반·필수 정보 누락이 없다.",
                    ["tests/test_gpu_cooler_omission.py::test_office_build_omits_gpu_and_cooler_and_flags_the_cpu_target",
                     "tests/test_gpu_cooler_omission.py::test_omitted_slots_do_not_create_required_info_missing_or_set_violation"],
                    [case("사무 기본 — GPU·쿨러 제외", {
                        "outcome": "recommendable", "omitted_slots": {"GPU": "integrated_graphics", "쿨러": "box_cooler"},
                        "cpu_target_flags": ["box_cooler_required", "integrated_graphics_required"],
                        "selected_sub": {"CPU": "cpu:r5-7600"}, "pass_counts_sub": {"CPU": 1}, "fail_counts_sub": {"CPU": 2},
                        "borrowed_alloc": {}, "margins_sub": {"power.compat_check": {"status": "available", "cpu_basis": "max_power"},
                                                              "size.gpu_slots": {"status": "not_applicable", "reason": "omitted_slot"}}},
                         a | {"selected_has_no_gpu_cooler": not ({"GPU", "쿨러"} & set(a.get("selected", {})))}),
                     case("선택 부품에 GPU·쿨러 없음", {"selected_has_no_gpu_cooler": True}, {"selected_has_no_gpu_cooler": not ({"GPU", "쿨러"} & set(a.get("selected", {})))})])


def _uniform_cpus(**override) -> dict:
    """세 CPU 가 모두 같은 내장 그래픽·기본 쿨러·TDP(전부 Pass 하는 값)를 갖게 한 카탈로그 — override 한 값만 다르게 해 사유 코드를 하나씩 본다."""
    cat = make_catalog()
    update(cat, "CPU", **{"integrated_graphics": "O", "cooler_included": "O (정품 박스 기준)", "tdp_w": 65, **override})
    return cat


def s18():
    pending = _uniform_cpus()
    strip(pending, "CPU", "integrated_graphics", "cooler_included")
    cases = []
    for name, cat, want in (
            ("내장 그래픽 전부 X", _uniform_cpus(integrated_graphics="X"), {"fail_reasons": {"FAIL_NO_INTEGRATED_GRAPHICS": 3}, "pending_reasons": {}}),
            ("기본 쿨러 전부 X", _uniform_cpus(cooler_included="X / SKU 확인"), {"fail_reasons": {"FAIL_NO_BOX_COOLER": 3}, "pending_reasons": {}}),
            ("TDP 허용 초과", _uniform_cpus(tdp_w=105), {"fail_reasons": {"FAIL_BOX_COOLER_TDP": 3}, "pending_reasons": {}}),
            ("값 없음 → Pending(승격 없음)", pending, {"fail_reasons": {},
                                                  "pending_reasons": {"PENDING_SPEC_MISSING:integrated_graphics": 3,
                                                                      "PENDING_SPEC_MISSING:cooler_included": 3}}),
            ("읽을 수 없는 값 → Pending", _uniform_cpus(integrated_graphics="확인불가", cooler_included=""),
             {"fail_reasons": {}, "pending_reasons": {"PENDING_SPEC_MISSING:integrated_graphics": 3,
                                                     "PENDING_SPEC_MISSING:cooler_included": 3}})):
        a = run_flow(cat, enricher=StubEnricher(), values=OFFICE)
        cases.append(case(name, {"outcome": "candidate_shortage", "shortage_sub": {"CPU": want}}, a))
    return scenario("18", "내장 그래픽·기본 쿨러 CPU 후보 없음", "CPU 가 내장 그래픽·기본 쿨러(허용 TDP 이하)를 대신하지 못하면 Fail, 값이 없거나 읽을 수 없으면 Pending. "
                    "어느 쪽이든 통과 CPU 가 없으면 자동 승격 없이 후보 부족으로 끝난다(Pending 은 보완 조회에 값이 없으면 그대로).",
                    ["tests/test_gpu_cooler_omission.py::test_cpu_filter_reason_codes",
                     "tests/test_gpu_cooler_omission.py::test_no_qualifying_cpu_is_candidate_shortage_without_promotion"], cases)


def s19():
    gpu = run_flow(make_catalog(), enricher=StubEnricher(), values={**OFFICE, "wanted_parts": {"GPU": {"fields": {}}}})
    quiet = run_flow(make_catalog(), enricher=StubEnricher(), values={**OFFICE, "priority": "quiet"})
    noise = run_flow(make_catalog(), enricher=StubEnricher(), values={**OFFICE, "noise_sensitive": True})
    return scenario("19", "GPU·쿨러를 다시 넣는 경우(D2·D4)", "원하는 부품(wanted_parts)에 GPU 가 있으면 GPU 슬롯이, 저소음 우선·소음 민감이면 쿨러 슬롯이 돌아온다. "
                    "돌아온 슬롯은 기본 배분의 비율을 빌려 합 1 로 다시 정규화하고 빌린 비율·이유를 남긴다. 다른 슬롯(쿨러/GPU)은 여전히 빠진다.",
                    ["tests/test_gpu_cooler_omission.py::test_wanted_gpu_brings_the_gpu_slot_back_and_borrows_the_base_ratio",
                     "tests/test_gpu_cooler_omission.py::test_quiet_priority_or_noise_sensitive_keeps_the_cooler"],
                    [case("D2 원하는 부품에 GPU", {"outcome": "recommendable", "omitted_slots": {"쿨러": "box_cooler"},
                                                   "borrowed_alloc": {"GPU": {"ratio": 0.37, "reason": "wanted_part"}},
                                                   "cpu_target_flags": ["box_cooler_required"], "alloc_sum": 1.0}, gpu | _alloc_sum(gpu)),
                     case("D4 저소음 우선", {"outcome": "recommendable", "omitted_slots": {"GPU": "integrated_graphics"},
                                           "borrowed_alloc": {"쿨러": {"ratio": 0.01, "reason": "quiet_priority"}},
                                           "cpu_target_flags": ["integrated_graphics_required"], "alloc_sum": 1.0}, quiet | _alloc_sum(quiet)),
                     case("D4 소음 민감", {"outcome": "recommendable", "omitted_slots": {"GPU": "integrated_graphics"},
                                         "borrowed_alloc": {"쿨러": {"ratio": 0.01, "reason": "noise_sensitive"}}, "alloc_sum": 1.0}, noise | _alloc_sum(noise))])


def s20():
    values = {"mode": "upgrade", "purpose": "office", "budget_max": 1_500_000}
    gpu_only = run_flow(make_catalog(), enricher=StubEnricher(), owned=owned_parts(), values={**values, "upgrade_parts": ["GPU"]})
    owned = owned_parts()
    del owned["쿨러"]
    both = run_flow(make_catalog(), enricher=StubEnricher(), owned=owned, values={**values, "upgrade_parts": ["GPU", "쿨러"]})
    return scenario("20", "업그레이드에서 고른 GPU·쿨러는 산다(D3)", "사무 용도라도 업그레이드에서 사용자가 고른 슬롯은 견적에 들어간다. 사무 배분의 그 슬롯이 0% 이면 기본 배분의 비율을 빌려 "
                    "고른 슬롯끼리 합 1 로 다시 정규화한다. 업그레이드는 뺀 슬롯(omitted_slots) 기록이 없고 CPU 내장 그래픽 조건도 걸지 않는다.",
                    ["tests/test_gpu_cooler_omission.py::test_upgrade_buys_the_slots_the_user_chose_even_when_the_purpose_allocation_is_zero"],
                    [case("업그레이드 GPU", {"outcome": "recommendable", "selected_has": ["GPU"], "omitted_slots": {}, "cpu_target_flags": [],
                                            "borrowed_alloc": {"GPU": {"ratio": 0.37, "reason": "upgrade_selected"}}, "alloc_sum": 1.0},
                          gpu_only | {"selected_has": sorted(gpu_only.get("selected", {})), **_alloc_sum(gpu_only)}),
                     case("업그레이드 GPU+쿨러", {"outcome": "recommendable", "borrowed_alloc_has": ["GPU", "쿨러"], "alloc_sum": 1.0},
                          both | {"borrowed_alloc_has": sorted(both.get("borrowed_alloc", {})), **_alloc_sum(both)})])


def _alloc_sum(actual: dict) -> dict:
    return {"alloc_sum": round(sum((actual.get("alloc") or {}).values()), 2)}


SCENARIOS = (s01, s02, s03, s04, s05, s06, s07, s08, s09, s10, s11, s12, s13, s14, s15, s16, s17, s18, s19, s20)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from src.engine.stage2_requirement import load_computer_rules

    scenarios = [fn() for fn in SCENARIOS]
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": compare._git("rev-parse", "HEAD"),
        "git_dirty": bool(compare._git("status", "--porcelain", "--untracked-files=no")),
        "rule_set_version": load_computer_rules().get("rule_set_version"),
        "catalog": "in-memory fixed catalog (scripts/engine_policy_scenarios.make_catalog); enrichment = fixed-table stub",
        "summary": {"scenarios": len(scenarios), "cases": sum(len(s["cases"]) for s in scenarios),
                    "mismatch_cases": sum(1 for s in scenarios for c in s["cases"] if c["mismatch"])},
        "scenarios": scenarios,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str, sort_keys=False) + "\n", encoding="utf-8")
    for s in scenarios:
        print(f"{s['id']} {'MISMATCH' if s['mismatch'] else 'ok'} {s['title']}", file=sys.stderr)
    print(f"wrote {path} ({out['summary']})", file=sys.stderr)


if __name__ == "__main__":
    main()
