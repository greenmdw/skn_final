"""신규 조립에서 용도 배분이 0%인 GPU·쿨러 슬롯을 견적에서 빼는 규칙 (docs/추천엔진_GPU쿨러_미구매_구성_계획_20261015.md, computer-rules-v14).

앞쪽은 DB 없이 도는 엔진 단위 테스트(요구 사양·사전 필터·조합 검증·여유 기록·표기 해석), 뒤쪽(`db`)은 저장·재조회·개정 복제·결과 대화
(담기)·API 필드를 일회용 DB 로 확인한다.
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, Slots
from src.engine import build_margins, compat_parse, omitted_slots, stage2_requirement, stage3a_hardfilter, stage4_optimize
from src.engine.stage2_requirement import RequirementRuleError

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

NOOP = lambda _m: None  # noqa: E731


def _slots(**values) -> Slots:
    mode = values.pop("mode", "build")
    return Slots(category="computer", mode=mode, objective_text="", values={"purpose": "office", "budget_max": 1_500_000, **values})


def _spec(**values) -> RequirementSpec:
    return stage2_requirement.run(_slots(**values), {}, NOOP)


@pytest.fixture(scope="module")
def scen():
    os.environ.setdefault("MOCK_MODE", "1")
    return importlib.import_module("engine_policy_scenarios")


# ── [2] 요구사양: 배분 0 슬롯을 targets 에서 뺀다 ─────────────────────────────────────────

def test_office_build_omits_gpu_and_cooler_and_flags_the_cpu_target():
    rules = stage2_requirement.load_computer_rules()
    spec = _spec()
    assert list(spec.targets) == ["CPU", "RAM", "메인보드", "저장장치", "파워", "케이스"]
    assert spec.omitted_slots == {"GPU": "integrated_graphics", "쿨러": "box_cooler"}
    assert spec.targets["CPU"]["integrated_graphics_required"] is True
    assert spec.targets["CPU"]["box_cooler_required"] is True
    assert spec.targets["CPU"]["box_cooler_max_tdp_w"] == rules["verification"]["box_cooler_max_tdp_w"] == 65
    # 배분에는 사는 슬롯만, 합 1 (시장 값 그대로 — 재정규화 없음)
    assert spec.budget["alloc"] == {"CPU": 0.29, "메인보드": 0.12, "RAM": 0.25, "저장장치": 0.24, "파워": 0.07, "케이스": 0.03}
    assert abs(sum(spec.budget["alloc"].values()) - 1) < 1e-9
    assert "borrowed_alloc" not in spec.budget
    assert spec.power_sizing["estimated_power_w"]["gpu"] == 0           # GPU 전력 0W 로 PSU 헤드룸 산정


@pytest.mark.parametrize("purpose", ["office", "study", "other"])
def test_study_and_other_share_the_office_omission(purpose):
    spec = _spec(purpose=purpose)
    assert spec.omitted_slots == {"GPU": "integrated_graphics", "쿨러": "box_cooler"}
    assert "GPU" not in spec.targets and "쿨러" not in spec.targets


@pytest.mark.parametrize("values", [{"purpose": "game"}, {"purpose": "creation"}, {}, {"purpose": "game", "priority": "quiet"}])
def test_game_and_creation_keep_all_eight_slots(values):
    spec = stage2_requirement.run(Slots(category="computer", mode="build", objective_text="", values=values), {}, NOOP)
    assert len(spec.targets) == 8 and spec.omitted_slots == {}
    assert "integrated_graphics_required" not in spec.targets["CPU"] and "box_cooler_required" not in spec.targets["CPU"]
    assert "borrowed_alloc" not in spec.budget


def test_wanted_gpu_brings_the_gpu_slot_back_and_borrows_the_base_ratio():
    """D2 — 원하는 부품(wanted_parts)에 GPU 가 있으면 GPU 슬롯이 돌아오고, 기본 배분의 GPU 비율(0.37)을 빌려 합 1 로 다시 맞춘다."""
    rules = stage2_requirement.load_computer_rules()["requirements"]
    spec = _spec(wanted_parts={"그래픽카드": {"fields": {}}})              # 슬롯 표기는 별칭도 받는다
    assert "GPU" in spec.targets and "쿨러" not in spec.targets
    assert spec.omitted_slots == {"쿨러": "box_cooler"}
    assert spec.budget["borrowed_alloc"] == {"GPU": {"ratio": rules["budget_allocation"]["GPU"], "reason": "wanted_part"}}
    alloc = spec.budget["alloc"]
    assert abs(sum(alloc.values()) - 1) < 1e-9 and set(alloc) == set(spec.targets)
    office = rules["purpose_profiles"]["office"]["budget_allocation"]
    total = 1 + rules["budget_allocation"]["GPU"]
    assert alloc["GPU"] == pytest.approx(0.37 / total) and alloc["CPU"] == pytest.approx(office["CPU"] / total)
    assert "integrated_graphics_required" not in spec.targets["CPU"] and spec.targets["CPU"]["box_cooler_required"] is True
    assert spec.power_sizing["estimated_power_w"]["gpu"] == rules["purpose_profiles"]["office"]["estimated_power_w"]["gpu"]


@pytest.mark.parametrize("values, reason", [({"priority": "quiet"}, "quiet_priority"), ({"noise_sensitive": True}, "noise_sensitive")])
def test_quiet_priority_or_noise_sensitive_keeps_the_cooler(values, reason):
    """D4 — 기본 쿨러는 소음 근거가 없으므로 저소음·소음 민감이면 쿨러를 빼지 않는다(기본 배분의 쿨러 비율을 빌림). GPU 는 여전히 뺀다."""
    spec = _spec(**values)
    assert "쿨러" in spec.targets and "GPU" not in spec.targets
    assert spec.omitted_slots == {"GPU": "integrated_graphics"}
    assert spec.budget["borrowed_alloc"] == {"쿨러": {"ratio": 0.01, "reason": reason}}
    assert "box_cooler_required" not in spec.targets["CPU"] and spec.targets["CPU"]["integrated_graphics_required"] is True
    assert abs(sum(spec.budget["alloc"].values()) - 1) < 1e-9


def test_noise_sensitive_false_and_other_priorities_do_not_keep_the_cooler():
    for values in ({"noise_sensitive": False}, {"priority": "value"}, {"priority": "performance"}):
        assert _spec(**values).omitted_slots == {"GPU": "integrated_graphics", "쿨러": "box_cooler"}


def test_upgrade_buys_the_slots_the_user_chose_even_when_the_purpose_allocation_is_zero():
    """D3 — 업그레이드에서 고른 슬롯은 산다. 배분이 0 이면 기본 배분 비율을 빌려 고른 슬롯끼리 합 1 로 다시 정규화한다. 뺀 슬롯 기록·CPU 조건은 없다."""
    spec = _spec(mode="upgrade", upgrade_parts=["GPU", "쿨러", "RAM"])
    assert set(spec.targets) == {"GPU", "쿨러", "RAM"} and spec.omitted_slots == {}
    assert spec.budget["borrowed_alloc"] == {"GPU": {"ratio": 0.37, "reason": "upgrade_selected"},
                                              "쿨러": {"ratio": 0.01, "reason": "upgrade_selected"}}
    assert abs(sum(spec.budget["alloc"].values()) - 1) < 1e-9
    assert spec.budget["alloc"]["GPU"] == pytest.approx(0.37 / (0.37 + 0.01 + 0.25))
    only_ram = _spec(mode="upgrade", upgrade_parts=["RAM"])
    assert only_ram.budget["alloc"] == {"RAM": 1.0} and "borrowed_alloc" not in only_ram.budget


def test_upgrade_of_a_game_build_is_unchanged():
    spec = stage2_requirement.run(Slots(category="computer", mode="upgrade", objective_text="",
                                         values={"purpose": "game", "upgrade_parts": ["GPU"]}), {}, NOOP)
    assert list(spec.targets) == ["GPU"] and spec.budget["alloc"] == {"GPU": 1.0} and "borrowed_alloc" not in spec.budget


def test_full_slots_keeps_the_eight_reference_slots_for_quote_checks():
    """견적 점검·이전 견적 비교는 용도 기준 8개 부품이 필요하다 — 슬롯을 빼지 않고 배분도 그대로(0 포함)."""
    spec = stage2_requirement.run(_slots(), {}, NOOP, full_slots=True)
    assert len(spec.targets) == 8 and spec.omitted_slots == {}
    assert spec.budget["alloc"]["GPU"] == 0 and spec.budget["alloc"]["쿨러"] == 0
    assert "integrated_graphics_required" not in spec.targets["CPU"]


# ── 배분 검증 ────────────────────────────────────────────────────────────────────────────

def _write(tmp_path, mutate):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    mutate(rules)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("label, mutate, match", [
    ("CPU 0%", lambda r: r["requirements"]["purpose_profiles"]["office"]["budget_allocation"].update(CPU=0, GPU=0.29), "GPU·쿨러만 0"),
    ("RAM 0%", lambda r: r["requirements"]["purpose_profiles"]["office"]["budget_allocation"].update(RAM=0, GPU=0.25), "GPU·쿨러만 0"),
    ("기본 배분 GPU 0%", lambda r: r["requirements"]["budget_allocation"].update(GPU=0, CPU=0.51), "GPU·쿨러는 0 보다"),
    ("기본 배분 쿨러 0%", lambda r: r["requirements"]["budget_allocation"].update(쿨러=0, CPU=0.15), "GPU·쿨러는 0 보다"),
    ("음수", lambda r: r["requirements"]["purpose_profiles"]["office"]["budget_allocation"].update(GPU=-0.1, CPU=0.39), "음수"),
    ("슬롯 누락", lambda r: r["requirements"]["purpose_profiles"]["office"]["budget_allocation"].pop("케이스"), "8개 부품"),
    ("합계 1 아님", lambda r: r["requirements"]["purpose_profiles"]["office"]["budget_allocation"].update(CPU=0.5), "합계"),
    ("기본 쿨러 허용 TDP 없음", lambda r: r["verification"].pop("box_cooler_max_tdp_w"), "box_cooler_max_tdp_w"),
    ("기본 쿨러 허용 TDP 0", lambda r: r["verification"].update(box_cooler_max_tdp_w=0), "box_cooler_max_tdp_w"),
])
def test_invalid_budget_allocation_or_box_cooler_tdp_is_rejected(tmp_path, label, mutate, match):
    with pytest.raises(RequirementRuleError, match=match):
        stage2_requirement.load_computer_rules(_write(tmp_path, mutate))


def test_zero_gpu_and_cooler_are_accepted_but_not_other_slots(tmp_path):
    path = _write(tmp_path, lambda r: None)
    assert stage2_requirement.load_computer_rules(path)["rule_set_version"] == "computer-rules-v14"


# ── 표기 해석(엔진·채팅 공용) ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, want", [
    ("O", True), ("o", True), ("O (정품 박스 기준)", True), (" O ", True),
    ("X", False), ("X / SKU 확인", False), ("x", False),
    (None, None), ("", None), ("   ", None), ("확인불가", None), ("미표기", None), (1, None),
])
def test_parse_ox(raw, want):
    assert compat_parse.parse_ox(raw) is want


def test_chat_and_engine_share_the_same_parser():
    from src.services import result_advice
    for raw in ("O (정품 박스 기준)", "X / SKU 확인", None, "?"):
        assert result_advice._has_box_cooler(raw) is compat_parse.parse_ox(raw)


def test_catalog_loader_carries_integrated_graphics_and_cooler_included():
    from src.repo import catalog_repo
    assert "s.integrated_graphics" in catalog_repo._SPEC_QUERIES["cpu"][0] and "s.cooler_included" in catalog_repo._SPEC_QUERIES["cpu"][0]
    specs = catalog_repo._specs_from_row("cpu", {"socket": "AM5", "integrated_graphics": "O", "cooler_included": "O (정품 박스 기준)"})
    assert specs["integrated_graphics"] == "O" and specs["cooler_included"] == "O (정품 박스 기준)"
    assert "integrated_graphics" not in catalog_repo._specs_from_row("cpu", {"socket": "AM5", "integrated_graphics": None, "cooler_included": " "})


# ── [3-A] CPU 사전 필터 ─────────────────────────────────────────────────────────────────

def _cpu(key="cpu:t", price=200_000, **specs) -> Candidate:
    base = {"socket": "AM5", "perf_tier": 6, "tdp_w": 65, "integrated_graphics": "O", "cooler_included": "O (정품 박스 기준)"}
    return Candidate(product_key=key, slot="CPU", name=key, price=price,
                     specs={k: v for k, v in {**base, **specs}.items() if v is not None})


@pytest.mark.parametrize("specs, verdict, reasons", [
    ({}, "Pass", ["PASS"]),
    ({"integrated_graphics": "X"}, "Fail", ["FAIL_NO_INTEGRATED_GRAPHICS"]),
    ({"integrated_graphics": None}, "Pending", ["PENDING_SPEC_MISSING:integrated_graphics"]),
    ({"integrated_graphics": "모름"}, "Pending", ["PENDING_SPEC_MISSING:integrated_graphics"]),
    ({"cooler_included": "X / SKU 확인"}, "Fail", ["FAIL_NO_BOX_COOLER"]),
    ({"cooler_included": None}, "Pending", ["PENDING_SPEC_MISSING:cooler_included"]),
    ({"tdp_w": 105}, "Fail", ["FAIL_BOX_COOLER_TDP:105>65"]),
    ({"tdp_w": 65.0}, "Pass", ["PASS"]),                                          # 허용값 이하(경계 포함)
    ({"tdp_w": None}, "Pending", ["PENDING_SPEC_MISSING:tdp_w"]),
    ({"cooler_included": None, "tdp_w": 105}, "Fail", ["FAIL_BOX_COOLER_TDP:105>65"]),   # TDP 초과는 값 유무와 무관하게 탈락
    ({"integrated_graphics": "X", "cooler_included": None}, "Fail", ["FAIL_NO_INTEGRATED_GRAPHICS"]),   # Fail > Pending
])
def test_cpu_filter_reason_codes(specs, verdict, reasons):
    target = _spec().targets["CPU"]
    judged = stage3a_hardfilter._judge("CPU", _cpu(**specs), target)
    assert (judged.verdict, judged.reasons) == (verdict, reasons)


def test_cpu_filter_applies_only_to_the_flags_that_were_set():
    """GPU 만 뺀 견적(저소음)은 내장 그래픽만 본다 — 기본 쿨러 값은 보지 않는다. 게임 견적은 둘 다 안 본다."""
    quiet = _spec(priority="quiet").targets["CPU"]
    assert stage3a_hardfilter._judge("CPU", _cpu(cooler_included="X"), quiet).verdict == "Pass"
    assert stage3a_hardfilter._judge("CPU", _cpu(integrated_graphics="X"), quiet).verdict == "Fail"
    game = stage2_requirement.run(Slots(category="computer", mode="build", objective_text="", values={"purpose": "game"}), {}, NOOP).targets["CPU"]
    assert stage3a_hardfilter._judge("CPU", _cpu(integrated_graphics="X", cooler_included="X", perf_tier=9), game).verdict == "Pass"


def test_hardfilter_skips_the_omitted_slots_even_if_candidates_are_passed():
    spec = _spec()
    by_slot = {"CPU": [_cpu()], "GPU": [Candidate(product_key="g", slot="GPU", name="g", price=1, specs={})],
               "쿨러": [Candidate(product_key="c", slot="쿨러", name="c", price=1, specs={})]}
    # CPU 만 있고 나머지 목표 슬롯 후보가 없어 부족이지만, GPU·쿨러는 부족 목록에도 판정에도 나오지 않는다.
    with pytest.raises(stage3a_hardfilter.CandidateShortage) as exc:
        stage3a_hardfilter.run(spec, by_slot, NOOP)
    assert "GPU" not in exc.value.slots and "쿨러" not in exc.value.slots and "RAM" in exc.value.slots


def test_no_qualifying_cpu_is_candidate_shortage_without_promotion(scen):
    """통과 CPU 가 없으면(전부 Fail 또는 Pending) 자동 승격 없이 후보 부족. Pending 은 보완 값이 없으면 그대로."""
    a = scen.run_flow(scen._uniform_cpus(integrated_graphics="X"), enricher=scen.StubEnricher(), values=scen.OFFICE)
    assert a["outcome"] == "candidate_shortage"
    assert a["shortage"]["CPU"] == {"pending_reasons": {}, "fail_reasons": {"FAIL_NO_INTEGRATED_GRAPHICS": 3}}
    pending = scen._uniform_cpus()
    scen.strip(pending, "CPU", "integrated_graphics", "cooler_included")
    b = scen.run_flow(pending, enricher=scen.StubEnricher(), values=scen.OFFICE)
    assert b["outcome"] == "candidate_shortage" and b["prefilter_enrichment"] == {"not_found": 3}
    assert b["shortage"]["CPU"]["fail_reasons"] == {}
    assert b["shortage"]["CPU"]["pending_reasons"] == {"PENDING_SPEC_MISSING:integrated_graphics": 3,
                                                       "PENDING_SPEC_MISSING:cooler_included": 3}


def test_enrichment_that_fills_the_flags_returns_the_cpu_to_pass(scen):
    cat = scen.make_catalog()
    scen.strip(cat, "CPU", "integrated_graphics", "cooler_included")
    table = {("CPU", k): {"integrated_graphics": "O", "cooler_included": "O (정품 박스 기준)"} for k in ("cpu:r5-7600", "cpu:r7-7700x", "cpu:r5-7500f")}
    a = scen.run_flow(cat, enricher=scen.StubEnricher(table), values=scen.OFFICE)
    assert a["outcome"] == "recommendable" and a["returned_to_pass"] >= 1
    assert a["pass_counts"]["CPU"] == 2 and a["fail_counts"]["CPU"] == 1        # 7700X 는 TDP 105W 라 기본 쿨러로 못 식힌다


def test_feasibility_does_not_count_or_require_omitted_slots(scen):
    from src.engine import feasibility
    spec = _spec()
    cat = scen.make_catalog()
    res = feasibility.assess(spec, cat)
    assert set(res["per_slot"]) == set(spec.targets) and res["unfillable"] == []


# ── [4]·[3-C] 조합: 빠진 슬롯은 필수 정보 누락·세트 위반·부적격을 만들지 않는다 ───────────────────

def test_omitted_slots_do_not_create_required_info_missing_or_set_violation(scen):
    a = scen.run_flow(scen.make_catalog(), enricher=scen.StubEnricher(), values=scen.OFFICE)
    assert a["outcome"] == "recommendable" and a["reason_codes"] == [] and a["missing"] == []
    assert set(a["selected"]) == {"CPU", "RAM", "메인보드", "저장장치", "파워", "케이스"}
    assert a["eligible"] is True and a["passed"] is True


def _office_build(scen):
    spec = _spec()
    cat = scen.make_catalog()
    chosen = {slot: next(c for c in cands if c.product_key in {"cpu:r5-7600", "ram:kit-16x2", "mb:b650", "ssd:1tb", "psu:750", "case:a"})
              for slot, cands in cat.items() if slot not in ("GPU", "쿨러")}
    return spec, chosen


def test_compat_details_skip_gpu_and_cooler_rows_and_record_the_igpu_and_box_cooler_rows(scen):
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    rows = {r["axis"]: r for r in stage4_optimize.pc_compat_details(chosen, spec, rules)}
    for axis in ("gpu_len", "gpu_slots", "gpu_connector", "cooler_height", "cooler_socket", "radiator"):
        assert rows[axis]["state"] == "skipped" and "이라 확인하지 않았습니다" in rows[axis]["detail"], axis
        assert rows[axis]["missing_slots"] == () and not rows[axis]["required_missing"]
    assert rows["power"]["state"] == "ok" and "GPU 없음(내장 그래픽) 0W" in rows["power"]["detail"]
    assert [i["slot"] for i in rows["power"]["inputs"]] == ["CPU", "파워"]           # 0W 는 부품 스펙이 아니라 근거 항목을 만들지 않는다
    assert rows["integrated_graphics"]["state"] == "ok" and "내장 그래픽이 있어" in rows["integrated_graphics"]["detail"]
    assert rows["box_cooler"]["state"] == "ok" and "기본 쿨러" in rows["box_cooler"]["detail"]
    link = stage4_optimize.pc_link_check(chosen, spec, rules)
    assert "set" not in link and not any(v == "fail" for v in link.values())
    assert "gpu_len" not in link and link["integrated_graphics"] == "ok" and link["box_cooler"] == "ok"
    assert not any(f["missing"] for f in stage4_optimize.required_info_findings(chosen, spec, rules, detail=False))


def test_power_axis_still_requires_cpu_power_and_psu_wattage_when_gpu_is_omitted(scen):
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    chosen["파워"] = chosen["파워"].model_copy(update={"specs": {k: v for k, v in chosen["파워"].specs.items() if k != "wattage_w"}})
    findings = {f["axis"]: f for f in stage4_optimize.required_info_findings(chosen, spec, rules, detail=False)}
    assert findings["power"]["applicable"] and [m["key"] for m in findings["power"]["missing"]] == ["wattage_w"]
    assert not findings["gpu_len"]["applicable"] and not findings["cooler_height"]["applicable"]


def test_a_psu_below_the_cpu_only_load_is_still_a_power_failure(scen):
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    chosen["CPU"] = chosen["CPU"].model_copy(update={"specs": {**chosen["CPU"].specs, "max_power_w": 900}})
    assert "power" in stage4_optimize._pc_known_failures(chosen, spec, rules)


@pytest.mark.parametrize("specs, axis, state", [
    ({"integrated_graphics": "X"}, "integrated_graphics", "fail"),
    ({"integrated_graphics": None}, "integrated_graphics", "unknown"),
    ({"cooler_included": "X / SKU 확인"}, "box_cooler", "fail"),
    ({"tdp_w": 105}, "box_cooler", "fail"),
    ({"cooler_included": None}, "box_cooler", "unknown"),
])
def test_swapping_in_a_cpu_that_cannot_replace_the_omitted_part_is_flagged(scen, specs, axis, state):
    """결과 대화에서 CPU 를 바꾼 뒤의 재검증 — 내장 그래픽·기본 쿨러가 없는 CPU 면 그 부품이 필요하다고 알린다(확정이면 위반, 모르면 확인 필요)."""
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    chosen["CPU"] = chosen["CPU"].model_copy(update={"specs": {k: v for k, v in {**chosen["CPU"].specs, **specs}.items() if v is not None}})
    rows = {r["axis"]: r for r in stage4_optimize.pc_compat_details(chosen, spec, rules)}
    assert rows[axis]["state"] == state
    link = stage4_optimize.pc_link_check(chosen, spec, rules)
    assert link[axis] == ("fail" if state == "fail" else "ok (근사)")
    from src.engine import stage3c_verify
    from src.dto import BuildResult
    verification = stage3c_verify.verify_build(BuildResult(list_id="x", link_check=link, budget={"max": 0, "used": 0}), "computer", NOOP,
                                               chosen=chosen, spec=spec, rules=rules)
    target = verification.targets[0]
    assert any(i.axis == axis for i in target.issues)
    assert target.eligible is (state != "fail")


def test_after_adding_the_part_back_the_cpu_condition_is_not_required(scen):
    """담은 슬롯은 omitted_slots 에서 빠지므로 그 CPU 조건을 더는 보지 않는다."""
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    chosen["CPU"] = chosen["CPU"].model_copy(update={"specs": {**chosen["CPU"].specs, "integrated_graphics": "X"}})
    gpu = scen.make_catalog()["GPU"][0]
    spec.omitted_slots = {"쿨러": "box_cooler"}
    chosen["GPU"] = gpu
    link = stage4_optimize.pc_link_check(chosen, spec, rules)
    assert "integrated_graphics" not in link and link.get("gpu_len") == "ok"


def test_margins_record_omitted_parts_as_not_applicable_and_power_uses_zero_gpu(scen):
    spec, chosen = _office_build(scen)
    rules = stage2_requirement.load_computer_rules()["verification"]
    m = build_margins.evaluate_margins(chosen, spec, rules)
    for name in ("gpu_length", "gpu_slots", "cooler_height", "radiator"):
        assert m["size"][name]["status"] == "not_applicable" and m["size"][name]["reason"] == build_margins.OMITTED_SLOT, name
    assert m["cooling"]["status"] == "not_applicable" and m["cooling"]["reason"] == build_margins.OMITTED_SLOT
    power = m["power"]["compat_check"]
    assert power["status"] == "available" and power["load_w"] == power["load_w"] and all(i["slot"] != "GPU" for i in power["inputs"])
    cpu_w = next(i["value"] for i in power["inputs"] if i["slot"] == "CPU")
    assert power["load_w"] == cpu_w                                              # CPU + 0W
    assert m["size"]["psu_length"]["status"] == "available"


def test_balance_is_undecided_without_a_gpu(scen):
    from src.engine import stage4_optimize as s4
    spec = _spec()
    cat = scen.make_catalog()
    from src.engine.stage3b_rank import _score
    pools = {slot: [_score(c, 100_000.0, slot, {"가격": 0.45, "성능": 0.3, "리뷰": 0.25}) for c in cands]
             for slot, cands in cat.items() if slot in spec.targets}
    rank = RankResult(slots={slot: {"ranked": [c.model_dump() for c in cands]} for slot, cands in pools.items()})
    build = s4.build_computer(rank, spec, NOOP)
    assert build.balance["verdict"] == "판단 보류" and build.totals["power_w"] is not None
    assert [i.slot for i in build.items].count("GPU") == 0 and "set" not in build.link_check


# ── 저장 기록·표기 ────────────────────────────────────────────────────────────────────────

def test_omitted_step_roundtrip_and_api_shape():
    step = omitted_slots.build_step({"GPU": "integrated_graphics", "쿨러": "box_cooler"},
                                    {"쿨러": {"ratio": 0.01, "reason": "quiet_priority"}})
    assert step["step"] == omitted_slots.OMITTED_SLOTS_STEP
    assert omitted_slots.omitted_from_step(step) == {"GPU": "integrated_graphics", "쿨러": "box_cooler"}
    out = omitted_slots.out_from_step(step)
    assert [e["slot"] for e in out["omitted_slots"]] == ["GPU", "쿨러"]
    gpu = out["omitted_slots"][0]
    assert gpu["slot_label"] == "그래픽카드" and gpu["reason_text"] == "내장 그래픽 사용" and "메인보드" in gpu["notes"][0]
    cooler = out["omitted_slots"][1]
    assert cooler["reason_text"] == "CPU 기본 쿨러 사용" and "정품 박스" in cooler["notes"][0] and "포장 형태" in cooler["notes"][0]
    assert out["borrowed_alloc"] == [{"slot": "쿨러", "ratio": 0.01, "reason": "quiet_priority",
                                       "reason_text": stage2_requirement.REINSTATE_REASONS["quiet_priority"]}]
    assert omitted_slots.build_step({}, {}) is None
    assert omitted_slots.omitted_from_step(None) == {} and omitted_slots.out_from_step(None) == {"omitted_slots": [], "borrowed_alloc": []}
    assert omitted_slots.chat_added_slots(omitted_slots.build_step({}, {"GPU": {"ratio": 0.37, "reason": "result_chat"}})) == {"GPU": "result_chat"}


def test_the_result_schema_carries_omitted_slots_and_borrowed_alloc():
    from src import schemas
    step = omitted_slots.build_step({"GPU": "integrated_graphics"}, {"쿨러": {"ratio": 0.01, "reason": "noise_sensitive"}})
    result = schemas.RecommendResultOut(list_id="l", run_id="r", status="done", category="computer", **omitted_slots.out_from_step(step))
    assert result.omitted_slots[0].slot == "GPU" and result.omitted_slots[0].reason == "integrated_graphics"
    assert result.borrowed_alloc[0].ratio == 0.01 and result.borrowed_alloc[0].reason == "noise_sensitive"
    assert schemas.RecommendResultOut(list_id="l", run_id="r", status="done", category="computer").omitted_slots == []


def test_explanation_caveats_tell_why_the_parts_are_missing_and_what_to_check():
    from src.services import recommendation_service
    extras = recommendation_service._explanation_extras(_spec())
    text = " ".join(extras["extra_caveats"])
    assert "그래픽카드는 견적에 넣지 않았습니다(내장 그래픽 사용)" in text and "CPU 쿨러는 견적에 넣지 않았습니다(CPU 기본 쿨러 사용)" in text
    assert "메인보드의 영상 출력" in text and "정품 박스" in text
    assert "extra_caveats" not in recommendation_service._explanation_extras(
        stage2_requirement.run(Slots(category="computer", mode="build", objective_text="", values={"purpose": "game"}), {}, NOOP))


# ── 주변기기: 모니터 단자 검사 ────────────────────────────────────────────────────────────

def test_monitor_port_check_says_needs_confirmation_when_the_quote_uses_integrated_graphics():
    from src.engine import peripheral_cross
    monitor = Candidate(product_key="m", slot="monitor", name="모니터", price=1, specs={"resolution_class": "FHD", "refresh_hz": 60,
                                                                                         "hdmi_ports": 1, "dp_ports": 1})
    from src.engine.peripheral_rules import load_peripheral_rules
    rules = load_peripheral_rules()
    plain = peripheral_cross.monitor_cross_checks(monitor, pc_resolution="FHD_144", gpu_specs=None, target_refresh_hz=None, rules=rules)
    igpu = peripheral_cross.monitor_cross_checks(monitor, pc_resolution="FHD_144", gpu_specs=None, target_refresh_hz=None, rules=rules,
                                                 integrated_graphics=True)
    port_plain = next(c for c in plain if c["axis"] == "monitor_gpu_port")
    port_igpu = next(c for c in igpu if c["axis"] == "monitor_gpu_port")
    assert port_plain["state"] == "unknown" and "그래픽카드 출력 단자 정보가 없어" in port_plain["detail"]
    assert port_igpu["state"] == "unknown" and "내장 그래픽" in port_igpu["detail"] and "메인보드" in port_igpu["detail"]
    issues = peripheral_cross.cross_issues(igpu)
    assert any(i.axis == "monitor_gpu_port" and i.judge == "확인 필요" for i in issues)


# ── 견적 점검·이전 견적 비교는 8개 부품 기준을 그대로 쓴다 ───────────────────────────────────

def test_quote_balance_requirement_keeps_all_eight_slots_for_office():
    from src.services import quote_balance
    spec, _ = quote_balance.requirement_spec({"purpose": "office"})
    assert spec.targets["GPU"]["perf_tier_min"] is not None and spec.omitted_slots == {}


def test_quote_balance_budget_rows_handle_a_zero_allocation_without_dividing_by_zero():
    from src.services import quote_balance
    spec, _ = quote_balance.requirement_spec({"purpose": "office"})
    prices = {"rows": [{"part": p, "quoted": q} for p, q in (("CPU", 300_000), ("GPU", 400_000), ("RAM", 150_000), ("메인보드", 120_000),
                                                             ("저장장치", 100_000), ("파워", 80_000))],
              "summary": {"quote_total_complete": True}}
    rows = quote_balance._budget_rows(spec, prices, 1_500_000)
    gpu = next(r for r in rows if r["part"] == "GPU" and r["aspect"] == "예산 비중")
    assert gpu["state"] == "excess" and "0%" in gpu["detail"] and gpu["target"] == 0


def test_previous_compare_requirements_still_see_the_gpu_floor_for_office():
    from src.categories import load_category
    from src.services import previous_compare
    req = previous_compare._requirements(load_category("computer"), {"category": "computer", "mode": "build", "purpose": "office"})
    assert req[("GPU", "perf_tier_min")] is not None


# ── 결과 대화 도우미 ──────────────────────────────────────────────────────────────────────

def _chat_session(**extra):
    from src.agent import result_agent as ra
    result = {"run_id": "r", "category": "computer", "conditions_summary": "사무", "budget_max": 1_500_000,
              "items": [{"item_id": str(uuid.uuid4()), "slot": "CPU", "slot_label": "CPU", "price": 200_000, "qty": 1, "selected": True,
                         "alternatives_count": 2, "budget_share": 0.3, "product": {"name": "CPU A", "spec_summary": ""},
                         "reason": {"status": "ready", "text": "x"}}],
              "totals": {"selected_price": 200_000, "selected_units": 1, "budget_remaining": 1_300_000, "over_budget": False},
              "verification": {"status": "ready", "confidence": 100, "issues": []},
              "omitted_slots": [{"slot": "GPU", "slot_label": "그래픽카드", "reason": "integrated_graphics", "reason_text": "내장 그래픽 사용", "notes": []}],
              **extra}
    return ra, ra.ResultSession(conn=None, revision_id=uuid.uuid4(), result=result)


def test_chat_tells_how_to_add_an_omitted_part_instead_of_saying_the_slot_does_not_exist():
    ra, s = _chat_session()
    out = s.swap("GPU", str(uuid.uuid4()))
    assert "일부러 넣지 않았습니다" in out and "omitted_options" in out and "add_omitted_part" in out
    assert "일부러" not in s.set_item("모니터", selected="true")            # 구성표에도 뺀 슬롯에도 없는 이름은 그대로 오류
    assert "omitted_options" in s.list_alternatives("GPU")
    assert s.add_omitted_part("쿨러", str(uuid.uuid4())).startswith("오류: '쿨러'은(는) 이 견적에서 뺀 부품이 아닙니다")


def test_chat_prompt_mentions_the_omitted_slots_only_when_there_are_some():
    ra, s = _chat_session()
    assert "18. 이 견적은 GPU(내장 그래픽 사용)을(를) 일부러 넣지 않았습니다" in ra.system_prompt(s.result, "안녕", [])
    ra, s = _chat_session(omitted_slots=[])
    assert "18. 이 견적은" not in ra.system_prompt(s.result, "안녕", [])


def test_chat_write_tool_is_refused_for_a_question():
    ra, s = _chat_session()
    s.read_only = True
    assert s.add_omitted_part("GPU", str(uuid.uuid4())).startswith("거절")


# ── DB: 저장·재조회·개정 복제·결과 대화(담기)·API ─────────────────────────────────────────────

def _office_list(c, purpose="사무", priority="가성비", budget=1_500_000):
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    assert c.post(f"/session/{lid}/message", json={"text": "사무용 PC 맞추고 싶어요"}).status_code == 200
    for qid, value in (("q_purpose", purpose), ("q_budget_max", budget), ("q_priority", priority)):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    assert r.json()["can_recommend"] is True, r.json()
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return lid, data


def _client():
    from fastapi.testclient import TestClient

    from src.api import app
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"omit-{uuid.uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": "미구매",
                                     "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_office_result_has_six_items_omitted_slots_and_a_cpu_that_replaces_both_parts():
    c = _client()
    lid, data = _office_list(c)
    assert sorted(i["slot"] for i in data["items"]) == sorted(["CPU", "RAM", "메인보드", "저장장치", "파워", "케이스"])
    assert [(e["slot"], e["reason"]) for e in data["omitted_slots"]] == [("GPU", "integrated_graphics"), ("쿨러", "box_cooler")]
    assert data["borrowed_alloc"] == []
    notes = " ".join(n for e in data["omitted_slots"] for n in e["notes"])
    assert "메인보드" in notes and "정품 박스" in notes
    assert data["eligibility"]["status"] == "recommendable", data["eligibility"]
    assert not [i for i in data["verification"]["issues"] if i["severity"] == "major"]
    assert not any(row["state"] == "fail" for row in data["compat_checks"])
    axes = {row["axis"]: row for row in data["compat_checks"]}
    assert axes["integrated_graphics"]["state"] == "ok" and axes["box_cooler"]["state"] == "ok"
    assert axes["gpu_len"]["state"] == "skipped"
    if data["explanation"]["status"] == "ready":                 # 요약 본문의 '확인이 필요한 것'에 빠진 이유·구매 전 확인 안내가 붙는다
        assert "그래픽카드는 견적에 넣지 않았습니다" in data["explanation"]["text"]

    # 저장·재조회 — 같은 값
    again = c.get(f"/session/{lid}/result").json()
    assert again["omitted_slots"] == data["omitted_slots"] and again["compat_checks"] == data["compat_checks"]


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_omitted_slots_survive_confirm_and_revision_clone():
    c = _client()
    lid, data = _office_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "사무 PC"}).status_code == 200
    revised = c.post(f"/lists/{lid}/revisions")
    assert revised.status_code in (200, 201), revised.text
    again = c.get(f"/session/{lid}/result").json()
    assert [e["slot"] for e in again["omitted_slots"]] == ["GPU", "쿨러"]
    assert sorted(i["slot"] for i in again["items"]) == sorted(i["slot"] for i in data["items"])


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_adding_the_omitted_gpu_and_cooler_borrows_the_base_ratio_and_reverifies():
    """D2 — 결과 대화/화면에서 GPU 를 담으면 GPU 슬롯이 돌아오고 기본 배분 비율을 빌린다. 쿨러도 같다."""
    c = _client()
    lid, data = _office_list(c)
    opts = c.get(f"/session/{lid}/omitted-slots/GPU/options")
    assert opts.status_code == 200, opts.text
    items = opts.json()["items"]
    assert items and all(not i["current"] for i in items)
    r = c.post(f"/session/{lid}/omitted-slots/GPU/add", json={"candidate_id": items[0]["candidate_id"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert "GPU" in {i["slot"] for i in res["items"]} and [e["slot"] for e in res["omitted_slots"]] == ["쿨러"]
    assert res["borrowed_alloc"] == [{"slot": "GPU", "ratio": 0.37, "reason": "result_chat",
                                       "reason_text": stage2_requirement.REINSTATE_REASONS["result_chat"]}]
    gpu_item = next(i for i in res["items"] if i["slot"] == "GPU")
    assert gpu_item["product"]["variant_id"] == items[0]["candidate_id"] and gpu_item["selected"] is True
    axes = {row["axis"]: row["state"] for row in res["compat_checks"]}
    assert "integrated_graphics" not in axes and axes["gpu_len"] in ("ok", "unknown") and axes["box_cooler"] == "ok"
    assert res["totals"]["selected_price"] == sum(i["price"] * i["qty"] for i in res["items"] if i["selected"])
    # 같은 슬롯을 또 담을 수 없다
    again = c.post(f"/session/{lid}/omitted-slots/GPU/add", json={"candidate_id": items[0]["candidate_id"]})
    assert again.status_code == 422, again.text
    # 쿨러도 담으면 뺀 슬롯이 없다 — 두 슬롯의 빌린 비율이 모두 남는다
    cooler_opts = c.get(f"/session/{lid}/omitted-slots/쿨러/options").json()["items"]
    assert cooler_opts
    done = c.post(f"/session/{lid}/omitted-slots/쿨러/add", json={"candidate_id": cooler_opts[0]["candidate_id"]}).json()
    assert done["omitted_slots"] == [] and {b["slot"] for b in done["borrowed_alloc"]} == {"GPU", "쿨러"}
    assert len(done["items"]) == 8
    final = c.get(f"/session/{lid}/result").json()
    assert final["omitted_slots"] == [] and len(final["items"]) == 8


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_swapping_the_cpu_for_one_without_integrated_graphics_asks_for_a_graphics_card():
    c = _client()
    lid, data = _office_list(c)
    cpu = next(i for i in data["items"] if i["slot"] == "CPU")
    alts = c.get(f"/session/{lid}/items/{cpu['item_id']}/alternatives").json()["items"]
    # 대안 목록은 지금 구성과 안 맞는 후보(내장 그래픽 없는 CPU 포함)를 걸러 낸다 — 남은 후보는 모두 내장 그래픽이 있다.
    from src.repo.catalog_repo import load_specs_by_variant
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        specs = load_specs_by_variant(conn, [("cpu", a["candidate_id"]) for a in alts])
        no_igpu = conn.execute(
            "SELECT v.id FROM catalog.cpu_spec s JOIN catalog.product_variant v ON v.product_id = s.product_id "
            "WHERE s.integrated_graphics = 'X' AND s.socket = %s LIMIT 1",
            (specs[str(cpu["product"]["variant_id"])]["socket"] if str(cpu["product"]["variant_id"]) in specs else "AM5",)).fetchone()
    assert all(str((specs.get(a["candidate_id"]) or {}).get("integrated_graphics", "O")).upper().startswith("O") for a in alts)
    if no_igpu is None:
        pytest.skip("같은 소켓에 내장 그래픽 없는 CPU 가 카탈로그에 없다")
    r = c.post(f"/session/{lid}/items/{cpu['item_id']}/swap", json={"candidate_id": str(no_igpu[0])})
    assert r.status_code == 200, r.text
    res = r.json()
    assert any(i["axis"] == "integrated_graphics" and i["severity"] == "major" for i in res["verification"]["issues"]), res["verification"]
    assert res["eligibility"]["status"] == "not_recommendable"


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_result_questions_work_without_a_gpu_and_do_not_change_the_quote():
    """GPU·쿨러가 없는 견적에서 결과 대화의 묻는 말(점검·게임·남은 예산·가정 계산)이 오류 없이 답하고 구성표를 바꾸지 않는다."""
    import psycopg

    from src.auth.deps import Principal
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service, result_advice, session_service

    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None, autocommit=True) as conn:
        created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
        principal = Principal(user_id=None, browser_token=created["browser_token"])
        list_id = uuid.UUID(created["list_id"])
        session_service.choose_category(conn, list_id, "computer", "build", principal)
        for field, value in (("purpose", "office"), ("budget_max", 1_500_000), ("priority", "value")):
            session_service.patch_slot(conn, list_id, field, value, principal)
        revision_id = PlanRepo(conn).get_current_revision(list_id)["id"]
        accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
        recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
        run = recommendation_service._require_done_run(conn, revision_id)[1]
        before = [(r["slot"], str(r["variant_id"]), r["qty"], r["selected"]) for r in EngineRepo(conn).get_candidates(run["id"])]
        assert {slot for slot, *_ in before} == {"CPU", "RAM", "메인보드", "저장장치", "파워", "케이스"}

        ctx = result_advice._context(conn, revision_id)
        assert ctx.spec.omitted_slots == {"GPU": "integrated_graphics", "쿨러": "box_cooler"}
        check = result_advice.check_build(conn, revision_id)
        assert check and "GPU 길이" not in check                              # 빠진 GPU 의 길이 검사를 '정보 없음'으로 말하지 않는다
        assert "기본 쿨러" in "\n".join(result_advice.cooler_lines(conn, ctx))
        game = result_advice.game_check(conn, revision_id, "롤")
        assert "그래픽카드를 넣지 않은 내장 그래픽 구성이라 비교하지 않음" in game and "GPU 성능 등급 요구" in game
        from src.services import peripherals_service
        pc_context = peripherals_service.pc_context_from_list(conn, list_id, principal)     # 모니터 단자 검사가 내장 그래픽 견적임을 안다
        assert pc_context["gpu_specs"] is None and pc_context["integrated_graphics"] is True
        assert result_advice.upgrade_options(conn, revision_id)           # 예외 없이 문장을 낸다
        cpu = ctx.row("CPU")
        assert result_advice.preview_swap(conn, revision_id, "CPU", direction="up")
        after = [(r["slot"], str(r["variant_id"]), r["qty"], r["selected"]) for r in EngineRepo(conn).get_candidates(run["id"])]
        assert after == before and cpu is not None


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_quiet_priority_keeps_the_cooler_and_records_the_borrowed_ratio_over_http():
    """D4 — 저소음 요청이면 쿨러가 견적에 들어오고(7개 품목), 기본 배분의 쿨러 비율과 이유가 결과에 남는다. GPU 는 여전히 빠진다."""
    c = _client()
    lid, data = _office_list(c, priority="조용한 게 좋아요")
    assert sorted(i["slot"] for i in data["items"]) == sorted(["CPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"])
    assert [e["slot"] for e in data["omitted_slots"]] == ["GPU"]
    assert data["borrowed_alloc"] == [{"slot": "쿨러", "ratio": 0.01, "reason": "quiet_priority",
                                        "reason_text": stage2_requirement.REINSTATE_REASONS["quiet_priority"]}]
    axes = {row["axis"]: row["state"] for row in data["compat_checks"]}
    assert axes["integrated_graphics"] == "ok" and "box_cooler" not in axes and axes["cooler_height"] in ("ok", "unknown")


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_game_result_has_no_omitted_slots_and_keeps_eight_items():
    c = _client()
    lid, data = _office_list(c, purpose="게임", budget=3_500_000, priority="성능 우선")
    assert len(data["items"]) == 8 and data["omitted_slots"] == [] and data["borrowed_alloc"] == []
    assert not any(row["axis"] in ("integrated_graphics", "box_cooler") for row in data["compat_checks"])
