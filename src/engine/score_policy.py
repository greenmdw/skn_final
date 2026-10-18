"""부품 점수식의 공통 규칙 — 입력 검증과 축 계산.

stage2(규칙 검증)와 stage3b(점수 계산)가 같이 쓴다. 서로 import하면 순환이 생겨 별도 모듈로 둔다.
점수 = 가격·성능·리뷰 세 축의 가중합이며, 입력이 잘못되면 대체값으로 덮지 않고 ScoreInputError를 낸다.
"""
from __future__ import annotations

import math

from src.engine.engine_config import perf_beta, price_alpha

AXES = ("가격", "성능", "리뷰")
_WEIGHT_TOLERANCE = 1e-9


class ScoreInputError(ValueError):
    """점수 계산에 쓸 수 없는 입력(예산·가격·등급·가중치)."""


def _finite_real(x, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ScoreInputError(f"{name}은(는) 실수여야 합니다: {x!r}")
    value = float(x)
    if not math.isfinite(value):
        raise ScoreInputError(f"{name}이(가) 유한하지 않습니다: {x!r}")
    return value


def clip01(x) -> float:
    return min(1.0, max(0.0, _finite_real(x, "점수 축 값")))


def price_axis(price, ref_budget, alpha=None) -> float:
    """가격 축 = 1 / (1 + (P/B)^alpha) — 로그 가격 Sigmoid. P = B이면 0.5, 쌀수록 1, 비쌀수록 0에 가깝다.

    alpha를 주지 않으면 config/recommendation_engine.yaml 값을 쓴다. alpha=1은 이전 식 B / (B + P)와 같다.
    범위가 [0, 1]이라 clip하지 않는다."""
    p = _finite_real(price, "가격")
    b = _finite_real(ref_budget, "참고 예산")
    if p <= 0 or b <= 0:
        raise ScoreInputError(f"가격과 참고 예산은 양수여야 합니다: 가격={price!r}, 참고 예산={ref_budget!r}")
    a = price_alpha() if alpha is None else _finite_real(alpha, "가격 축 alpha")
    if a <= 0:
        raise ScoreInputError(f"가격 축 alpha는 양수여야 합니다: {alpha!r}")
    try:
        ratio_pow = (p / b) ** a
    except OverflowError:       # P/B가 매우 크면 점수는 0에 수렴한다
        return 0.0
    return 1.0 / (1.0 + ratio_pow)


def performance_axis(value, target, beta=None) -> float:
    """성능 축 = 1 / (1 + (T/Q)^beta) — 가격 축과 같은 모양. Q = T이면 0.5, 목표보다 빠를수록 1, 느릴수록 0에 가깝다.

    Q는 후보의 벤치마크 값, T는 목표 값(같은 지표). beta를 주지 않으면 config/recommendation_engine.yaml 값을 쓴다."""
    q = _finite_real(value, "성능 값")
    t = _finite_real(target, "성능 목표 값")
    if q <= 0 or t <= 0:
        raise ScoreInputError(f"성능 값과 목표 값은 양수여야 합니다: 값={value!r}, 목표={target!r}")
    b = perf_beta() if beta is None else _finite_real(beta, "성능 축 beta")
    if b <= 0:
        raise ScoreInputError(f"성능 축 beta는 양수여야 합니다: {beta!r}")
    try:
        ratio_pow = (t / q) ** b
    except OverflowError:       # 목표보다 아주 느리면 점수는 0에 수렴한다
        return 0.0
    return 1.0 / (1.0 + ratio_pow)


def validate_axis_weights(weights, where: str) -> None:
    """키 집합 == AXES, 각 값 0~1의 0.01 단위, 합 1. 실패는 ValueError(where 포함)."""
    if not isinstance(weights, dict) or set(weights) != set(AXES):
        raise ScoreInputError(f"{where}: 가중치 축은 {list(AXES)}이어야 합니다: "
                              f"{sorted(weights) if isinstance(weights, dict) else weights!r}")
    for axis in AXES:
        v = weights[axis]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ScoreInputError(f"{where}: {axis} 가중치가 유한한 실수가 아닙니다: {v!r}")
        if not 0 <= v <= 1:
            raise ScoreInputError(f"{where}: {axis} 가중치는 0~1이어야 합니다: {v!r}")
        if abs(v * 100 - round(v * 100)) >= 1e-9:
            raise ScoreInputError(f"{where}: {axis} 가중치는 0.01 단위여야 합니다: {v!r}")
    if abs(math.fsum(weights[a] for a in AXES) - 1) > _WEIGHT_TOLERANCE:
        raise ScoreInputError(f"{where}: 가중치 합이 1이 아닙니다")
