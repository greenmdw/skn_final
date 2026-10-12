"""조합의 전력·냉각·크기 여유 평가(4b단계, 정책 §2.3) — 기록일 뿐 판정·점수를 바꾸지 않는다.

기준 세트·후보 도우미는 4a 테스트(test_combo_eligibility)의 것을 그대로 쓴다. DB가 필요한 테스트는 tests/test_build_margins_db.py.
"""
from __future__ import annotations

import pytest

from src.engine import build_margins
from src.engine import stage3c_verify
from src.engine.build_margins import evaluate_margins
from src.engine.stage2_requirement import RequirementRuleError, load_computer_rules
from src.engine.stage4_optimize import build_computer
from tests.test_combo_eligibility import BASE, RULES, SLOTS, _noop, build_of, full, part, rank_of, spec_of  # noqa: F401


def margins_of(chosen=None, spec=None, rules=RULES):
    return evaluate_margins(chosen if chosen is not None else full(), spec or spec_of(), rules)


def with_other_load(watts=60, source="테스트 측정"):
    return {**RULES, "margins": {"power": {"other_load": {"watts": watts, "source": source}}}}


def owned_part(slot, name="유지 부품", source="catalog", **specs):
    return {"name": name, "specs": {**BASE[slot], **specs}, "source": source}


def owned_spec(*owned_slots, bought=(), **over_by_slot):
    """업그레이드: owned_slots 는 유지, bought 는 이번에 사는 슬롯(chosen 에 넣을 슬롯은 호출부가 따로 만든다)."""
    owned = {s: owned_part(s, **over_by_slot.get(s, {})) for s in owned_slots}
    return spec_of(targets=tuple(bought) or SLOTS, mode="upgrade", owned=owned)


# ── 전력: 기존 호환 검사와 같은 범위·계수 ─────────────────────────────────────────────────

def test_compat_check_matches_the_existing_formula_and_records_inputs_with_sources():
    chosen = full()
    chosen["CPU"] = chosen["CPU"].model_copy(update={"provenance": {
        "spec_url": "https://cpu.example/page", "checked_at": "2026-10-01", "by_key": {"max_power_w": "https://cpu.example/power"}}})
    item = margins_of(chosen)["power"]["compat_check"]
    assert item["status"] == "available" and item["unit"] == "W"
    assert item["value"] == 750 * 0.9 - (142 + 200)                    # PSU × 0.9 − (CPU 최대 + GPU)
    assert item["formula"] == "파워 정격 × 0.9 − (CPU + GPU)" and item["scope"] == "cpu_gpu" and item["factor"] == 0.9
    assert item["cpu_basis"] == "max_power" and "limits" not in item
    by_slot = {i["slot"]: i for i in item["inputs"]}
    assert by_slot["CPU"]["key"] == "max_power_w" and by_slot["CPU"]["value"] == 142 and by_slot["CPU"]["unit"] == "W"
    assert by_slot["CPU"]["source"] == "https://cpu.example/power" and by_slot["CPU"]["checked_at"] == "2026-10-01"
    assert by_slot["CPU"]["side"] == "purchase" and by_slot["CPU"]["name"] == "AMD Ryzen 7 7700X"
    assert by_slot["GPU"]["value"] == 200 and by_slot["파워"]["value"] == 750 and by_slot["GPU"]["source"] is None


def test_compat_check_agrees_with_the_existing_compat_row():
    chosen = full()
    row = next(r for r in __import__("src.engine.stage4_optimize", fromlist=["x"]).pc_compat_details(chosen, spec_of(), RULES)
               if r["axis"] == "power")
    item = margins_of(chosen)["power"]["compat_check"]
    assert row["state"] == "ok" and item["value"] >= 0
    low = full(**{"파워": {"wattage_w": 350}})
    row = next(r for r in __import__("src.engine.stage4_optimize", fromlist=["x"]).pc_compat_details(low, spec_of(), RULES)
               if r["axis"] == "power")
    assert row["state"] == "fail" and margins_of(low)["power"]["compat_check"]["value"] < 0


def test_missing_max_power_falls_back_to_tdp_and_records_the_limit():
    item = margins_of(full(CPU={"max_power_w": None}))["power"]["compat_check"]
    assert item["status"] == "available" and item["value"] == 750 * 0.9 - (105 + 200)
    assert item["cpu_basis"] == "tdp_fallback" and item["limits"] == ["TDP는 최대 패키지 전력보다 낮을 수 있음"]
    assert next(i for i in item["inputs"] if i["slot"] == "CPU")["key"] == "tdp_w"


def test_missing_gpu_power_is_unavailable_and_names_the_key():
    item = margins_of(full(GPU={"power_w": None}))["power"]["compat_check"]
    assert item["status"] == "unavailable" and item["value"] is None and item["reason"] == "inputs_missing"
    assert [(m["slot"], m["key"], m["side"]) for m in item["missing"]] == [("GPU", "power_w", "purchase")]


def test_total_is_unavailable_without_a_documented_other_load_and_keeps_the_known_load():
    assert RULES["margins"]["power"]["other_load"] is None
    total = margins_of()["power"]["total"]
    assert total["status"] == "unavailable" and total["reason"] == "other_load_basis_missing"
    assert total["value"] is None and total["known_load_w"] == 142 + 200 and total["factors_applied"] == []


def test_total_with_a_configured_other_load_does_not_multiply_the_safety_factors():
    margins = margins_of(rules=with_other_load(60, "측정 근거"))
    total = margins["power"]["total"]
    assert total["status"] == "available" and total["value"] == 750 - (142 + 200 + 60)
    assert total["factors_applied"] == [] and total["formula"] == "파워 정격 − (CPU + GPU + 기타)"
    other = next(i for i in total["inputs"] if i["key"] == "other_load")
    assert other["value"] == 60 and other["source"] == "측정 근거"
    # 호환 검사는 0.9 계수 그대로 — 두 값은 서로의 계수를 가져다 쓰지 않는다
    assert margins["power"]["compat_check"]["value"] == 750 * 0.9 - 342


def test_requirement_sizing_records_the_stage2_result_without_recomputing_it_and_factors_are_not_reapplied():
    from src.engine.stage2_requirement import _computer_build
    from src.engine.slots import slots_from_conditions
    from src.categories import load_category

    cat_def = load_category("computer")
    slots = slots_from_conditions("computer", cat_def, {"category": "computer", "mode": "build", "purpose": "game", "budget_max": 2_000_000})
    spec = _computer_build(slots, _noop)
    sizing = margins_of(spec=spec)["power"]["requirement_sizing"]
    assert sizing["status"] == "available" and sizing["value"] == spec.targets["파워"]["wattage_min"]
    assert sizing["purpose"] == "파워 최소 용량 요구 산정" and sizing["basis"] == "profile_estimate"
    assert sizing["estimated_power_w"] == {"cpu": 125, "gpu": 300, "other": 75} and sizing["headroom_multiplier"] == 1.5
    assert sizing["required_w"] == int((125 + 300 + 75) * 1.5)
    margins = margins_of(spec=spec)
    assert margins["power"]["compat_check"]["factor"] == 0.9                     # 1.5 는 요구 산정에만
    assert margins["power"]["total"]["factors_applied"] == [] and margins["power"]["total"]["status"] == "unavailable"


def test_other_load_format_is_validated_by_the_rules_loader(tmp_path):
    import yaml
    from src.engine import stage2_requirement as s2

    def load(other):
        data = yaml.safe_load(s2._COMPUTER_RULES_PATH.read_text(encoding="utf-8"))
        data["verification"]["margins"] = {"power": {"other_load": other}}
        path = tmp_path / f"rules_{abs(hash(repr(other)))}.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return load_computer_rules(path)

    assert load({"watts": 50, "source": "측정"})["verification"]["margins"]["power"]["other_load"]["watts"] == 50
    assert load(None)
    for bad in ({"watts": 0, "source": "x"}, {"watts": -5, "source": "x"}, {"watts": "50", "source": "x"},
                {"watts": 50, "source": " "}, {"watts": 50}, {"source": "x"}, {"watts": True, "source": "x"}, 75):
        with pytest.raises(RequirementRuleError, match="other_load"):
            load(bad)


# ── 크기 ──────────────────────────────────────────────────────────────────────────────────────

def test_size_margins_are_the_plain_differences_with_units():
    size = margins_of(full(GPU={"length_mm": 312.5}))["size"]
    assert size["gpu_length"]["value"] == 350 - 312.5 and size["gpu_length"]["unit"] == "mm"     # 반올림 없음
    assert size["cooler_height"]["value"] == 170 - 150 and size["psu_length"]["value"] == 200 - 160
    assert size["gpu_slots"]["value"] == 7 - 3 and size["gpu_slots"]["unit"] == "slot" and size["gpu_slots"]["required_slots"] == 3
    gpu_in = {(i["slot"], i["key"]): i["value"] for i in size["gpu_length"]["inputs"]}
    assert gpu_in == {("GPU", "length_mm"): 312.5, ("케이스", "max_gpu_len_mm"): 350}
    assert size["not_evaluated"] == [{"check": "cooler_ram_clearance", "reason": "쿨러의 RAM 간섭 허용 높이 정보 없음"}]


@pytest.mark.parametrize("slot,key,item", [("GPU", "length_mm", "gpu_length"), ("케이스", "max_gpu_len_mm", "gpu_length"),
                                           ("쿨러", "height_mm", "cooler_height"), ("케이스", "max_cooler_height_mm", "cooler_height"),
                                           ("파워", "length_mm", "psu_length"), ("케이스", "max_psu_length_mm", "psu_length"),
                                           ("GPU", "slot_thickness", "gpu_slots"), ("케이스", "expansion_slots", "gpu_slots")])
def test_a_missing_size_value_is_unavailable_with_no_substitute(slot, key, item):
    result = margins_of(full(**{slot: {key: None}}))["size"][item]
    assert result["status"] == "unavailable" and result["value"] is None
    assert [(m["slot"], m["key"]) for m in result["missing"]] == [(slot, key)]


def test_a_confirmed_negative_margin_is_recorded_as_is_and_the_set_stays_not_recommendable():
    chosen = full(GPU={"length_mm": 400})
    assert margins_of(chosen)["size"]["gpu_length"]["value"] == -50
    pools = {s: [c] for s, c in chosen.items()}
    build, _ = build_of(pools)
    assert build.eligibility["status"] == "not_recommendable"
    assert build.margins["size"]["gpu_length"]["value"] == -50                  # 진단 세트에도 음수 값이 그대로 남는다


def test_liquid_cooler_uses_the_radiator_item_and_skips_cooler_height():
    chosen = full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 240, "height_mm": None})
    size = margins_of(chosen)["size"]
    assert size["cooler_height"]["status"] == "not_applicable" and size["cooler_height"]["reason"] == "liquid_cooler"
    rad = size["radiator"]
    assert rad["status"] == "available" and rad["unit"] == "position"
    assert rad["fits_positions"] == ["front", "top"] and rad["value"] == 2
    assert {(i["slot"], i["key"]) for i in rad["inputs"]} >= {("쿨러", "radiator_mm"), ("케이스", "radiator_front_mm")}


def test_air_cooler_makes_the_radiator_not_applicable():
    rad = margins_of()["size"]["radiator"]
    assert rad["status"] == "not_applicable" and rad["reason"] == "air_cooler"


def test_liquid_cooler_with_no_case_radiator_info_is_unavailable_and_unknown_type_is_unavailable():
    blank = {"radiator_front_mm": None, "radiator_top_mm": None, "radiator_rear_mm": None}
    rad = margins_of(full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 240}, 케이스=blank))["size"]["radiator"]
    assert rad["status"] == "unavailable" and {m["key"] for m in rad["missing"]} == set(blank)
    unknown = margins_of(full(쿨러={"cooling_type": None}))["size"]
    assert unknown["cooler_height"]["status"] == unknown["radiator"]["status"] == "unavailable"
    assert unknown["cooler_height"]["missing"] == [{"slot": "쿨러", "key": "cooling_type", "side": "purchase"}]


def test_radiator_that_fits_nowhere_is_recorded_with_zero_positions():
    rad = margins_of(full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 360}))["size"]["radiator"]
    assert rad["status"] == "available" and rad["value"] == 0 and rad["fits_positions"] == []


# ── 냉각 ──────────────────────────────────────────────────────────────────────────────────────

def test_cooling_is_always_unavailable_with_inputs_and_no_tdp_difference_value():
    cooling = margins_of()["cooling"]
    assert cooling["status"] == "unavailable" and cooling["reason"] == "no_comparable_thermal_test" and cooling["value"] is None
    keys = {(i["slot"], i["key"]) for i in cooling["inputs"]}
    assert {("CPU", "tdp_w"), ("CPU", "max_power_w"), ("쿨러", "cooling_type"), ("쿨러", "height_mm"), ("케이스", "name"),
            ("CPU", "name")} <= keys
    assert cooling["power_setting"] == "기본 설정 가정(사용자 전력 제한 정보 없음)"
    assert set(cooling["mounting"]) == {"cooler_socket", "cooler_height", "radiator"}
    assert cooling["mounting"]["cooler_height"]["state"] == "ok" and cooling["mounting"]["radiator"]["state"] == "skipped"
    # 어떤 부품 조합이어도 TDP 차이 같은 수치로 확정하지 않는다
    for chosen in (full(), full(CPU={"tdp_w": 253, "max_power_w": 253}), full(쿨러={"cooling_type": "Liquid (AIO)", "radiator_mm": 240})):
        assert margins_of(chosen)["cooling"]["status"] == "unavailable"


# ── 업그레이드: 유지 부품 · 바뀌지 않는 축 ─────────────────────────────────────────────────

def test_upgrade_uses_kept_psu_and_case_values_and_marks_them_owned():
    chosen = {"GPU": part("GPU", length_mm=320)}
    spec = owned_spec("CPU", "파워", "케이스", bought=("GPU",), 파워={"wattage_w": 650})
    spec.owned["파워"]["source"] = "live"
    spec.owned["파워"]["source_url"] = "https://live.example/psu"
    margins = evaluate_margins(chosen, spec, RULES)
    power = margins["power"]["compat_check"]
    assert power["status"] == "available" and power["value"] == 650 * 0.9 - (142 + 200)
    sides = {i["slot"]: i for i in power["inputs"]}
    assert sides["GPU"]["side"] == "purchase" and sides["CPU"]["side"] == "owned" and sides["파워"]["side"] == "owned"
    assert sides["파워"]["source_kind"] == "live" and sides["파워"]["source"] == "https://live.example/psu"
    assert margins["size"]["gpu_length"]["value"] == 350 - 320
    assert next(i for i in margins["size"]["gpu_length"]["inputs"] if i["slot"] == "케이스")["side"] == "owned"


def test_upgrade_axes_without_a_purchased_part_are_not_applicable():
    chosen = {"GPU": part("GPU")}
    spec = owned_spec("CPU", "쿨러", "케이스", "파워", bought=("GPU",))
    size = evaluate_margins(chosen, spec, RULES)["size"]
    assert size["cooler_height"]["status"] == "not_applicable" and size["cooler_height"]["reason"] == "no_purchased_part"
    assert size["psu_length"]["status"] == "not_applicable" and size["radiator"]["status"] == "not_applicable"
    assert size["gpu_length"]["status"] == "available" and size["gpu_slots"]["status"] == "available"
    ram_only = evaluate_margins({"RAM": part("RAM")}, owned_spec("CPU", "GPU", "파워", "케이스", bought=("RAM",)), RULES)
    assert ram_only["power"]["compat_check"]["status"] == "not_applicable"
    assert ram_only["power"]["total"]["status"] == "not_applicable"
    assert ram_only["power"]["requirement_sizing"]["reason"] == "power_not_in_scope"


def test_upgrade_with_a_kept_part_missing_a_value_is_unavailable_and_says_owned():
    chosen = {"GPU": part("GPU")}
    spec = owned_spec("CPU", "파워", "케이스", bought=("GPU",), 파워={"wattage_w": None})
    item = evaluate_margins(chosen, spec, RULES)["power"]["compat_check"]
    assert item["status"] == "unavailable"
    assert [(m["slot"], m["key"], m["side"]) for m in item["missing"]] == [("파워", "wattage_w", "owned")]


def test_upgrade_gpu_recommended_psu_path_records_the_same_inputs_as_the_existing_check():
    chosen = {"GPU": part("GPU", recommended_psu_w=600)}
    spec = owned_spec("파워", bought=("GPU",), 파워={"wattage_w": 750})
    item = evaluate_margins(chosen, spec, RULES)["power"]["compat_check"]
    assert item["status"] == "available" and item["scope"] == "gpu_recommended_psu" and item["value"] == 750 - 600
    assert {i["key"] for i in item["inputs"]} == {"recommended_psu_w", "wattage_w"}
    assert item["limits"] == ["CPU 전력을 몰라 전체 소비전력은 확인하지 못함"]


# ── 불변성: 여유는 기록일 뿐 ───────────────────────────────────────────────────────────────

def _fingerprint(build, verification):
    t = verification.targets[0]
    return ([(i.slot, i.product_key, i.score) for i in build.items], build.link_check, build.eligibility,
            (t.confidence, t.passed, t.eligible, t.blocking))


def test_margins_do_not_change_selection_scores_confidence_or_eligibility(monkeypatch):
    pools = {s: [part(s, key=f"{s}-a", price=10_000, score=0.9), part(s, key=f"{s}-b", price=9_000, score=0.8)] for s in SLOTS}

    def run():
        build, spec = build_of(pools)
        chosen = {i.slot: next(c for c in pools[i.slot] if c.product_key == i.product_key) for i in build.items}
        return build, _fingerprint(build, stage3c_verify.verify_build(build, "computer", _noop, chosen=chosen, spec=spec, rules=RULES))

    real_build, real = run()
    assert real_build.margins["version"] == 1
    monkeypatch.setattr(build_margins, "evaluate_margins", lambda *a, **k: {})
    empty_build, other = run()
    assert empty_build.margins == {} and other == real
    monkeypatch.setattr(build_margins, "evaluate_margins", lambda *a, **k: {"version": 1, "power": {"x": -10_000}})
    assert run()[1] == real


def test_a_large_margin_does_not_offset_another_violation():
    chosen = full(파워={"wattage_w": 2000}, GPU={"length_mm": 400})        # 전력 여유는 아주 크지만 GPU 길이는 맞지 않음
    margins = margins_of(chosen)
    assert margins["power"]["compat_check"]["value"] > 1000 and margins["size"]["gpu_length"]["value"] < 0
    build, _ = build_of({s: [c] for s, c in chosen.items()})
    assert build.eligibility["status"] == "not_recommendable"
    assert "compat_violation" in [r["code"] for r in build.eligibility["reasons"]]


def test_date_inputs_are_json_serializable():
    import json
    from datetime import date

    chosen = full(GPU={"length_mm": 312.5})
    chosen["GPU"] = chosen["GPU"].model_copy(update={"provenance": {"spec_url": "u", "checked_at": date(2026, 10, 1)}})
    margins = margins_of(chosen)
    assert json.loads(json.dumps(margins)) == margins
    assert margins["size"]["gpu_length"]["value"] == 37.5
