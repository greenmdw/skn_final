"""추천 엔진 점수식 설정(config/recommendation_engine.yaml) 로더.

엔진 모듈을 import하지 않는다 — score_policy가 이 모듈을 읽으므로 순환을 만들지 않기 위해서다.
값이 잘못되면 기본값으로 대체하지 않고 EngineConfigError를 낸다.
"""
from __future__ import annotations

import math
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
