"""정책 변경 비교 지표 요약(scripts/engine_policy_report.py)의 순수 함수 — 작은 가짜 덤프로 확인한다. DB·LLM 없음.

고정 시나리오 스크립트(scripts/engine_policy_scenarios.py)가 기대와 모두 일치하는지도 함께 본다(DB 없이 메모리 카탈로그로 돈다).
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

report = importlib.import_module("engine_policy_report")


def item(slot, key, tier=0.0, **extra):
    return {"slot": slot, "product_key": key, "perf_tier": tier, "price": 100, **extra}


def rec(rid, *, status="recommendable", items=(), used=50.0, max_=100, noise=None, purpose="game", priority=None,
        floors=None, link=None, verification=None, hardfilter=None, reasons=(), **extra):
    elig = {"status": status, "reasons": list(reasons)} if status else None
    values = {"mode": "build", "purpose": purpose, "budget_max": max_}
    if noise is not None:
        values["noise_sensitive"] = noise
    if priority:
        values["priority"] = priority
    out = {"id": rid, "values": values, "wall_ms": 100,
           "build": {"items": list(items), "totals": {"price": used}, "budget": {"max": max_, "used": used, "used_pct": used / max_ * 100},
                     "link_check": link or {}, "eligibility": elig, "margins": None},
           "budget_used_pct": used / max_ * 100, "verification": verification or [], "hardfilter": hardfilter or {}, **extra}
    if floors is not None:
        out["target_floors"] = floors
    return out


def dump(*recs, commit="abc12345def", dirty=False):
    return {"git_commit": commit, "git_dirty": dirty, "requests": list(recs)}


# ── 분류·기본 통계 ────────────────────────────────────────────────────────────────

def test_classify_separates_shortage_other_errors_unjudged_and_eligibility():
    assert report.classify({"error": {"type": "CandidateShortage"}}) == "shortage"
    assert report.classify({"error": {"type": "ValueError"}}) == "error"
    assert report.classify(rec("a", status=None)) == "unjudged"
    assert report.classify(rec("a")) == "recommendable"
    assert report.classify(rec("a", status="not_recommendable")) == "not_recommendable"


def test_shortage_is_counted_over_all_requests_not_hidden():
    d = dump(rec("a"), rec("b", status="not_recommendable"), {"id": "c", "error": {"type": "CandidateShortage", "attrs": {"slots": {"GPU": {}}}}},
             {"id": "d", "error": {"type": "KeyError"}})
    assert report.outcome_counts(d) == {"recommendable": 1, "not_recommendable": 1, "shortage": 1, "error": 1, "unjudged": 0}
    assert report.shortage_slots(d) == {"GPU": 1}
    table = report.stage_table([("x", d)])
    assert "1 (25.0%)" in table                              # 분모는 전체 요청 4건


def test_percentile_is_nearest_rank_and_mean_ignores_none():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert report.percentile(values, 50) == 50 and report.percentile(values, 90) == 90 and report.percentile(values, 100) == 100
    assert report.percentile([], 50) is None and report.percentile([None], 50) is None
    assert report.mean([1, None, 3]) == 2 and report.mean([]) is None


def test_timing_uses_wall_ms():
    d = dump(*[{**rec(str(i)), "wall_ms": ms} for i, ms in enumerate([100, 200, 300, 400, 1000])])
    t = report.timing(d)
    assert (t["n"], t["mean"], t["p50"], t["p90"], t["max"]) == (5, 400, 300, 1000, 1000)
    assert "측정 조건: 단독" in report.timing_table([("x", d)], "단독")


def test_table_escapes_pipes_and_formats_none():
    assert report.table(["a", "b"], [["x|y", None]]) == "| a | b |\n|---|---|\n| x\\|y | n/a |"


# ── 슬롯·사유 ────────────────────────────────────────────────────────────────────

def test_slot_counts_sum_and_average_with_reason_distributions():
    d = dump(rec("a", hardfilter={"GPU": {"pass": 4, "pending": 2, "fail": 1, "pending_reasons": {"P:x": 2}, "fail_reasons": {"F": 1}}}),
             rec("b", hardfilter={"GPU": {"pass": 2, "pending": 0, "fail": 3, "pending_reasons": {}, "fail_reasons": {"F": 2, "G": 1}}}))
    gpu = report.slot_counts(d)["GPU"]
    assert (gpu["n"], gpu["pass"], gpu["pass_mean"], gpu["pending"], gpu["fail"]) == (2, 6, 3.0, 2, 4)
    assert gpu["pending_reasons"] == {"P:x": 2} and gpu["fail_reasons"] == {"F": 3, "G": 1}


def test_ineligible_reason_distribution_counts_each_code():
    d = dump(rec("a", status="not_recommendable", reasons=[{"code": "budget_exceeded"}, {"code": "compat_violation"}]),
             rec("b", status="not_recommendable", reasons=[{"code": "budget_exceeded"}]), rec("c"))
    assert report.ineligible_reasons(d) == {"budget_exceeded": 2, "compat_violation": 1}


def test_missing_by_part_names_owned_and_purchased_sides():
    reason = {"code": "required_info_missing", "missing": [{"slot": "파워", "key": "wattage_w", "side": "owned"},
                                                           {"slot": "케이스", "key": "x", "side": "purchase"}]}
    d = dump(rec("a", status="not_recommendable", reasons=[reason]), rec("b", status="not_recommendable", reasons=[reason]))
    assert report.missing_by_part(d) == {"구매:케이스.x": 2, "유지:파워.wattage_w": 2}


# ── 선택·순위·예산 ───────────────────────────────────────────────────────────────

def test_selection_changes_count_slots_and_requests():
    ref = dump(rec("a", items=[item("CPU", "c1"), item("GPU", "g1")]), rec("b", items=[item("CPU", "c1")]), rec("only-ref", items=[item("CPU", "c1")]))
    cur = dump(rec("a", items=[item("CPU", "c2"), item("GPU", "g1")]), rec("b", items=[item("CPU", "c1")]), rec("new", items=[item("CPU", "c9")]))
    assert report.selection_changes(ref, cur) == {"pairs": 2, "changed_any": 1, "per_slot": {"CPU": 1}}


def test_adjacent_table_compares_each_stage_with_the_previous_one():
    d0 = dump(rec("a", items=[item("CPU", "c1")]))
    d1 = dump(rec("a", items=[item("CPU", "c2")]))
    d2 = dump(rec("a", items=[item("CPU", "c2")]))
    text = report.adjacent_table([("0", d0), ("1", d1), ("2", d2)])
    assert "| 1 | 1 | 1 (100.0%) | 1 |" in text and "| 2 | 1 | 0 (0.0%) | 0 |" in text


def test_rank_stats_use_a_common_top5_cut_and_report_the_full_rank_when_present():
    old = rec("a", items=[item("CPU", "c1"), item("GPU", "g9")], rank={"top": {"CPU": [{"product_key": "c0"}, {"product_key": "c1"}], "GPU": [{"product_key": "g0"}]}})
    new = rec("a", items=[item("CPU", "c1", rank_in_3b=2), item("GPU", "g9", rank_in_3b=12)], rank={"top": {}})
    s_old, s_new = report.rank_stats(dump(old)), report.rank_stats(dump(new))
    assert s_old["CPU"] == {"mean_top5": 2, "n_top5": 1, "outside_top5": 0, "full_mean": None} and s_old["GPU"]["outside_top5"] == 1
    assert s_new["CPU"]["mean_top5"] == 2 and s_new["GPU"]["outside_top5"] == 1 and s_new["GPU"]["full_mean"] == 12


def test_budget_stats_separate_all_built_from_recommendable_only():
    d = dump(rec("a", used=80), rec("b", used=120, status="not_recommendable"), rec("c", used=40))
    assert report.budget_stats(d)["n"] == 3
    only = report.budget_stats(d, ("recommendable", "unjudged"))
    assert only["n"] == 2 and only["used_mean"] == 60 and only["used_max"] == 80


def test_ram_stats_count_pair_configurations_and_list_catalog_prices():
    d = dump(rec("a", items=[item("RAM", "r1", qty=2, price=120)]), rec("b", items=[item("RAM", "r2", qty=1, price=140)]))
    d["ram_pair_prices"] = {"DDR5-32GB": {"kit": 140, "single_pair": 120}}
    assert report.ram_stats(d) == {"n": 2, "single_pair": 1, "kit": 1, "price_mean": 130}
    text = report.ram_table([("x", d)])
    assert "DDR5-32GB | 140 | 120" in text


def test_budget_same_requests_uses_only_requests_recommendable_in_the_final_dump():
    base = dump(rec("a", used=80), rec("b", used=140))
    final = dump(rec("a", used=60), rec("b", status="not_recommendable", used=140))
    text = report.budget_same_requests([("old", base), ("new", final)])
    assert "| old | 1 | 80.00 | 80 |" in text and "| new | 1 | 60.00 | 60 |" in text


def test_counter_stats_sum_prunings_and_count_requests_with_widened_or_capped_search():
    a = rec("a")
    a["build"]["alternatives"] = {"pruned_compat": 3, "pruned_budget": 0, "widened": 1}
    b = rec("b")
    b["build"]["alternatives"] = {"pruned_compat": 2, "capped": 1}
    st = report.counter_stats(dump(a, b))
    assert st["pruned_total"] == {"pruned_budget": 0, "pruned_compat": 5}
    assert st["requests_with"] == {"capped": 1, "pruned_budget": 0, "pruned_compat": 2, "widened": 1} and st["requests"] == 2
    assert "pruned_compat 발생 요청" in report.counter_table([("x", dump(a, b))])


def test_budget_monotonic_flags_a_cheaper_build_for_a_bigger_budget():
    def perf(budget, price, purpose="game"):
        return rec(f"{purpose}{budget}", priority="performance", noise=False, purpose=purpose, max_=budget, used=price)

    ok = dump(perf(1000, 900), perf(2000, 1800), perf(3500, 1790))               # 1800 → 1790 은 5% 안
    bad = dump(perf(1000, 900), perf(2000, 1800), perf(3500, 1500))
    assert report.budget_monotonic(ok) == [{"purpose": "game", "totals": [900, 1800, 1790], "ok": True}]
    assert report.budget_monotonic(bad)[0]["ok"] is False
    assert "1,500" in report.budget_monotonic_table([("x", bad)])


# ── 저소음 ───────────────────────────────────────────────────────────────────────

def _review(profile_quiet, quiet):
    return {"value": 0.5, "profile_alpha_sum": 1.0, "profile_quiet_alpha": profile_quiet,
            "quiet": [{"aspect": "fan_quietness", "context": "low_load", "alpha": a, "q": 0.5, "state": "observed"} for a in quiet]}


def test_noise_pairs_compare_selection_weights_and_quiet_evidence():
    w = {"가격": 0.4, "성능": 0.4, "리뷰": 0.2}
    quiet = rec("q", noise=True, items=[item("쿨러", "k2", review=_review(0.3, [0.3]))], rank={"weights_used": w})
    normal = rec("n", noise=False, items=[item("쿨러", "k1", review=_review(0.2, []))], rank={"weights_used": w})
    other = rec("o", noise=False, items=[item("쿨러", "k1")], max_=200, rank={"weights_used": w})        # 짝이 없는 요청
    n = report.noise_pairs(dump(quiet, normal, other))
    assert n["pairs"] == 1 and n["selection_differs"] == 1 and n["per_slot"] == {"쿨러": 1}
    assert n["outer_weights_differ"] == 0 and n["profile_quiet_alpha_differs"] == 1
    assert n["noise1"] == {"items": 1, "with_quiet_contribution": 1, "profile_quiet_alpha_mean": 0.3}
    assert n["noise0"]["with_quiet_contribution"] == 0
    assert n["quiet_alpha_delta_by_priority"] == {"none": pytest.approx(0.1)}
    assert "none" in report.noise_delta_table(dump(quiet, normal))
    assert report.noise_pairs(dump(rec("x", noise=True), rec("y", noise=False)))["noise1"]["profile_quiet_alpha_mean"] is None   # 리뷰 근거 없는 옛 덤프


# ── 필수 조건 위반 ───────────────────────────────────────────────────────────────

def test_violations_find_budget_perf_compat_and_ineligible_reasons_only_in_recommendable_results():
    ok = rec("ok", items=[item("GPU", "g", 6)], floors={"GPU": 5}, link={"socket": "ok", "ram_speed": "ok (근사)"})
    over = rec("over", used=130, items=[item("GPU", "g", 6)], floors={"GPU": 5})
    low = rec("low", items=[item("GPU", "g", 4)], floors={"GPU": 5})
    bad_link = rec("link", items=[item("GPU", "g", 6)], floors={"GPU": 5}, link={"socket": "fail", "budget": "fail"})
    leaked = rec("leak", items=[item("GPU", "g", 6)], floors={"GPU": 5}, reasons=[{"code": "required_info_missing"}])
    blocked = rec("blocked", items=[item("GPU", "g", 6)], floors={"GPU": 5},
                  verification=[{"eligible": False, "blocking": [{"code": "x"}]}])
    skipped = rec("skip", status="not_recommendable", used=500)                      # 부적격은 검사 대상이 아니다
    v = report.violations(dump(ok, over, low, bad_link, leaked, blocked, skipped))
    assert v["checked"] == 6
    assert sorted((x["id"], x["kind"]) for x in v["list"]) == [
        ("blocked", "verification_blocking"), ("leak", "required_info_missing"), ("link", "compat_violation"),
        ("low", "perf_below_min"), ("over", "budget_exceeded")]
    assert report.violations(dump(ok))["count"] == 0


def test_violations_count_requests_whose_dump_has_no_performance_floor():
    v = report.violations(dump(rec("a", items=[item("GPU", "g", 1)])))
    assert v["requests_without_target_floors"] == 1 and v["count"] == 0


# ── 보완 ─────────────────────────────────────────────────────────────────────────

def test_enrichment_stats_report_fill_and_return_rates():
    attempts = [{"status": "filled", "returned_to_pass": True}, {"status": "filled", "returned_to_pass": False},
                {"status": "not_found", "returned_to_pass": False}, {"status": "no_path", "returned_to_pass": False}]
    combo = {"attempted": 2, "filled": 1, "rerun": True, "attempts": [{"status": "filled"}, {"status": "not_found"}]}
    e = report.enrichment_stats(dump(rec("a", enrichment=attempts, combo_enrichment=combo), rec("b")))
    assert (e["prefilter_attempted"], e["prefilter_filled"], e["prefilter_returned"]) == (4, 2, 1)
    assert e["prefilter_fill_rate"] == 0.5 and e["prefilter_return_rate"] == 0.25
    assert e["prefilter_status"] == {"filled": 2, "no_path": 1, "not_found": 1}
    assert (e["combo_requests"], e["combo_attempted"], e["combo_filled"], e["combo_rerun"]) == (1, 2, 1, 1)
    assert e["combo_status"] == {"filled": 1, "not_found": 1}


# ── 여유 ─────────────────────────────────────────────────────────────────────────

def _inp(slot, key, value):
    return {"slot": slot, "side": "purchase", "key": key, "value": value, "unit": "mm"}


MARGINS = {
    "size.gpu_length": {"status": "available", "value": 50, "inputs": [_inp("GPU", "length_mm", 300), _inp("케이스", "max_gpu_len_mm", 350)]},
    "size.gpu_slots": {"status": "available", "value": 4, "inputs": [_inp("GPU", "slot_thickness", 2.5), _inp("케이스", "expansion_slots", 7)]},
    "power.compat_check": {"status": "available", "value": 445.0, "scope": "cpu_gpu", "factor": 0.9,
                           "inputs": [_inp("CPU", "tdp_w", 65), _inp("GPU", "power_w", 165), _inp("파워", "wattage_w", 750)]},
    "power.requirement_sizing": {"status": "available", "value": 750, "inputs": []},
    "power.total": {"status": "unavailable", "reason": "other_load_basis_missing", "missing": ["GPU.power_w"], "inputs": []},
    "cooling": {"status": "unavailable", "reason": "no_comparable_thermal_test", "inputs": []},
}


def test_margin_values_are_recomputed_from_inputs():
    d = dump(rec("a", margins=None))
    d["requests"][0]["build"]["margins"] = MARGINS
    repro = report.margin_reproduction(d)
    assert (repro["checked"], repro["mismatches"], repro["recorded_only"]) == (3, 0, 1)
    assert report.margin_status_counts(d)["cooling"] == {"unavailable": 1}
    assert report.margin_unavailable_reasons(d)["power.total"] == {"other_load_basis_missing / GPU.power_w": 1}
    assert report.margin_unavailable_reasons(d)["cooling"] == {"no_comparable_thermal_test": 1}


def test_margin_reproduction_flags_a_value_that_does_not_follow_from_its_inputs():
    broken = {**MARGINS, "size.gpu_length": {**MARGINS["size.gpu_length"], "value": 49}}
    d = dump(rec("a"))
    d["requests"][0]["build"]["margins"] = broken
    repro = report.margin_reproduction(d)
    assert repro["mismatches"] == 1 and repro["list"][0]["item"] == "size.gpu_length" and repro["list"][0]["recomputed"] == 50


def test_recompute_margin_other_shapes():
    rad = {"status": "available", "value": 2, "fits_positions": ["front", "top"], "inputs": []}
    assert report.recompute_margin("size.radiator", rad) == 2
    rec_psu = {"scope": "gpu_recommended_psu", "inputs": [_inp("파워", "wattage_w", 750), _inp("GPU", "recommended_psu_w", 600)]}
    assert report.recompute_margin("power.compat_check", rec_psu) == 150
    total = {"inputs": [_inp("CPU", "tdp_w", 65), _inp("GPU", "power_w", 165), _inp("파워", "wattage_w", 750),
                        {"slot": None, "key": "other_load", "value": 100}]}
    assert report.recompute_margin("power.total", total) == 420
    assert report.recompute_margin("cooling", {"inputs": []}) is None


# ── 시나리오 표·전체 렌더 ─────────────────────────────────────────────────────────

SCENARIOS = {"scenarios": [{"id": "13", "title": "GPU 커넥터", "tests": ["tests/test_x.py::test_y"], "mismatch": True, "cases": [
    {"name": "a", "expected": {"outcome": "recommendable", "missing_has": ["m"]}, "actual": {"outcome": "recommendable", "missing": ["m"]}, "mismatch": False},
    {"name": "b", "expected": {"outcome": "recommendable"}, "actual": {"outcome": "not_recommendable"}, "mismatch": True}]}]}


def test_scenario_tables_show_expected_actual_match_and_tests():
    text = report.scenario_table(SCENARIOS)
    assert "일치" in text and "**불일치**" in text and "missing" in text
    assert "test_x.py::test_y" in report.scenario_tests_table(SCENARIOS)
    group = report.scenario_group_table(SCENARIOS, ("13",))
    assert "정상 추천 1/2 (50.0%)" in group


def test_render_smoke_with_minimal_dumps():
    base = dump(rec("a", status=None, items=[item("CPU", "c")], hardfilter={"CPU": {"pass": 1, "pending": 0, "fail": 0}}))
    final = dump(rec("a", items=[item("CPU", "c", 5)], floors={"CPU": 3}, hardfilter={"CPU": {"pass": 1, "pending": 0, "fail": 0}}))
    text = report.render([("0 기준선", base), ("최종", final)], SCENARIOS, "단독 실행")
    for heading in ("## 단계별 요약", "## 필수 조건 위반", "## 정보 보완", "## 요청당 처리 시간", "## 고정 시나리오"):
        assert heading in text
    assert "측정 조건: 단독 실행" in text


# ── 고정 시나리오(DB 없음) ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def scenarios_module():
    os.environ.setdefault("MOCK_MODE", "1")
    return importlib.import_module("engine_policy_scenarios")


def test_matches_rule_suffixes(scenarios_module):
    m = scenarios_module.matches
    actual = {"a": 5, "items": ["x", "y"], "d": {"k": 1, "z": 2}}
    assert m({"a": 5}, actual) and not m({"a": 6}, actual)
    assert m({"a_min": 5}, actual) and not m({"a_min": 6}, actual) and not m({"b_min": 1}, actual)
    assert m({"items_has": ["y"]}, actual) and not m({"items_has": ["q"]}, actual)
    assert m({"d_sub": {"k": 1}}, actual) and not m({"d_sub": {"k": 2}}, actual)


def test_every_fixed_scenario_matches_its_expectation(scenarios_module):
    results = [fn() for fn in scenarios_module.SCENARIOS]
    assert [s["id"] for s in results] == [f"{i:02d}" for i in range(1, 21)]
    assert [(s["id"], c["name"]) for s in results for c in s["cases"] if c["mismatch"]] == []
    assert all(s["tests"] for s in results)


# ── GPU·쿨러 미구매 규칙 지표(computer-rules-v14) ─────────────────────────────────────────────

def light_rec(rid, *, omitted, items, cpu, purpose="office", status="recommendable"):
    return rec(rid, items=items, purpose=purpose, status=status, omitted_slots=omitted, selected_cpu=cpu)


def test_request_group_splits_light_game_and_upgrade():
    assert report.request_group({"values": {"mode": "build", "purpose": "office"}}) == "사무·학습·기타 새 PC"
    assert report.request_group({"values": {"mode": "build", "purpose": "other"}}) == "사무·학습·기타 새 PC"
    assert report.request_group({"values": {"mode": "build", "purpose": "creation"}}) == "게임·창작 새 PC"
    assert report.request_group({"values": {"mode": "upgrade", "purpose": "office"}}) == "업그레이드"


def test_light_rule_check_uses_the_recorded_omitted_slots_per_request():
    good_cpu = {"integrated_graphics": "O", "cooler_included": "O (정품 박스 기준)", "tdp_w": 65}
    d = dump(
        light_rec("ok", omitted={"GPU": "integrated_graphics", "쿨러": "box_cooler"}, items=[item("CPU", "c")], cpu=good_cpu),
        # 저소음: 쿨러를 다시 넣었으므로 기본 쿨러 X 인 CPU 도 위반이 아니고, 쿨러 품목이 있어도 위반이 아니다
        light_rec("quiet", omitted={"GPU": "integrated_graphics"}, items=[item("CPU", "c"), item("쿨러", "k")],
                  cpu={"integrated_graphics": "O", "cooler_included": "X", "tdp_w": 105}),
        light_rec("bad_cpu", omitted={"GPU": "integrated_graphics", "쿨러": "box_cooler"}, items=[item("CPU", "c")],
                  cpu={"integrated_graphics": "X", "cooler_included": "O", "tdp_w": 65}),
        light_rec("leak", omitted={"GPU": "integrated_graphics"}, items=[item("CPU", "c"), item("GPU", "g")], cpu=good_cpu),
        light_rec("old", omitted=None, items=[item("CPU", "c")], cpu=None),
    )
    d["requests"][-1].pop("omitted_slots"), d["requests"][-1].pop("selected_cpu")
    check = report.light_rule_check(d)
    assert check["recommendable"] == 5 and check["no_record"] == 1 and check["cooler_kept"] == 2
    assert check["cpu_checked"] == 4 and len(check["bad_cpu"]) == 1 and check["bad_cpu"][0].startswith("bad_cpu")
    assert check["leaked"] == ["leak: GPU 품목이 있음"]
    assert "GPU·쿨러 미구매 규칙" in "\n".join(report.omission_section([("기준선", d), ("최종", d)]))


def test_unchanged_table_compares_selection_and_price_by_request_id():
    a = rec("g1", purpose="game", items=[item("CPU", "c1", qty=1)], used=100)
    b = rec("g2", purpose="game", items=[item("CPU", "c1", qty=1)], used=100)
    changed = rec("g2", purpose="game", items=[item("CPU", "c2", qty=1)], used=100)
    text = report.unchanged_table([("기준선", dump(a, b)), ("최종", dump(a, changed))])
    row = next(line for line in text.splitlines() if line.startswith("| 게임·창작 새 PC"))
    assert "| 2 | 1 | 1 | g2 |" in row
