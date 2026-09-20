"""PC stage 4 searches the received top-N pools, rather than picking slotwise."""
from itertools import product

from src.dto import Candidate, RankResult, RequirementSpec
from src.engine.stage4_optimize import _pc_known_failures, build_computer
from src.engine.stage2_requirement import load_computer_rules


def candidate(slot, key, price, score, **specs):
    return Candidate(slot=slot, product_key=key, name=key, price=price,
                     score=score, specs=specs)


def run(pools, budget, exclude=None):
    rank = RankResult(slots={slot: {"ranked": [c.model_dump() for c in options]}
                             for slot, options in pools.items()})
    spec = RequirementSpec(list_id="search", category="computer", mode="build",
                           targets={slot: {} for slot in pools}, budget={"total": budget})
    return build_computer(rank, spec, lambda _: None, exclude=exclude), spec


def test_budget_search_beats_slotwise_greedy():
    pools = {
        "CPU": [candidate("CPU", "expensive_cpu", 90, 10),
                candidate("CPU", "value_cpu", 30, 9)],
        "GPU": [candidate("GPU", "strong_gpu", 70, 100),
                candidate("GPU", "weak_gpu", 10, 1)],
    }
    result, _ = run(pools, 100)
    assert [item.product_key for item in result.items] == ["value_cpu", "strong_gpu"]
    assert result.totals["price"] == 100
    assert result.alternatives["considered"] == 4
    assert result.alternatives["valid"] > 0
    assert result.alternatives["feasible"] == 1


def test_search_obeys_cross_slot_compatibility_and_exclusion():
    pools = {
        "CPU": [candidate("CPU", "am5", 50, 9, socket="AM5"),
                candidate("CPU", "lga", 50, 8, socket="LGA1700")],
        "메인보드": [candidate("메인보드", "lga_board", 30, 10, socket="LGA1700"),
                      candidate("메인보드", "am5_board", 30, 2, socket="AM5")],
    }
    result, _ = run(pools, 100)
    assert {item.product_key for item in result.items} == {"lga", "lga_board"}
    assert "fail" not in result.link_check.values()
    excluded, _ = run(pools, 100, {("CPU", "lga")})
    assert {item.product_key for item in excluded.items} == {"am5", "am5_board"}


def test_no_feasible_build_is_marked_and_exclusion_does_not_restore_pool():
    pools = {"CPU": [candidate("CPU", "only", 120, 10)]}
    over, _ = run(pools, 100)
    assert over.link_check["budget"] == "fail"
    assert over.alternatives["feasible"] == 0
    excluded, _ = run(pools, 100, {("CPU", "only")})
    assert excluded.items == []
    assert excluded.link_check["set"] == "fail"
    assert excluded.alternatives["considered"] == 0


def test_small_pool_matches_brute_force_oracle():
    pools = {
        "CPU": [candidate("CPU", "c1", 40, 7, socket="AM5"),
                candidate("CPU", "c2", 30, 6, socket="LGA1700")],
        "메인보드": [candidate("메인보드", "b1", 30, 5, socket="AM5"),
                      candidate("메인보드", "b2", 25, 4, socket="LGA1700")],
        "GPU": [candidate("GPU", "g1", 50, 9), candidate("GPU", "g2", 35, 6)],
    }
    result, spec = run(pools, 110)
    slots = list(pools)
    rules = load_computer_rules()["verification"]
    feasible = []
    for combo in product(*(pools[s] for s in slots)):
        chosen = dict(zip(slots, combo))
        price = sum(c.price for c in combo)
        if price <= 110 and not _pc_known_failures(chosen, spec, rules):
            feasible.append((-sum(c.score for c in combo), price,
                             tuple(c.product_key for c in combo)))
    expected = min(feasible)
    assert tuple(i.product_key for i in result.items) == expected[2]
    assert result.totals["price"] == expected[1]


def test_selected_candidate_keeps_catalog_identity_for_persistence():
    source = Candidate(
        slot="CPU", product_key="cpu:test:model", name="Test Model", price=100,
        variant_id="00000000-0000-0000-0000-000000000001",
        offer_observation_id="00000000-0000-0000-0000-000000000002",
    )
    result, _ = run({"CPU": [source]}, 200)
    assert result.items[0].variant_id == source.variant_id
    assert result.items[0].offer_observation_id == source.offer_observation_id
