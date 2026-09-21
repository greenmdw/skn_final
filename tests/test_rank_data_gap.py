"""[3-B] 검사용 스펙이 빈 후보의 감점 — 데이터 없는 싼 부품이 검사를 피해 계속 뽑히지 않게 한다."""
from __future__ import annotations

from src.dto import Candidate
from src.engine import stage3b_rank
from src.engine.stage2_requirement import load_computer_rules

GAP = load_computer_rules()["ranking"]["data_gap"]


def _case(name, price, **specs):
    return Candidate(slot="케이스", product_key=name, name=name, price=price, specs=specs)


FULL = dict(max_psu_length_mm=200, expansion_slots=7, max_gpu_len_mm=400, max_cooler_height_mm=165)


def test_only_columns_that_someone_has_are_counted():
    cands = [_case("a", 50_000), _case("b", 90_000, max_psu_length_mm=200)]
    assert stage3b_rank._data_gap_keys(cands, "케이스", GAP) == ["max_psu_length_mm"]
    assert stage3b_rank._data_gap_keys([_case("a", 50_000)], "케이스", GAP) == []      # 아무도 값이 없으면 감점 대상 아님


def test_penalty_scales_with_missing_keys_and_is_capped():
    keys = list(FULL)
    assert stage3b_rank._data_gap_penalty(_case("x", 1, **FULL), keys, GAP) == 0
    one = stage3b_rank._data_gap_penalty(_case("x", 1, **{k: v for k, v in FULL.items() if k != "expansion_slots"}), keys, GAP)
    assert one == GAP["penalty_per_key"]
    assert stage3b_rank._data_gap_penalty(_case("x", 1), keys, GAP) == GAP["max_penalty"]


def test_missing_data_lowers_the_score_but_price_still_counts():
    cheap_missing = _case("cheap", 55_000, **{k: v for k, v in FULL.items() if k != "max_psu_length_mm"})
    fair_full = _case("full", 88_000, **FULL)
    keys = list(FULL)
    args = (None, 120_000, "케이스", {})
    a = stage3b_rank._score(cheap_missing, *args, gap_penalty=stage3b_rank._data_gap_penalty(cheap_missing, keys, GAP))
    b = stage3b_rank._score(fair_full, *args, gap_penalty=stage3b_rank._data_gap_penalty(fair_full, keys, GAP))
    plain = stage3b_rank._score(cheap_missing, *args)
    assert a.score < plain.score                       # 감점이 적용됐다
    assert b.score > a.score                           # 값이 다 있는 조금 비싼 케이스가 앞선다
    assert "데이터" not in "".join(a.breakdown)         # breakdown 은 축별 값만 — 감점은 따로 뺀다


def test_gap_penalty_defaults_to_no_change():
    cand = _case("c", 60_000, **FULL)
    assert stage3b_rank._score(cand, None, 100_000, "케이스", {}).score == \
        stage3b_rank._score(cand, None, 100_000, "케이스", {}, gap_penalty=0.0).score
