"""주변기기 per_item 분기(E11) 테스트 — 추천엔진 구현계획 §3.3.

DB 불필요. 후보는 tests/fixtures/peripherals/*.csv(mock 로더, E9)로 읽는다.
다룬다: spec_rules 평가기(연산자 5종·최악 채택·중복 pref), [3-A] filter_candidates
(QHD_165/FHD_144), [3-B] rank_candidates(선호적합 순서), 조합(choose, 예산·절단),
[3-C] verify_per_item(Pending 축·데이터 결손 감점), run_peripherals 진입점, pipeline
불변/확장(monkeypatch).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import CONFIDENCE_THRESHOLD
from src.dto import Candidate, Issue, PeripheralPick, PeripheralRequirement
from src.engine import spec_rules
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_requirement import build_requirements
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import choose, filter_candidates, rank_candidates, run_peripherals
from src.engine.stage3c_verify import verify_per_item

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_NOLOG = lambda _m: None  # noqa: E731


def _rules():
    return load_peripheral_rules()


def _candidates():
    return load_peripheral_candidates_from_csv(_FIXTURES, _rules())


# ── spec_rules: 연산자 5종 ───────────────────────────────────────────────
def test_evaluate_min_pass_fail_pending():
    pref = {"key": "x", "op": "min", "value": 10}
    assert spec_rules.evaluate(pref, {"x": 15})[0] == "Pass"
    assert spec_rules.evaluate(pref, {"x": 5})[0] == "Fail"
    assert spec_rules.evaluate(pref, {})[0] == "Pending"
    assert spec_rules.evaluate(pref, {"x": None})[0] == "Pending"


def test_evaluate_max_pass_fail_pending():
    pref = {"key": "x", "op": "max", "value": 10}
    assert spec_rules.evaluate(pref, {"x": 5})[0] == "Pass"
    assert spec_rules.evaluate(pref, {"x": 15})[0] == "Fail"
    assert spec_rules.evaluate(pref, {})[0] == "Pending"


def test_evaluate_equals_pass_fail_pending():
    pref = {"key": "flag", "op": "equals", "value": False}
    assert spec_rules.evaluate(pref, {"flag": False})[0] == "Pass"
    assert spec_rules.evaluate(pref, {"flag": True})[0] == "Fail"
    assert spec_rules.evaluate(pref, {})[0] == "Pending"


def test_evaluate_member_of_pass_fail_pending():
    pref = {"key": "cls", "op": "member_of", "value": ["QHD", "UHD"]}
    assert spec_rules.evaluate(pref, {"cls": "QHD"})[0] == "Pass"
    assert spec_rules.evaluate(pref, {"cls": "FHD"})[0] == "Fail"
    assert spec_rules.evaluate(pref, {})[0] == "Pending"


def test_evaluate_contains_any_case_insensitive_partial_match():
    pref = {"key": "panel_raw", "op": "contains_any", "value": ["IPS", "OLED"]}
    assert spec_rules.evaluate(pref, {"panel_raw": "고급 ips 패널"})[0] == "Pass"
    assert spec_rules.evaluate(pref, {"panel_raw": "VA 패널"})[0] == "Fail"
    assert spec_rules.evaluate(pref, {})[0] == "Pending"


def test_evaluate_all_worst_verdict_wins():
    prefs = [
        {"key": "a", "op": "min", "value": 10},   # Pass (a=20)
        {"key": "b", "op": "min", "value": 10},   # Pending (없음)
        {"key": "c", "op": "min", "value": 10},   # Fail (c=1)
    ]
    verdict, reasons = spec_rules.evaluate_all(prefs, {"a": 20, "c": 1})
    assert verdict == "Fail"
    assert reasons and all("c" in r for r in reasons)


def test_evaluate_all_dedupes_identical_pref():
    prefs = [{"key": "a", "op": "equals", "value": True}, {"key": "a", "op": "equals", "value": True}]
    verdict, reasons = spec_rules.evaluate_all(prefs, {})
    assert verdict == "Pending"
    assert reasons == ["a: 값 없음"]   # 중복이면 이유가 두 번이 아니라 한 번만 나온다


def test_evaluate_all_empty_prefs_is_pass():
    assert spec_rules.evaluate_all([], {"anything": 1}) == ("Pass", [])


# ── [3-A] filter_candidates ──────────────────────────────────────────────
def test_qhd165_monitor_filter_keeps_only_qhd_165_or_higher():
    rules = _rules()
    cands = _candidates()
    req = build_requirements({"resolution": "QHD_165"}, ["monitor"], rules)["monitor"]
    kept, stats = filter_candidates("monitor", req, cands["monitor"])
    # 픽스처: LG UltraGear 27GP850(QHD,165Hz), Samsung Odyssey G5(QHD,180Hz) 만 통과.
    # ASUS VA24DQSB(FHD), ProArt PA279CRV(UHD), ProArt PA34VCNV(QHD_WIDE), Apple Studio
    # Display(5120x2880, OTHER)는 등급 불일치로 Fail.
    assert {c.name for c in kept} == {"LG UltraGear 27GP850", "Samsung Odyssey G5 G50F LS27FG504"}
    assert stats == {"pool": 6, "pass": 2, "fail": 4, "pending": 0}


def test_fhd144_monitor_filter_is_empty_and_reason_is_readable():
    rules = _rules()
    cands = _candidates()
    req = build_requirements({"resolution": "FHD_144"}, ["monitor"], rules)["monitor"]
    kept, stats = filter_candidates("monitor", req, cands["monitor"])
    # ASUS VA24DQSB는 FHD지만 75Hz뿐이라 144Hz 하한을 못 채워 전부 탈락한다.
    assert kept == []
    assert stats["fail"] == 6


def test_filter_candidates_never_relaxes_condition_when_pool_is_empty():
    """빈 결과일 때 조건을 완화해 다른 것으로 채우지 않는다(계획 §3.3 C6)."""
    rules = _rules()
    req = build_requirements({"resolution": "FHD_144"}, ["monitor"], rules)["monitor"]
    kept, _ = filter_candidates("monitor", req, [])
    assert kept == []


# ── [3-B] rank_candidates: 선호적합 순서 ──────────────────────────────────
def test_rank_candidates_preference_axis_orders_pass_over_pending_over_fail():
    req = PeripheralRequirement(
        kind="mouse", hard={}, soft={"preferences": [{"key": "polling_hz_max", "op": "min", "value": 1000}]},
    )
    cand_pass = Candidate(product_key="p1", slot="mouse", name="1000Hz 이상", price=50000,
                          specs={"polling_hz_max": 2000.0})
    cand_pending = Candidate(product_key="p2", slot="mouse", name="공란", price=50000, specs={})
    cand_fail = Candidate(product_key="p3", slot="mouse", name="미달", price=50000,
                          specs={"polling_hz_max": 500.0})
    weights = {"가격": 0.0, "선호적합": 1.0, "데이터충실": 0.0, "리뷰": 0.0}
    ranked = rank_candidates("mouse", req, [cand_pass, cand_pending, cand_fail], weights)
    by_key = {c.product_key: c for c in ranked}
    assert by_key["p1"].breakdown["선호적합"] == 1.0
    assert by_key["p2"].breakdown["선호적합"] == 0.5
    assert by_key["p3"].breakdown["선호적합"] == 0.0
    assert by_key["p1"].score > by_key["p2"].score > by_key["p3"].score
    assert [c.product_key for c in ranked] == ["p1", "p2", "p3"]


def test_rank_candidates_no_matching_soft_prefs_is_neutral():
    req = PeripheralRequirement(kind="speaker", hard={}, soft={})
    cand = Candidate(product_key="s1", slot="speaker", name="s1", price=10000)
    ranked = rank_candidates("speaker", req, [cand], {"가격": 0, "선호적합": 1, "데이터충실": 0, "리뷰": 0})
    assert ranked[0].breakdown["선호적합"] == 0.5


def test_rank_candidates_deterministic_tie_break_price_then_key():
    req = PeripheralRequirement(kind="speaker", hard={}, soft={})
    weights = {"가격": 0.0, "선호적합": 0.0, "데이터충실": 0.0, "리뷰": 0.0}   # 전 축 0 → 전부 동점
    cands = [
        Candidate(product_key="z", slot="speaker", name="z", price=20000),
        Candidate(product_key="a", slot="speaker", name="a", price=10000),
        Candidate(product_key="b", slot="speaker", name="b", price=10000),
    ]
    ranked = rank_candidates("speaker", req, cands, weights)
    assert [c.product_key for c in ranked] == ["a", "b", "z"]   # 가격 낮은 순 → product_key


def test_rank_candidates_pending_hard_verdict_gets_penalty():
    from src.config import PENDING_SCORE_PENALTY

    req = PeripheralRequirement(kind="monitor", hard={"resolution_class": ["QHD"]}, soft={})
    weights = {"가격": 0.0, "선호적합": 0.0, "데이터충실": 0.0, "리뷰": 0.0}
    passing = Candidate(product_key="m1", slot="monitor", name="m1", price=10000, verdict="Pass")
    pending = Candidate(product_key="m2", slot="monitor", name="m2", price=10000, verdict="Pending")
    ranked = rank_candidates("monitor", req, [passing, pending], weights)
    by_key = {c.product_key: c.score for c in ranked}
    assert round(by_key["m1"] - by_key["m2"], 6) == round(PENDING_SCORE_PENALTY, 6)


# ── 조합(choose) ──────────────────────────────────────────────────────────
def test_choose_without_budget_takes_top1_per_kind():
    ranked = {
        "monitor": [Candidate(product_key="m1", slot="monitor", name="m1", price=1, score=0.9),
                    Candidate(product_key="m2", slot="monitor", name="m2", price=1, score=0.5)],
        "mouse": [Candidate(product_key="s1", slot="mouse", name="s1", price=1, score=0.8)],
    }
    picks, counts = choose(ranked, budget_max=None)
    assert {k: c.product_key for k, c in picks.items()} == {"monitor": "m1", "mouse": "s1"}
    assert counts == {}


def test_choose_with_budget_stays_within_budget_when_feasible():
    rules = _rules()
    cands = _candidates()
    req_mon = build_requirements({"resolution": "QHD_165"}, ["monitor"], rules)["monitor"]
    req_mouse = build_requirements({"purpose": "game"}, ["mouse"], rules)["mouse"]
    kept_mon, _ = filter_candidates("monitor", req_mon, cands["monitor"])
    kept_mouse, _ = filter_candidates("mouse", req_mouse, cands["mouse"])
    ranked_mon = rank_candidates("monitor", req_mon, kept_mon, rules["ranking"]["monitor"]["weights"])
    ranked_mouse = rank_candidates("mouse", req_mouse, kept_mouse, rules["ranking"]["mouse"]["weights"])

    picks, counts = choose({"monitor": ranked_mon, "mouse": ranked_mouse}, budget_max=400000)
    total = sum(c.price for c in picks.values())
    assert total <= 400000
    assert "over_budget" not in counts


def test_choose_with_infeasible_budget_returns_cheapest_and_flags_over_budget():
    rules = _rules()
    cands = _candidates()
    req_mon = build_requirements({"resolution": "QHD_165"}, ["monitor"], rules)["monitor"]
    req_mouse = build_requirements({"purpose": "game"}, ["mouse"], rules)["mouse"]
    kept_mon, _ = filter_candidates("monitor", req_mon, cands["monitor"])
    kept_mouse, _ = filter_candidates("mouse", req_mouse, cands["mouse"])
    ranked_mon = rank_candidates("monitor", req_mon, kept_mon, rules["ranking"]["monitor"]["weights"])
    ranked_mouse = rank_candidates("mouse", req_mouse, kept_mouse, rules["ranking"]["mouse"]["weights"])

    picks, counts = choose({"monitor": ranked_mon, "mouse": ranked_mouse}, budget_max=1000)
    assert counts["over_budget"] == 1
    # 최저가 조합 — 각 종류에서 제일 싼 후보를 골랐는지 확인.
    cheapest_mon = min(ranked_mon, key=lambda c: c.price)
    cheapest_mouse = min(ranked_mouse, key=lambda c: c.price)
    assert picks["monitor"].product_key == cheapest_mon.product_key
    assert picks["mouse"].product_key == cheapest_mouse.product_key


def test_choose_reports_truncation_and_considered_count():
    ranked = [Candidate(product_key=f"m{i}", slot="mouse", name=f"m{i}", price=1000 * i, score=1.0 - i * 0.01)
              for i in range(1, 7)]  # 6개 — top_n(5) 초과
    picks, counts = choose({"mouse": ranked}, budget_max=1_000_000, top_n=5)
    assert counts["truncated"] == 1
    assert counts["considered"] == 5
    assert picks["mouse"].product_key == "m1"   # top-5 안에서는 여전히 1위가 최선


# ── run_peripherals 진입점 ────────────────────────────────────────────────
def test_run_peripherals_skipped_when_no_condition():
    result = run_peripherals({}, _candidates(), _NOLOG)
    assert result.status == "skipped"
    assert result.picks == []


def test_run_peripherals_empty_status_when_all_requested_kinds_empty():
    result = run_peripherals({"peripherals": ["monitor"], "resolution": "FHD_144"}, _candidates(), _NOLOG)
    assert result.status == "empty"
    assert result.empty == [{"kind": "monitor", "reason": "FHD·144Hz 이상 조건에 맞는 모니터가 카탈로그에 없습니다"}]


def test_run_peripherals_ready_fills_picks_and_verification():
    values = {"peripherals": ["monitor", "mouse"], "resolution": "QHD_165", "purpose": "game"}
    result = run_peripherals(values, _candidates(), _NOLOG)
    assert result.status == "ready"
    assert {p.kind for p in result.picks} == {"monitor", "mouse"}
    assert result.verification is not None
    assert result.verification.mode == "per_item"
    assert len(result.verification.targets) == 2
    for pick in result.picks:
        assert len(pick.alternatives) <= 2
        assert all(alt.product_key != pick.candidate.product_key for alt in pick.alternatives)


def test_run_peripherals_unknown_kind_raises():
    with pytest.raises(ValueError):
        run_peripherals({"peripherals": ["speaker_amp"]}, _candidates(), _NOLOG)


# ── [3-C] verify_per_item ─────────────────────────────────────────────────
def test_verify_per_item_pending_hard_axis_penalty():
    req = PeripheralRequirement(kind="monitor", hard={"resolution_class": ["QHD"], "refresh_min_hz": 165}, soft={})
    cand = Candidate(product_key="m1", slot="monitor", name="m1", price=100, verdict="Pending",
                     reasons=["refresh_hz: 값 없음"])
    pick = PeripheralPick(kind="monitor", candidate=cand, score=0.5, verdict="Pending")
    result = verify_per_item({"monitor": pick}, {"monitor": req}, _NOLOG)
    target = result.targets[0]
    assert len(target.issues) == 1
    assert target.issues[0].penalty == 6
    assert target.confidence == 94
    assert target.passed is (94 >= CONFIDENCE_THRESHOLD)


def test_verify_per_item_data_gap_issue_bundles_all_missing_keys():
    req = PeripheralRequirement(
        kind="mouse", hard={},
        soft={"preferences": [{"key": "polling_hz_max", "op": "min", "value": 1000},
                              {"key": "dpi_max", "op": "min", "value": 8000}]},
    )
    cand = Candidate(product_key="s1", slot="mouse", name="s1", price=100, specs={})   # 둘 다 결손
    pick = PeripheralPick(kind="mouse", candidate=cand)
    result = verify_per_item({"mouse": pick}, {"mouse": req}, _NOLOG)
    target = result.targets[0]
    assert len(target.issues) == 1          # 여러 결손 키가 있어도 쟁점은 한 건으로 묶는다
    assert target.issues[0].penalty == 6
    assert "polling_hz_max" in target.issues[0].tool_result
    assert "dpi_max" in target.issues[0].tool_result
    assert target.confidence == 94


def test_verify_per_item_no_issues_when_fully_known():
    req = PeripheralRequirement(kind="speaker", hard={}, soft={"preferences": [{"key": "channels", "op": "min", "value": 2}]})
    cand = Candidate(product_key="sp1", slot="speaker", name="sp1", price=100, specs={"channels": 2.1}, verdict="Pass")
    pick = PeripheralPick(kind="speaker", candidate=cand)
    result = verify_per_item({"speaker": pick}, {"speaker": req}, _NOLOG)
    target = result.targets[0]
    assert target.issues == []
    assert target.confidence == 100
    assert target.passed is True


def test_verify_per_item_extra_issues_extension_point_for_e12():
    req = PeripheralRequirement(kind="monitor", hard={}, soft={})
    cand = Candidate(product_key="m1", slot="monitor", name="m1", price=100)
    pick = PeripheralPick(kind="monitor", candidate=cand)
    extra = Issue(axis="monitor_gpu_port", text="교차 검사 쟁점", judge="확인 필요", penalty=10)
    result = verify_per_item({"monitor": pick}, {"monitor": req}, _NOLOG, extra_issues={"monitor": [extra]})
    target = result.targets[0]
    assert len(target.issues) == 1
    assert target.confidence == 90


# ── pipeline: 불변 + 확장 ─────────────────────────────────────────────────
def test_pipeline_computer_pass_unaffected_without_peripherals_condition():
    from src.pipeline import run_pipeline

    result = run_pipeline("computer_pass", on_log=_NOLOG, catalog_source="mock")
    assert result.peripherals is None
    assert result.build is not None and len(result.build.items) == 8
    assert result.verification.targets[0].passed is True


def test_pipeline_runs_peripherals_when_condition_present(monkeypatch):
    import copy

    import src.pipeline as pipeline_module

    original = pipeline_module.load_scenario("computer_pass")
    scenario = copy.deepcopy(original)
    scenario["mock_slot_fill"]["confirmed"]["peripherals"] = ["monitor", "mouse"]

    def fake_load_scenario(name: str) -> dict:
        return scenario if name == "computer_pass" else original

    def fake_catalog(log, *, catalog_source=None):
        return load_peripheral_candidates_from_csv(_FIXTURES)

    monkeypatch.setattr(pipeline_module, "load_scenario", fake_load_scenario)
    monkeypatch.setattr(pipeline_module, "_load_peripheral_catalog", fake_catalog)

    result = pipeline_module.run_pipeline("computer_pass", on_log=_NOLOG, catalog_source="mock")

    assert result.peripherals is not None
    assert result.peripherals.status == "ready"
    assert {p.kind for p in result.peripherals.picks} == {"monitor", "mouse"}
    # 주변기기 단계가 붙어도 컴퓨터 세트 계산 자체는 그대로다(기존 결과 불변 원칙).
    assert result.build is not None and len(result.build.items) == 8


# ── load_peripheral_candidates_from_csv: filename_template / 빈 디렉터리 ──────
def test_load_from_csv_with_filename_template_matches_data_dir_naming(tmp_path):
    """실제 data/peripherals는 `{kind}_processed.csv` 이름을 쓴다(db/seed_peripherals.py와
    동일 규칙) — pipeline._load_peripheral_catalog가 이 인자로 그 이름 규칙을 그대로 읽는다."""
    import shutil

    shutil.copyfile(_FIXTURES / "monitor.csv", tmp_path / "monitor_processed.csv")
    result = load_peripheral_candidates_from_csv(tmp_path, filename_template="{kind}_processed.csv")
    assert len(result.get("monitor", [])) == 6
    assert result.get("mouse", []) == []   # mouse_processed.csv 가 없으니 그 종류는 아예 없음


def test_load_from_csv_missing_directory_returns_empty_without_raising():
    """data/peripherals 자체가 없는 환경(수집 파일 미배포)에서도 예외 없이 빈 결과를 낸다."""
    result = load_peripheral_candidates_from_csv(Path("/nonexistent/does-not-exist-xyz"))
    assert result == {}


def test_pipeline_load_peripheral_catalog_handles_missing_data_dir(monkeypatch):
    """`_load_peripheral_catalog`가 CATALOG_SOURCE=mock에서 data/peripherals가 없어도
    죽지 않고 빈 dict를 내며, run_peripherals는 그 결과를 요청 종류 전부 empty로 처리한다."""
    import src.pipeline as pipeline_module

    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    monkeypatch.setattr(pipeline_module, "DATA_DIR", Path("/nonexistent/does-not-exist-xyz"))

    candidates = pipeline_module._load_peripheral_catalog(_NOLOG)
    assert candidates == {}

    result = run_peripherals({"peripherals": ["monitor"]}, candidates, _NOLOG)
    assert result.status == "empty"
    assert result.empty == [{"kind": "monitor", "reason": "모니터 후보 자체가 카탈로그에 없습니다"}]
