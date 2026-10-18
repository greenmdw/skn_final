"""추천 엔진 점수식 설정(config/recommendation_engine.yaml) 로더.

엔진 모듈을 import하지 않는다 — score_policy가 이 모듈을 읽으므로 순환을 만들지 않기 위해서다.
값이 잘못되면 기본값으로 대체하지 않고 EngineConfigError를 낸다.
"""
from __future__ import annotations

import math
import statistics
from functools import lru_cache
from pathlib import Path

import yaml

_ENGINE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "recommendation_engine.yaml"


class EngineConfigError(ValueError):
    """추천 엔진 설정 파일의 구조·값 오류."""


def _check_alpha(alpha) -> float:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
        raise EngineConfigError(f"가격 축 alpha는 유한한 양수여야 합니다: {alpha!r}")
    return float(alpha)


@lru_cache(maxsize=8)
def _load_engine_config(path: Path) -> dict:
    if not path.is_file():
        raise EngineConfigError(f"추천 엔진 설정 파일 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise EngineConfigError("추천 엔진 설정 schema_version 오류")
    version = data.get("config_version")
    if not isinstance(version, str) or not version.strip():
        raise EngineConfigError("추천 엔진 설정 config_version 없음")
    price = ((data.get("scoring") or {}).get("price_axis") or {})
    if "alpha" not in price:
        raise EngineConfigError("추천 엔진 설정에 scoring.price_axis.alpha 없음")
    _check_alpha(price["alpha"])
    return data


def load_engine_config(path: Path | None = None) -> dict:
    """버전 있는 점수식 설정. 테스트는 별도 경로를 넘겨 설정 변경을 검증한다."""
    return _load_engine_config(Path(path or _ENGINE_CONFIG_PATH).resolve())


def price_alpha(path: Path | None = None) -> float:
    """가격 축 s = 1 / (1 + (P/B)^alpha)의 alpha."""
    return float(load_engine_config(path)["scoring"]["price_axis"]["alpha"])


# ── 성능 축(scoring.performance_axis) ───────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[2]
PERF_SLOT_TYPES = {"CPU": "cpu", "GPU": "gpu"}


def _positive(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise EngineConfigError(f"{what}은(는) 유한한 양수여야 합니다: {value!r}")
    return float(value)


@lru_cache(maxsize=8)
def _load_benchmarks(path: Path) -> dict:
    if not path.is_file():
        raise EngineConfigError(f"벤치마크 파일 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise EngineConfigError("벤치마크 파일 schema_version 오류")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(PERF_SLOT_TYPES.values()):
        raise EngineConfigError(f"벤치마크 파일 metrics 는 {sorted(PERF_SLOT_TYPES.values())} 를 가져야 합니다")
    products = data.get("products")
    if not isinstance(products, dict) or not products:
        raise EngineConfigError("벤치마크 파일 products 없음")
    for key, row in products.items():
        product_type = str(key).split(":", 1)[0]
        if product_type not in metrics or not isinstance(row, dict):
            raise EngineConfigError(f"벤치마크 행 오류: {key}")
        if row.get("tier") is not None:
            _positive(row["tier"], f"{key} tier")
        for name, value in row.items():
            if name in ("tier", "derived"):
                continue
            if name not in metrics[product_type]:
                raise EngineConfigError(f"{key}: 알 수 없는 지표 {name}")
            _positive(value, f"{key} {name}")
        for name, kind in (row.get("derived") or {}).items():
            if name not in row or kind not in ("환산", "추정"):
                raise EngineConfigError(f"{key}: derived 표시 오류 {name}={kind!r}")
    return data


def _perf_settings(cfg: dict) -> dict:
    perf = (cfg.get("scoring") or {}).get("performance_axis")
    if not isinstance(perf, dict):
        raise EngineConfigError("추천 엔진 설정에 scoring.performance_axis 없음")
    _positive(perf.get("beta"), "성능 축 beta")
    bench = _load_benchmarks((_ROOT / str(perf.get("benchmarks") or "")).resolve())
    if perf.get("benchmark_version") != bench.get("benchmark_version"):
        raise EngineConfigError(f"벤치마크 버전 불일치: 설정 {perf.get('benchmark_version')!r}, "
                                f"파일 {bench.get('benchmark_version')!r}")
    metrics = perf.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise EngineConfigError("성능 축 metrics 없음")
    for purpose, by_slot in metrics.items():
        if not isinstance(by_slot, dict) or not set(by_slot) <= set(PERF_SLOT_TYPES):
            raise EngineConfigError(f"성능 축 metrics.{purpose} 는 CPU·GPU 슬롯만 가질 수 있습니다")
        for slot, metric in by_slot.items():
            names = metric.values() if isinstance(metric, dict) else [metric]
            for name in names:
                if name not in bench["metrics"][PERF_SLOT_TYPES[slot]]:
                    raise EngineConfigError(f"성능 축 metrics.{purpose}.{slot}: 알 수 없는 지표 {name!r}")
    return perf


def perf_beta(path: Path | None = None) -> float:
    """성능 축 s = 1 / (1 + (T/Q)^beta)의 beta."""
    return float(_perf_settings(load_engine_config(path))["beta"])


def perf_metric(purpose: str, slot: str, resolution: str | None, path: Path | None = None) -> str | None:
    """용도·슬롯(·해상도)에 쓸 지표 이름. 정해 두지 않은 용도·슬롯·해상도는 None."""
    metric = (_perf_settings(load_engine_config(path))["metrics"].get(purpose) or {}).get(slot)
    if isinstance(metric, dict):
        return metric.get(resolution)
    return metric


def _benchmarks(path: Path | None) -> dict:
    perf = _perf_settings(load_engine_config(path))
    return _load_benchmarks((_ROOT / perf["benchmarks"]).resolve())


def benchmark_value(product_key: str, metric: str, path: Path | None = None) -> float | None:
    """제품의 지표 값. 표에 없는 제품·지표는 None."""
    value = (_benchmarks(path)["products"].get(product_key) or {}).get(metric)
    return float(value) if value is not None else None


def tier_level_value(slot: str, metric: str, level: float, path: Path | None = None) -> float:
    """등급(1~10 눈금)을 지표 눈금으로 옮긴 값. 등급마다 그 등급 제품들의 중앙값을 구하고, 사이 등급은 로그 눈금에서
    선형으로 잇는다(7.5 = 7등급과 8등급 중앙값의 기하평균). 표의 가장 낮은·높은 등급 밖은 끝 값을 쓴다."""
    product_type = PERF_SLOT_TYPES[slot]
    by_tier: dict[float, list[float]] = {}
    for key, row in _benchmarks(path)["products"].items():
        if key.startswith(f"{product_type}:") and row.get("tier") is not None and row.get(metric) is not None:
            by_tier.setdefault(float(row["tier"]), []).append(float(row[metric]))
    if not by_tier:
        raise EngineConfigError(f"{slot} 지표 {metric} 에 등급이 있는 값이 없습니다")
    points = sorted((tier, statistics.median(values)) for tier, values in by_tier.items())
    level = float(level)
    if level <= points[0][0]:
        return points[0][1]
    if level >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= level <= t1:
            w = (level - t0) / (t1 - t0)
            return math.exp((1 - w) * math.log(v0) + w * math.log(v1))
    raise AssertionError("unreachable")
