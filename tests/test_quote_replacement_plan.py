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


def test_an_empty_replacement_list_changes_nothing_and_the_price_shows_only_the_difference(by_slot):
    review = _review(purpose="game", resolution="4K")
    pricey = next(c for c in by_slot["GPU"] if c.name == "NVIDIA GeForce RTX 4070 Ti SUPER")
    state = rp.build_state(review, {"GPU": pricey}, by_slot)
    assert set(state["price"]) == {"delta_total", "unpriced_slots"}                  # 교체 예산을 뺐다 — 초과 판정·경고 없음
    assert all("over_budget" not in row["warnings"] for row in state["replacements"])
    empty = rp.build_state(review, {}, by_slot)
    assert empty["replacements"] == [] and empty["compat"]["before"] == empty["compat"]["after"] and empty["price"]["delta_total"] == 0


# ── 결정 ③④⑥⑪ ────────────────────────────────────────────────────────────────
def _socket_pool(current_tier=7):
    return {
        "CPU": [_cand("CPU", "Intel Core i5-14600K", 237_000, socket="LGA1700", perf_tier=current_tier),
                _cand("CPU", "AMD Ryzen 7 7700", 300_000, socket="AM5", perf_tier=7), _cand("CPU", "AMD Ryzen 5 7600", 240_000, socket="AM5", perf_tier=6),
                _cand("CPU", "AMD Ryzen 5 7500F", 190_000, socket="AM5", perf_tier=5)],
        "메인보드": [_cand("메인보드", "ASUS TUF GAMING B650-PLUS WIFI", 155_000, socket="AM5")],
    }


def _socket_review(**conditions):
    return {"input": {"current_specs": {"CPU": "Intel Core i5-14600K", "메인보드": "ASUS TUF GAMING B650-PLUS WIFI"}, "conditions": conditions}}


def test_a_slightly_lower_cpu_is_offered_only_when_value_comes_first_and_within_one_grade():
    plain = _by_slot(rp.build_targets(_socket_review(purpose="office"), _socket_pool()))["CPU"]
    assert [c["name"] for c in plain["candidates"]] == ["AMD Ryzen 7 7700"]
    value = _by_slot(rp.build_targets(_socket_review(purpose="office", priority="value"), _socket_pool()))["CPU"]
    names = {c["name"]: c for c in value["candidates"]}
    assert set(names) == {"AMD Ryzen 7 7700", "AMD Ryzen 5 7600"}                       # 등급 1 낮은 7600 은 허용, 2 낮은 7500F 는 아니다
    assert names["AMD Ryzen 5 7600"]["cautions"] == ["성능이 낮아요"] and names["AMD Ryzen 7 7700"]["cautions"] == []


def test_a_lower_ram_or_storage_is_never_offered_even_when_value_comes_first(by_slot):
    out = rp.build_targets(_review(purpose="game", resolution="4K", priority="value"), by_slot)
    for slot in ("RAM", "저장장치"):
        for cand in _by_slot(out)[slot]["candidates"]:
            assert "성능이 낮아요" not in cand["cautions"]


def test_candidates_are_shown_with_a_notice_when_the_current_grade_is_unknown():
    pool = _socket_pool()
    pool["CPU"][0] = _cand("CPU", "Intel Core i5-14600K", 237_000, socket="LGA1700")             # 현재 부품의 성능 등급을 모른다
    target = _by_slot(rp.build_targets(_socket_review(purpose="office"), pool))["CPU"]
    assert target["candidates"], target                                                          # 숨기지 않는다
    assert all("성능을 몰라 비교하지 못했어요" in c["cautions"][0] for c in target["candidates"])
    assert "성능 등급을 확인하지 못해" in (target["note"] or "")


def test_partial_candidates_come_after_full_ones_instead_of_being_hidden(by_slot):
    out = rp.build_targets(_review(purpose="game", resolution="4K", games=["사이버펑크 2077"]), by_slot, limit=10)
    flags = [c["resolves_all"] for t in out["targets"] for c in t["candidates"] if t["slot"] == "GPU"]
    assert flags == sorted(flags, reverse=True)


def test_savings_candidates_appear_only_for_value_priority_and_an_excess_part(by_slot):
    base = {"GPU": "NVIDIA GeForce RTX 5090"}
    off = rp.build_targets(_review(base, purpose="office"), by_slot)
    assert all(t["savings"] == [] for t in off["targets"])                                      # 가성비가 아니면 나타나지 않는다
    on = rp.build_targets(_review(base, purpose="office", priority="value"), by_slot)
    gpu = _by_slot(on)["GPU"]
    assert gpu["kind"] == "keep" and any(r["code"] == "excess" for r in gpu["reasons"]), gpu["reasons"]
    assert gpu["savings"], gpu
    current_price = next(c.price for c in by_slot["GPU"] if c.name == "NVIDIA GeForce RTX 5090")
    assert all(s["price_delta"] < 0 and s["price"] < current_price for s in gpu["savings"])
    assert [s["price_delta"] for s in gpu["savings"]] == sorted(s["price_delta"] for s in gpu["savings"])      # 가장 많이 아끼는 순
    assert len(gpu["savings"]) <= 3


def test_the_price_reference_uses_the_total_budget_share_only_when_a_total_budget_is_given():
    assert rp._reference_budget({}, "GPU", 500_000, [400_000, 600_000]) == 500_000                     # 현재 부품 가격
    assert rp._reference_budget({}, "GPU", None, [400_000, 600_000]) == 500_000                         # 모르면 후보 가격 중앙값
    with_total = rp._reference_budget({"budget_max": 3_100_000, "purpose": "game"}, "GPU", 500_000, [])
    assert with_total != 500_000 and 0 < with_total < 3_100_000                                          # 총예산 × 부품별 배분
    assert rp._reference_budget({"budget_max": 3_100_000}, "GPU", 500_000, []) > 0                       # 용도가 없어도 기본 배분


def test_the_same_product_listed_twice_in_the_catalog_is_shown_once():
    rows = [{"name": "NVIDIA GeForce RTX 3050 (6GB)", "price": 308_800}, {"name": "NVIDIA GeForce RTX 3050 6GB", "price": 308_800},
            {"name": "NVIDIA GeForce RTX 3050 6GB", "price": 320_000}]
    assert [r["price"] for r in rp._dedupe(rows)] == [308_800, 320_000]                # 이름만 같고 가격이 다르면 다른 판매 항목이라 둘 다 보인다
