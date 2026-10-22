"""성능 축(pc-fit-v4) — CPU·GPU 성능을 벤치마크 목표식 1/(1+(T/Q)^beta)로 계산한다.

설정: config/recommendation_engine.yaml 의 scoring.performance_axis, 값: config/performance_benchmarks.yaml
(출처 docs/validation/benchmark_catalog_20261016.md). 2026-10-18 결정 — beta 4, T 는 ideal_tiers 의 목표 등급을
벤치마크 눈금으로 옮긴 값(예산에 맞춰 낮추지 않는다), 사무·학습·기타는 한 벌의 지표, 게임 CPU 는 해상도와 관계없이 1080p."""
from __future__ import annotations

import math
import os
import statistics

import pytest
import yaml

from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.engine import engine_config, stage3b_rank
from src.engine import stage2_requirement as s2
from src.engine.engine_config import (EngineConfigError, benchmark_value, perf_beta, perf_metric,
                                      tier_level_value)
from src.engine.score_policy import ScoreInputError, performance_axis

_noop = lambda _m: None  # noqa: E731
_BENCH = yaml.safe_load((engine_config._ROOT / "config" / "performance_benchmarks.yaml").read_text(encoding="utf-8"))


def _median(product_type: str, metric: str, tier: int) -> float:
    return statistics.median(row[metric] for key, row in _BENCH["products"].items()
                             if key.startswith(product_type + ":") and row.get("tier") == tier and metric in row)


# ── 설정 ─────────────────────────────────────────────────────────────────────────────────────

def test_repository_config_follows_the_2026_10_18_decisions():
    assert perf_beta() == 4.0
    for res, metric in (("FHD_144", "raster_1080p"), ("QHD_165", "raster_1440p"), ("4K", "raster_4k")):
        assert perf_metric("game", "GPU", res) == metric
        assert perf_metric("game", "CPU", res) == "game_1080p"           # 게임 CPU 는 해상도와 관계없이 1080p
    assert perf_metric("creation", "CPU", None) == perf_metric("creation", "GPU", None) == "blender"
    for purpose in ("office", "study", "other"):                          # 사무·학습·기타는 한 벌
        assert perf_metric(purpose, "CPU", None) == "single_thread"
        assert perf_metric(purpose, "GPU", None) == "raster_1080p"
    assert perf_metric("unknown", "CPU", None) is None and perf_metric("game", "RAM", "FHD_144") is None


def test_benchmark_file_covers_the_catalog_and_marks_filled_values():
    products = _BENCH["products"]
    assert sum(k.startswith("cpu:") for k in products) == 40 and sum(k.startswith("gpu:") for k in products) == 40
    assert benchmark_value("gpu:nvidia:geforce-rtx-4070", "raster_1440p") == 46.5
    assert benchmark_value("gpu:nvidia:geforce-rtx-5060-ti", "raster_1440p") == 41.0     # 8GB판 값
    assert benchmark_value("gpu:amd:radeon-pro-w7900", "raster_1440p") is None             # 워크스테이션: 게임 지표 없음
    assert benchmark_value("gpu:nvidia:no-such-card", "raster_1440p") is None
    # 문서가 엔진에 들어간다고 밝힌 추정값 세 개(†·* 표시가 derived 로 남는다)
    assert products["cpu:intel:core-i3-14100f"]["derived"]["single_thread"] == "추정"
    assert products["cpu:amd:ryzen-7-7700x3d"]["derived"]["game_1080p"] == "추정"
    assert products["cpu:amd:ryzen-9-9950x3d2"]["derived"]["game_1080p"] == "추정"
    assert all(row["tier"] is None for key, row in products.items() if ":radeon-pro-" in key or ":nvidia-rtx-" in key)


def _engine_yaml(tmp_path, **perf_overrides):
    cfg = yaml.safe_load((engine_config._ROOT / "config" / "recommendation_engine.yaml").read_text(encoding="utf-8"))
    cfg["scoring"]["performance_axis"].update(perf_overrides)
    path = tmp_path / "engine.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("overrides, match", [
    ({"beta": 0}, "beta"), ({"beta": True}, "beta"),
    ({"benchmark_version": "perf-bench-old"}, "버전 불일치"),
    ({"benchmarks": "config/none.yaml"}, "벤치마크 파일 없음"),
    ({"metrics": {"game": {"CPU": "raster_1440p"}}}, "알 수 없는 지표"),          # GPU 지표를 CPU 에 쓸 수 없다
    ({"metrics": {"game": {"RAM": "game_1080p"}}}, "CPU·GPU"),
])
def test_bad_performance_settings_are_rejected(tmp_path, overrides, match):
    with pytest.raises(EngineConfigError, match=match):
        perf_beta(_engine_yaml(tmp_path, **overrides))


def test_missing_performance_section_is_an_error_not_a_default(tmp_path):
    path = tmp_path / "engine.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "config_version": "t", "scoring": {"price_axis": {"alpha": 2}}}),
                    encoding="utf-8")
    with pytest.raises(EngineConfigError, match="performance_axis 없음"):
        perf_beta(path)


# ── 목표 값 T: 등급 → 벤치마크 눈금 ─────────────────────────────────────────────────────────

def test_integer_tier_is_the_median_of_that_tier():
    assert tier_level_value("CPU", "game_1080p", 6) == pytest.approx(_median("cpu", "game_1080p", 6))
    assert tier_level_value("GPU", "raster_1080p", 6) == pytest.approx(_median("gpu", "raster_1080p", 6))


def test_half_tier_is_the_geometric_mean_of_the_two_medians():
    # 게임 QHD 의 GPU 목표 7.5 = 7등급(4060 Ti 35.2, 5060 Ti 41.0) 중앙값과 8등급 중앙값(54.8)의 기하평균
    t = tier_level_value("GPU", "raster_1440p", 7.5)
    assert t == pytest.approx(math.sqrt(_median("gpu", "raster_1440p", 7) * _median("gpu", "raster_1440p", 8)))
    assert t == pytest.approx(45.7, abs=0.05)


def test_a_tier_with_no_products_is_interpolated_on_the_log_scale():
    # CPU 에는 5등급 제품이 없다 — 게임 QHD·4K 의 CPU 목표 5.5 는 4등급과 6등급 사이 3/4 지점
    lo, hi = _median("cpu", "game_1080p", 4), _median("cpu", "game_1080p", 6)
    assert tier_level_value("CPU", "game_1080p", 5.5) == pytest.approx(lo ** 0.25 * hi ** 0.75)


def test_levels_outside_the_table_use_the_end_values():
    assert tier_level_value("GPU", "raster_4k", 1) == tier_level_value("GPU", "raster_4k", 3)
    assert tier_level_value("GPU", "raster_4k", 11) == tier_level_value("GPU", "raster_4k", 10)


def test_target_values_increase_with_the_tier():
    # 게임 지표와 CPU 렌더링만 등급 순서를 따른다. 단일 스레드(6등급 중앙값 75.4 > 7등급 75.05)와 GPU 렌더링
    # (8등급에 렌더링이 느린 AMD 카드가 많아 7등급 4,125 > 8등급 3,279)은 따르지 않는다 — 이 두 지표의 목표는
    # 사무 4·학습/기타 6등급, 창작 GPU 6등급의 점만 쓴다.
    for slot, metric in (("CPU", "game_1080p"), ("CPU", "blender"),
                         ("GPU", "raster_1080p"), ("GPU", "raster_1440p"), ("GPU", "raster_4k")):
        values = [tier_level_value(slot, metric, level / 2) for level in range(6, 21)]
        assert values == sorted(values), (slot, metric)


# ── 성능 축 식 ───────────────────────────────────────────────────────────────────────────────

def test_axis_is_one_half_at_the_target_and_uses_beta_4():
    assert performance_axis(50, 50) == 0.5
    assert performance_axis(100, 50) == pytest.approx(1 / (1 + 0.5 ** 4))
    assert performance_axis(25, 50) == pytest.approx(1 / (1 + 2 ** 4))
    assert performance_axis(25, 50, beta=1) == pytest.approx(1 / 3)


def test_axis_is_monotonic_and_bounded():
    values = [performance_axis(q, 40) for q in (1e-9, 1, 10, 30, 40, 50, 100, 1e9)]
    assert values == sorted(values) and all(0 <= v <= 1 for v in values)


@pytest.mark.parametrize("q, t, beta", [(0, 1, None), (1, 0, None), (-1, 1, None), (math.nan, 1, None),
                                        (1, math.inf, None), (True, 1, None), (1, 1, 0)])
def test_axis_rejects_bad_inputs(q, t, beta):
    with pytest.raises(ScoreInputError):
        performance_axis(q, t, beta)


# ── 3-B 점수에 연결 ──────────────────────────────────────────────────────────────────────────

def _cand(slot, key, price, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=key, price=price, specs=specs)


def test_score_uses_the_benchmark_value_when_a_target_is_given():
    target = ("raster_1440p", 45.7)
    scored = stage3b_rank._score(_cand("GPU", "gpu:nvidia:geforce-rtx-4070", 900_000, perf_tier=8),
                                 1_000_000.0, "GPU", perf_target=target)
    assert scored.breakdown["성능"] == pytest.approx(performance_axis(46.5, 45.7))
    assert scored.score_notes == []


def test_a_candidate_without_a_benchmark_row_is_placed_by_its_tier():
    target = ("raster_1440p", 45.7)
    scored = stage3b_rank._score(_cand("GPU", "gpu:live:unknown-card", 900_000, perf_tier=8),
                                 1_000_000.0, "GPU", perf_target=target)
    assert scored.breakdown["성능"] == pytest.approx(
        performance_axis(tier_level_value("GPU", "raster_1440p", 8), 45.7))
    assert scored.score_notes == ["tier_estimate:성능"]


def test_no_benchmark_and_no_tier_is_an_error():
    with pytest.raises(ScoreInputError, match="벤치마크 값"):
        stage3b_rank._score(_cand("CPU", "cpu:live:unknown", 100_000), 300_000.0, "CPU",
                            perf_target=("game_1080p", 58.0))


def test_other_slots_and_calls_without_a_target_keep_the_tier_formula():
    ram = stage3b_rank._score(_cand("RAM", "ram", 100_000, perf_tier=6), 100_000.0, "RAM",
                              perf_target=("game_1080p", 58.0))
    gpu = stage3b_rank._score(_cand("GPU", "gpu:nvidia:geforce-rtx-4070", 100_000, perf_tier=8), 100_000.0, "GPU")
    assert ram.breakdown["성능"] == 0.6 and gpu.breakdown["성능"] == 0.8


def _spec(**values) -> RequirementSpec:
    values.setdefault("budget_max", 2_000_000)
    return s2.run(Slots(category="computer", mode="build", objective_text="", values=values), {}, _noop)


def _rank(slot: str, cands: list[Candidate], **values):
    spec = _spec(**values)
    slots = Slots(category="computer", mode="build", objective_text="", values=values)
    return stage3b_rank.run(HardFilterResult(slots={slot: cands}), spec, slots, _noop)


def test_qhd_game_ranks_gpus_by_measured_speed_not_by_lineup_grade():
    """같은 가격이면 Mainstream(6) RX 7800 XT(1440p 50.7)가 High-End(8) RTX 4070(46.5)보다 성능 점수가 높다."""
    cands = [_cand("GPU", "gpu:nvidia:geforce-rtx-4070", 700_000, perf_tier=8),
             _cand("GPU", "gpu:amd:radeon-rx-7800-xt", 700_000, perf_tier=6)]
    rr = _rank("GPU", cands, purpose="game", resolution="QHD_165")
    ranked = rr.slots["GPU"]["ranked"]
    assert [c["product_key"] for c in ranked] == ["gpu:amd:radeon-rx-7800-xt", "gpu:nvidia:geforce-rtx-4070"]
    assert rr.slots["GPU"]["perf_target"] == {"metric": "raster_1440p",
                                              "value": pytest.approx(tier_level_value("GPU", "raster_1440p", 7.5))}


def test_creation_uses_render_throughput():
    """창작은 Blender — RTX 5070(6,174)이 게임에서 더 빠른 RX 9070 XT(3,279)보다 성능 점수가 높다."""
    cands = [_cand("GPU", "gpu:amd:radeon-rx-9070-xt", 900_000, perf_tier=8),
             _cand("GPU", "gpu:nvidia:geforce-rtx-5070", 900_000, perf_tier=8)]
    rr = _rank("GPU", cands, purpose="creation")
    perf = {c["product_key"]: c["breakdown"]["성능"] for c in rr.slots["GPU"]["ranked"]}
    assert perf["gpu:nvidia:geforce-rtx-5070"] > perf["gpu:amd:radeon-rx-9070-xt"]
    assert rr.slots["GPU"]["perf_target"]["metric"] == "blender"


def test_office_study_and_other_share_the_single_thread_metric_with_their_own_targets():
    cands = [_cand("CPU", "cpu:intel:core-i5-14400", 250_000, perf_tier=6)]
    targets = {p: _rank("CPU", cands, purpose=p).slots["CPU"]["perf_target"] for p in ("office", "study", "other")}
    assert {t["metric"] for t in targets.values()} == {"single_thread"}
    assert targets["office"]["value"] == pytest.approx(tier_level_value("CPU", "single_thread", 4.0))
    assert targets["study"]["value"] == targets["other"]["value"] == pytest.approx(
        tier_level_value("CPU", "single_thread", 6.0))


def test_game_cpu_target_moves_with_resolution_on_the_1080p_metric():
    cands = [_cand("CPU", "cpu:amd:ryzen-5-7600", 250_000, perf_tier=6)]
    fhd = _rank("CPU", cands, purpose="game", resolution="FHD_144").slots["CPU"]["perf_target"]
    qhd = _rank("CPU", cands, purpose="game", resolution="QHD_165").slots["CPU"]["perf_target"]
    assert fhd["metric"] == qhd["metric"] == "game_1080p"
    assert fhd["value"] == pytest.approx(tier_level_value("CPU", "game_1080p", 6.0))
    assert qhd["value"] == pytest.approx(tier_level_value("CPU", "game_1080p", 5.5))


def test_the_target_is_not_lowered_for_a_small_budget():
    cands = [_cand("GPU", "gpu:nvidia:geforce-rtx-4060", 400_000, perf_tier=6)]
    small = _rank("GPU", cands, purpose="game", resolution="QHD_165", budget_max=600_000)
    large = _rank("GPU", cands, purpose="game", resolution="QHD_165", budget_max=3_500_000)
    assert small.slots["GPU"]["perf_target"] == large.slots["GPU"]["perf_target"]


# ── 개발 카탈로그와의 일치(일회용 DB) ────────────────────────────────────────────────────────

@pytest.mark.db
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="일회용 DB 필요")
def test_every_scored_catalog_cpu_and_gpu_has_a_row_with_the_same_tier():
    from src.db import get_conn
    from src.repo import catalog_repo
    with get_conn() as conn:
        by_slot = catalog_repo.load_candidates_by_slot_from_db(conn)
    products = _BENCH["products"]
    checked = 0
    for slot in ("CPU", "GPU"):
        for cand in by_slot[slot]:
            row = products.get(cand.product_key)
            assert row is not None, cand.product_key
            assert row["tier"] == cand.specs.get("perf_tier"), cand.product_key
            checked += 1
    assert checked == 80
