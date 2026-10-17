"""교체 대상 추천 — 어느 부품을 먼저 바꿀지와 후보 규칙(성능이 같거나 높고, 새 비호환이 없고, 이유를 풀고, 교체 예산 안)."""
from __future__ import annotations

import pytest

from src.engine.stage3_0_candidates import load_pc_catalog
from src.services import quote_replacement_plan as rp


@pytest.fixture()
def by_slot(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    return load_pc_catalog(lambda _msg: None)


BASE = {"CPU": "Intel Core i5-14600K", "GPU": "NVIDIA GeForce RTX 4060", "RAM": "Samsung DDR5-5600 32GB (2x16)",
        "메인보드": "ASUS PRIME B760M-A WIFI", "저장장치": "Samsung 990 PRO 1TB", "파워": "Corsair RM650e",
        "케이스": "NZXT H5 Flow", "쿨러": "Noctua NH-D15"}


def _review(specs=None, **conditions):
    return {"input": {"current_specs": {**BASE, **(specs or {})}, "conditions": conditions}}


def _by_slot(out):
    return {t["slot"]: t for t in out["targets"]}


def _tier(by_slot, slot, name):
    return next(c.specs.get("perf_tier") for c in by_slot[slot] if c.name == name)


def test_a_part_that_misses_the_purpose_is_a_replace_target_with_candidates_that_fix_it(by_slot):
    out = rp.build_targets(_review(purpose="game", resolution="4K"), by_slot)
    targets = _by_slot(out)
    gpu = targets["GPU"]
    assert gpu["kind"] == "replace" and gpu["rank"] == 1 and gpu["priority"] == 3
    assert {r["code"] for r in gpu["reasons"]} == {"balance_short"} and gpu["candidates"]
    assert out["counts"]["replace"] >= 1 and targets["케이스"]["kind"] == "keep" and targets["케이스"]["rank"] is None
    assert [t["kind"] for t in out["targets"]] == sorted((t["kind"] for t in out["targets"]), key=["replace", "verify", "keep"].index)


def test_candidates_are_never_lower_than_the_current_part_and_never_the_same_product(by_slot):
    out = rp.build_targets(_review(purpose="game", resolution="4K"), by_slot, limit=10)
    for slot in ("GPU", "RAM"):
        target = _by_slot(out)[slot]
        current = next(c for c in by_slot[slot] if c.name == target["current_name"])
        for cand in target["candidates"]:
            assert cand["name"] != current.name
            if slot == "GPU":
                assert cand["perf_tier"] >= _tier(by_slot, "GPU", current.name)
            else:
                assert next(c for c in by_slot[slot] if c.name == cand["name"]).specs["capacity_gb"] >= current.specs["capacity_gb"]


def _cand(slot, name, price, **specs):
    from src.dto import Candidate
    return Candidate(product_key=name.lower().replace(" ", "-"), slot=slot, name=name, specs=specs, price=price)


def test_an_incompatible_pair_flags_both_parts_and_candidates_fix_the_socket_without_new_problems():
    """모의 카탈로그는 보드 소켓 값이 비어 있어 소켓 검사를 못 하므로, 소켓이 있는 작은 카탈로그로 확인한다."""
    pool = {
        "CPU": [_cand("CPU", "AMD Ryzen 7 7700", 300_000, socket="AM5", perf_tier=7), _cand("CPU", "Intel Core i5-14600K", 237_000, socket="LGA1700", perf_tier=7),
                _cand("CPU", "Intel Core i7-14700K", 255_000, socket="LGA1700", perf_tier=8), _cand("CPU", "Intel Core i3-14100", 150_000, socket="LGA1700", perf_tier=4),
                _cand("CPU", "AMD Ryzen 5 7600", 240_000, socket="AM5", perf_tier=6)],
        "메인보드": [_cand("메인보드", "ASUS PRIME B760M-A WIFI", 204_000, socket="LGA1700"), _cand("메인보드", "ASUS TUF GAMING B650-PLUS WIFI", 155_000, socket="AM5"),
                  _cand("메인보드", "MSI MAG B850 TOMAHAWK WIFI", 173_000, socket="AM5"), _cand("메인보드", "MSI MAG B760 TOMAHAWK WIFI", 182_000, socket="LGA1700")],
    }
    review = {"input": {"current_specs": {"CPU": "AMD Ryzen 7 7700", "메인보드": "ASUS PRIME B760M-A WIFI"}, "conditions": {"purpose": "office"}}}
    out = rp.build_targets(review, pool)
    targets = _by_slot(out)
    for slot in ("CPU", "메인보드"):
        assert targets[slot]["kind"] == "replace" and targets[slot]["priority"] == 1
        assert any(r["code"] == "incompatible" for r in targets[slot]["reasons"])
    assert {t["slot"] for t in out["targets"][:2]} == {"CPU", "메인보드"}               # 비호환이 가장 먼저
    cpu = [c["name"] for c in targets["CPU"]["candidates"]]
    assert cpu == ["Intel Core i5-14600K", "Intel Core i7-14700K"]                       # 보드 소켓에 맞고, 현재(7)보다 낮은 14100 은 빠지고, 싼 것부터
    board = [c["name"] for c in targets["메인보드"]["candidates"]]
    assert board == ["ASUS TUF GAMING B650-PLUS WIFI", "MSI MAG B850 TOMAHAWK WIFI"] and all(c["resolves_all"] for c in targets["CPU"]["candidates"])


def test_a_part_not_in_the_catalog_is_verify_first_and_gets_no_candidates(by_slot):
    out = rp.build_targets(_review({"케이스": "1stPlayer Mi5 WING"}, purpose="office"), by_slot)
    case = _by_slot(out)["케이스"]
    assert case["kind"] == "verify" and case["candidates"] == [] and case["current_confirmed"] is False
    assert any(r["code"] == "unknown_info" for r in case["reasons"])


def test_the_replace_budget_limits_the_candidates_by_how_much_they_add(by_slot):
    review = _review(purpose="game", resolution="4K", replace_budget=1)
    gpu = _by_slot(rp.build_targets(review, by_slot))["GPU"]
    assert all(c["price_delta"] is None or c["price_delta"] <= 1 for c in gpu["candidates"])
    review = _review(purpose="game", resolution="4K", replace_budget=1)
    tiny = _by_slot(rp.build_targets({**review, "input": {**review["input"], "conditions": {**review["input"]["conditions"], "replace_budget": -10**9}}}, by_slot))["GPU"]
    assert tiny["candidates"] == [] and "교체 예산 안에서는 없어요" in tiny["note"]


def test_a_part_that_looks_fine_has_no_replace_reason(by_slot):
    out = rp.build_targets(_review(purpose="office"), by_slot)
    assert all(t["kind"] != "replace" for t in out["targets"]) and out["counts"]["replace"] == 0


def test_the_effect_of_a_replacement_is_computed_with_before_and_after_and_flags_a_lower_part(by_slot):
    review = _review(purpose="game", resolution="4K")
    cheaper = next(c for c in by_slot["GPU"] if c.name == "AMD Radeon RX 7800 XT")             # 등급이 현재(8)보다 낮다
    state = rp.build_state(review, {"GPU": cheaper}, by_slot)
    item = state["replacements"][0]
    assert item["slot"] == "GPU" and item["candidate"]["name"] == "AMD Radeon RX 7800 XT" and "grade_lower" in item["warnings"]
    assert set(state["compat"]) == {"before", "after", "new_issues", "resolved_issues"} and state["balance"]["available"] is True
    assert state["price"]["delta_total"] == cheaper.price - next(c for c in by_slot["GPU"] if c.name == "NVIDIA GeForce RTX 4060").price


def test_a_replacement_over_the_replace_budget_is_warned_and_an_empty_list_changes_nothing(by_slot):
    review = _review(purpose="game", resolution="4K", replace_budget=1)
    pricey = next(c for c in by_slot["GPU"] if c.name == "NVIDIA GeForce RTX 4070 Ti SUPER")
    state = rp.build_state(review, {"GPU": pricey}, by_slot)
    assert state["price"]["over_budget"] is True and "over_budget" in state["replacements"][0]["warnings"]
    empty = rp.build_state(review, {}, by_slot)
    assert empty["replacements"] == [] and empty["compat"]["before"] == empty["compat"]["after"] and empty["price"]["delta_total"] == 0
