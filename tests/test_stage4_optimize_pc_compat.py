"""[4] 세트 최적화의 PC 호환성 픽 로직.

회귀 배경: _apply_mainboard_compat가 예전엔 "랭킹 1위 메인보드"를 기준으로 CPU
풀을 미리 필터링했는데, 정작 예산 때문에 최종 픽은 다른 보드가 나올 수 있어서
소켓이 안 맞는 조합이 그대로 통과되는 버그가 있었다(실제로 CATALOG_SOURCE=db로
재현: CPU가 top-5 전부 LGA1700인데 메인보드 랭킹 1위가 AM4라서 소켓 불일치가
그냥 넘어갔다). _pick_mainboard/_pick_with_limit/_pick_cooler는 "실제로 뽑힐"
후보를 기준으로 확정 비호환을 피한다.
"""
from __future__ import annotations

from src.dto import Candidate, RequirementSpec
from src.engine.stage4_optimize import (
    _is_definite_mismatch, _pick_cooler, _pick_mainboard, _pick_with_limit, build_computer,
)


def _cand(key, price, **specs) -> Candidate:
    return Candidate(product_key=key, slot="s", name=key, brand="b", price=price, specs=specs)


# ── _is_definite_mismatch ───────────────────────────────────────────────────

def test_definite_mismatch_true_when_every_known_socket_differs():
    pool = [_cand("c1", 1, socket="LGA1700"), _cand("c2", 1, socket="LGA1851")]
    assert _is_definite_mismatch(pool, "socket", "AM5") is True


def test_definite_mismatch_false_when_at_least_one_matches():
    pool = [_cand("c1", 1, socket="LGA1700"), _cand("c2", 1, socket="AM5")]
    assert _is_definite_mismatch(pool, "socket", "AM5") is False


def test_definite_mismatch_false_when_no_candidate_has_the_key_at_all():
    # 정보가 아예 없으면 "확정 비호환"이 아니라 판단 보류 — Fail로 단정하지 않는다.
    pool = [_cand("c1", 1), _cand("c2", 1)]
    assert _is_definite_mismatch(pool, "socket", "AM5") is False


# ── _pick_mainboard (원래 버그의 핵심 회귀 테스트) ───────────────────────────

def test_pick_mainboard_skips_a_cheaper_board_with_no_compatible_cpu_in_pool():
    cpu_pool = [_cand("i5", 200_000, socket="LGA1700"), _cand("r5", 220_000, socket="AM5")]
    pools = {
        "CPU": cpu_pool,
        "메인보드": [
            _cand("am4_board", 50_000, socket="AM4"),       # 랭킹/가격 1위지만 CPU 풀에 AM4가 없음
            _cand("lga1700_board", 90_000, socket="LGA1700"),  # CPU 풀과 실제로 맞는 보드
        ],
    }
    picked = _pick_mainboard(pools, budget=0, running=0)
    assert picked.product_key == "lga1700_board"


def test_pick_mainboard_falls_back_to_budget_fit_when_nothing_matches():
    cpu_pool = [_cand("i5", 200_000, socket="LGA1700")]
    pools = {"CPU": cpu_pool, "메인보드": [_cand("am4_board", 50_000, socket="AM4")]}
    picked = _pick_mainboard(pools, budget=0, running=0)
    assert picked.product_key == "am4_board"  # 맞는 보드가 없으니 빈 슬롯보다는 이거


def test_pick_mainboard_respects_budget_before_compatibility():
    cpu_pool = [_cand("i5", 200_000, socket="LGA1700")]
    pools = {
        "CPU": cpu_pool,
        "메인보드": [_cand("cheap_am4", 30_000, socket="AM4"),
                    _cand("lga1700_over_budget", 999_000, socket="LGA1700")],
    }
    # 예산이 taight해서 비싼 호환 보드는 애초에 후보에서 배제돼야 한다.
    picked = _pick_mainboard(pools, budget=100_000, running=0)
    assert picked.product_key == "cheap_am4"


# ── _pick_with_limit (GPU 길이 / PSU 용량 공용) ─────────────────────────────

def test_pick_with_limit_skips_gpu_too_long_for_the_case():
    pool = [_cand("long_gpu", 500_000, length_mm=450), _cand("short_gpu", 520_000, length_mm=300)]
    picked = _pick_with_limit(pool, budget=0, running=0, key="length_mm", limit=350, max_allowed=True)
    assert picked.product_key == "short_gpu"


def test_pick_with_limit_skips_psu_under_the_required_wattage():
    pool = [_cand("weak_psu", 60_000, wattage_w=450), _cand("strong_psu", 90_000, wattage_w=750)]
    picked = _pick_with_limit(pool, budget=0, running=0, key="wattage_w", limit=600, max_allowed=False)
    assert picked.product_key == "strong_psu"


def test_pick_with_limit_unknown_limit_or_value_does_not_block_selection():
    pool = [_cand("only_option", 100)]
    assert _pick_with_limit(pool, 0, 0, key="length_mm", limit=None, max_allowed=True).product_key == "only_option"
    assert _pick_with_limit(pool, 0, 0, key="length_mm", limit=300, max_allowed=True).product_key == "only_option"


# ── _pick_cooler (높이 + 소켓 "부분 문자열 포함" 둘 다) ──────────────────────

def test_pick_cooler_skips_one_too_tall_for_the_case():
    pool = [_cand("tall", 60_000, height_mm=180), _cand("short", 55_000, height_mm=150)]
    picked = _pick_cooler({"쿨러": pool}, budget=0, running=0, max_height_mm=160, cpu_socket=None)
    assert picked.product_key == "short"


def test_pick_cooler_checks_socket_as_substring_not_exact_match():
    # 실제 데이터의 supported_socket은 "LGA1700/1200/115x, AM5/AM4"처럼 여러 소켓을
    # 한 문자열에 나열한다 — 정확 일치가 아니라 부분 문자열 포함으로 봐야 한다.
    pool = [
        _cand("amd_only", 50_000, height_mm=150, supported_socket="AM5/AM4"),
        _cand("multi", 60_000, height_mm=150, supported_socket="LGA1700/1200/115x, AM5/AM4"),
    ]
    picked = _pick_cooler({"쿨러": pool}, budget=0, running=0, max_height_mm=None, cpu_socket="LGA1700")
    assert picked.product_key == "multi"


# ── build_computer 통합 — 실제로 재현했던 버그 시나리오 ──────────────────────

def _rank_result(pools_by_slot: dict[str, list[Candidate]]):
    from src.dto import RankResult
    rr = RankResult()
    for slot, cands in pools_by_slot.items():
        rr.slots[slot] = {"ideal_tier": None, "ranked": [c.model_dump() for c in cands], "bottleneck_hint": None}
    return rr


def test_build_computer_never_pairs_a_socket_mismatched_cpu_and_mainboard():
    # 실제로 CATALOG_SOURCE=db에서 재현됐던 상황을 축소 재현: 메인보드 랭킹 1위가
    # AM4인데 CPU 후보 전부 LGA1700인 경우.
    pools = {
        "CPU": [_cand("i3", 100_000, socket="LGA1700", tdp_w=65)],
        "GPU": [_cand("gpu", 300_000, length_mm=280, power_w=200)],
        "RAM": [_cand("ram", 80_000, mem_type="DDR4")],
        "메인보드": [
            _cand("am4_board", 55_000, socket="AM4", mem_type="DDR4", form_factor="mATX"),
            _cand("lga1700_board", 90_000, socket="LGA1700", mem_type="DDR4", form_factor="mATX"),
        ],
        "저장장치": [_cand("ssd", 60_000)],
        "파워": [_cand("psu", 70_000, wattage_w=650)],
        "케이스": [_cand("case", 60_000, max_gpu_len_mm=400, max_cooler_height_mm=160,
                        supports_form_factors=["ATX", "mATX"])],
        "쿨러": [_cand("cooler", 40_000, height_mm=150, supported_socket="LGA1700/1200, AM5/AM4")],
    }
    spec = RequirementSpec(
        list_id="t", category="computer", mode="build",
        targets={s: {} for s in pools}, budget={"total": 2_000_000, "alloc": {}},
    )
    build = build_computer(_rank_result(pools), spec, log=lambda *a: None)
    cpu = next(i for i in build.items if i.slot == "CPU")
    mb = next(i for i in build.items if i.slot == "메인보드")
    assert mb.product_key == "lga1700_board"
    assert build.link_check["socket"] == "ok"
    assert cpu.product_key == "i3"


def test_build_computer_link_check_reports_gpu_length_and_power_as_ok_when_compatible():
    pools = {
        "CPU": [_cand("cpu", 200_000, socket="AM5", tdp_w=65)],
        "GPU": [_cand("gpu", 400_000, length_mm=280, power_w=200)],
        "RAM": [_cand("ram", 80_000, mem_type="DDR5")],
        "메인보드": [_cand("mb", 100_000, socket="AM5", mem_type="DDR5", form_factor="ATX")],
        "저장장치": [_cand("ssd", 60_000)],
        "파워": [_cand("psu", 90_000, wattage_w=750)],
        "케이스": [_cand("case", 60_000, max_gpu_len_mm=330, max_cooler_height_mm=170,
                        supports_form_factors=["ATX"])],
        "쿨러": [_cand("cooler", 40_000, height_mm=150, supported_socket="AM5/AM4")],
    }
    spec = RequirementSpec(
        list_id="t", category="computer", mode="build",
        targets={s: {} for s in pools}, budget={"total": 2_000_000, "alloc": {}},
    )
    build = build_computer(_rank_result(pools), spec, log=lambda *a: None)
    assert build.link_check["socket"] == "ok"
    assert build.link_check["gpu_len"] == "ok"
    assert build.link_check["cooler_height"] == "ok"
    assert build.link_check["power"] == "ok"
