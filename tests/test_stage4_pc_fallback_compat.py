"""[4] PC 세트 탐색의 폴백은 예산은 풀어도 호환은 풀지 않는다.

회귀 배경: stage3b가 슬롯당 상위 3~5개로 후보를 자른 뒤 [4]가 그 안에서만 탐색했다.
잘라내는 시점엔 교차 슬롯 호환(CPU 소켓 ↔ 쿨러 지원 소켓)을 모르기 때문에, 상위 쿨러가
전부 LGA1851 미지원이면 호환 조합이 통째로 사라졌다. 실제 카탈로그(개발 DB)에서 인텔 선호
시나리오 5개가 예산과 무관하게 소켓이 안 맞는 쿨러를 골랐다(40개 중 10개는 지원하는데도).
[4]는 top-N에서 못 찾으면 stage3b가 넘기는 전체 풀("pool")로 넓혀 다시 찾는다."""
from __future__ import annotations

from src.dto import Candidate, HardFilterResult, RankResult, RequirementSpec, Slots
from src.engine import stage3b_rank
from src.engine.stage4_optimize import build_computer


def cand(slot, key, price, score, **specs) -> Candidate:
    return Candidate(slot=slot, product_key=key, name=key, price=price, score=score, specs=specs)


def run(ranked, pool=None, budget=1000, exclude=None):
    """ranked: 슬롯 -> top-N 후보, pool: 슬롯 -> 전체 후보(없으면 legacy RankResult)."""
    slots = {}
    for slot, options in ranked.items():
        info = {"ranked": [c.model_dump() for c in options]}
        if pool is not None:
            info["pool"] = [c.model_dump() for c in pool.get(slot, options)]
        slots[slot] = info
    spec = RequirementSpec(list_id="fb", category="computer", mode="build",
                           targets={slot: {} for slot in ranked}, budget={"total": budget})
    return build_computer(RankResult(slots=slots), spec, lambda _: None, exclude=exclude)


def keys(result):
    return {item.slot: item.product_key for item in result.items}


CPU = cand("CPU", "cpu_lga", 100, 9, socket="LGA1851")
COOLER_AM_ONLY = cand("쿨러", "cooler_am_only", 30, 9, supported_socket="AM5/AM4")
COOLER_LGA = cand("쿨러", "cooler_lga", 40, 5, supported_socket="LGA1851/1700, AM5/AM4")
COOLER_LGA_BEST = cand("쿨러", "cooler_lga_best", 60, 8, supported_socket="LGA1851/1700")


# ── stage3b: 자르기 전 전체 풀을 함께 넘긴다 ─────────────────────────────────

def test_stage3b_exposes_the_full_pool_beside_the_top_n():
    cands = [cand("쿨러", f"c{i}", 10 + i, 0.0) for i in range(8)]
    spec = RequirementSpec(list_id="r", category="computer", mode="build",
                           targets={"쿨러": {}}, budget={"total": 0})
    slots = Slots(category="computer", mode="build", objective_text="", values={"purpose": "game"},
                  assumed_keys=[], missing=[])
    rank = stage3b_rank.run(HardFilterResult(slots={"쿨러": cands}), spec, slots, lambda _: None)
    info = rank.slots["쿨러"]
    assert len(info["ranked"]) == 3                       # top-N 계약은 그대로
    assert len(info["pool"]) == 8                         # 잘리기 전 전체
    assert [c["product_key"] for c in info["pool"][:3]] == [c["product_key"] for c in info["ranked"]]
    assert [c["rank"] for c in info["pool"]] == list(range(1, 9))


# ── stage4: top-N 안에 호환 조합이 없으면 전체 풀로 넓힌다 ────────────────────

def test_widens_to_full_pool_when_every_top_n_cooler_is_incompatible():
    result = run({"CPU": [CPU], "쿨러": [COOLER_AM_ONLY]},
                 pool={"쿨러": [COOLER_AM_ONLY, COOLER_LGA]})
    assert keys(result)["쿨러"] == "cooler_lga"
    assert result.link_check.get("cooler_socket") != "fail"
    assert "set" not in result.link_check and "budget" not in result.link_check
    assert result.alternatives["widened"] == 1 and result.alternatives["feasible"] == 1


def test_widened_search_still_maximises_score_within_budget():
    result = run({"CPU": [CPU], "쿨러": [COOLER_AM_ONLY]},
                 pool={"쿨러": [COOLER_AM_ONLY, COOLER_LGA, COOLER_LGA_BEST]}, budget=200)
    assert keys(result)["쿨러"] == "cooler_lga_best"      # 둘 다 예산 안이면 점수 높은 쪽


def test_budget_shortage_relaxes_the_budget_not_compatibility():
    # 예산(150)으로는 어떤 호환 조합도 못 만든다 → 호환되는 가장 싼 조합 + 예산 fail 표시.
    board_top = cand("메인보드", "board_top", 300, 9, socket="LGA1851")
    board_cheap = cand("메인보드", "board_cheap", 80, 3, socket="LGA1851")
    board_wrong = cand("메인보드", "board_wrong_socket", 10, 1, socket="AM5")
    result = run({"CPU": [CPU], "메인보드": [board_top]},
                 pool={"메인보드": [board_top, board_cheap, board_wrong]}, budget=150)
    assert keys(result)["메인보드"] == "board_cheap"      # 더 싼 board_wrong_socket 은 비호환이라 제외
    assert result.totals["price"] == 180
    assert result.link_check["budget"] == "fail"
    assert result.link_check["socket"] != "fail" and "set" not in result.link_check
    assert result.alternatives["feasible"] == 0 and result.alternatives["compatible"] == 1


def test_no_compatible_set_anywhere_is_still_marked_failed():
    only_am = cand("쿨러", "am_only", 30, 9, supported_socket="AM5")
    result = run({"CPU": [CPU], "쿨러": [only_am]}, pool={"쿨러": [only_am, only_am.model_copy(
        update={"product_key": "am_only_2"})]})
    assert result.link_check["set"] == "fail"
    assert result.link_check["cooler_socket"] == "fail"
    assert result.alternatives["compatible"] == 0


def test_rank_without_pool_behaves_as_before():
    result = run({"CPU": [CPU], "쿨러": [COOLER_AM_ONLY]})   # legacy: "pool" 키 없음
    assert "widened" not in result.alternatives
    assert result.link_check["set"] == "fail"


def test_widening_respects_exclusions():
    result = run({"CPU": [CPU], "쿨러": [COOLER_AM_ONLY]},
                 pool={"쿨러": [COOLER_AM_ONLY, COOLER_LGA]}, exclude={("쿨러", "cooler_lga")})
    assert keys(result)["쿨러"] == "cooler_am_only"       # 제외된 호환 쿨러는 넓혀도 되살아나지 않는다
    assert result.link_check["set"] == "fail"


def test_top_n_solution_is_untouched_when_it_already_exists():
    # 기존 경로가 해를 찾으면 넓히지 않는다 — 결과·탐색 통계가 이전과 같아야 한다.
    result = run({"CPU": [CPU], "쿨러": [COOLER_LGA]}, pool={"쿨러": [COOLER_LGA, COOLER_LGA_BEST]})
    assert keys(result)["쿨러"] == "cooler_lga"
    assert "widened" not in result.alternatives
