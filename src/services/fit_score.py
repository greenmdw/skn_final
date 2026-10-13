"""추천 적합도의 사용자 표시 — 리뷰 계산 snapshot 의 반올림 없는 원본 값만 읽는다.

`engine.recommendation_candidate.score`(numeric(8,4))는 기존 저장 계약으로만 남고 표시·평균·순위의 원본이 아니다.
새 방식 run(engine_versions 에 score_method)인데 snapshot 값이 없거나 유효하지 않으면 네 자리 값으로 대체하지 않고
`unavailable` 로 알린다. 기존(v1) run 은 `legacy_method` 이며 100점으로 변환하지 않는다.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from src.engine.score_policy import AXES, ScoreInputError, clip01, validate_axis_weights

LEGACY_METHOD_VERSION = "v1"
_SUM_TOLERANCE = 1e-12


def display_points(x) -> float:
    """0~1 점수 → 0~100점, 소수 첫째 자리 `ROUND_HALF_UP`. 표시 단계에서 한 번만 쓴다.

    `Decimal(repr(x))` 는 float 의 최단 십진 표기를 그대로 쓴다(0.665 → 66.5). 이는 저장 반올림을 되돌리는 방법이 아니며,
    계산 자체의 부동소수점 오차(예: 합이 0.66449999…로 나온 값)까지 없앴다고 가정하지 않는다.
    bool·비유한 값·0~1 밖의 값은 ValueError."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"점수는 실수여야 합니다: {x!r}")
    if not math.isfinite(x) or not 0 <= x <= 1:
        raise ValueError(f"점수는 0~1 의 유한한 값이어야 합니다: {x!r}")
    return float((Decimal(repr(float(x))) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _fit(status: str, *, reason: str | None = None, method_version: str | None = None,
         score: float | None = None, axes: list[dict] | None = None) -> dict:
    return {"status": status, "score": score, "axes": axes or [], "method_version": method_version, "reason": reason}


def _raw_for_item(snapshot, engine_versions, *, variant_id, product_id, slot) -> tuple[str, dict]:
    """(상태, 값) — 상태는 scored|legacy_method|unavailable. scored 면 값은 원본 rank_score·축 점수·가중치·방식 버전,
    아니면 {"reason": 사유 코드}."""
    method = (engine_versions or {}).get("score_method")
    if not method:
        return "legacy_method", {}
    if snapshot is None:
        return "unavailable", {"reason": "snapshot_missing"}
    candidate = (snapshot.get("candidates") or {}).get(str(variant_id))
    if candidate is None:
        return "unavailable", {"reason": "candidate_not_in_snapshot"}
    if candidate.get("product_id") != (str(product_id) if product_id else None) or candidate.get("slot") != slot:
        return "unavailable", {"reason": "snapshot_identity_mismatch"}
    try:
        breakdown, weights = candidate["rank_breakdown"], candidate["rank_weights"]
        if candidate["score_method"] != method:
            raise ScoreInputError("점수 방식 버전이 run 과 다릅니다")
        validate_axis_weights(weights, "snapshot 가중치")
        if not isinstance(breakdown, dict) or set(breakdown) != set(AXES):
            raise ScoreInputError("snapshot 축 점수의 축이 맞지 않습니다")
        values = {axis: clip01(breakdown[axis]) for axis in AXES}
        if any(values[axis] != breakdown[axis] for axis in AXES):
            raise ScoreInputError("snapshot 축 점수가 0~1 밖입니다")
        score = candidate["rank_score"]
        display_points(score)                                   # 형식·범위 확인
        if abs(score - clip01(math.fsum(weights[a] * values[a] for a in AXES))) > _SUM_TOLERANCE:
            raise ScoreInputError("snapshot 점수가 축 가중합과 다릅니다")
    except (KeyError, TypeError, ValueError):                    # ScoreInputError 는 ValueError
        return "unavailable", {"reason": "invalid_snapshot"}
    return "scored", {"score": score, "breakdown": values, "weights": weights, "method_version": method}


def fit_for_item(snapshot, engine_versions, *, variant_id, product_id, slot) -> dict:
    """부품 하나의 추천 적합도(API `items[].fit`). 축 순서는 AXES, 값은 모두 원본에서 한 번만 반올림한다."""
    status, raw = _raw_for_item(snapshot, engine_versions, variant_id=variant_id, product_id=product_id, slot=slot)
    if status == "legacy_method":
        return _fit("legacy_method", method_version=LEGACY_METHOD_VERSION)
    if status == "unavailable":
        return _fit("unavailable", reason=raw["reason"],
                    method_version=(engine_versions or {}).get("score_method"))
    axes = [{"axis": axis, "points": display_points(raw["breakdown"][axis]), "weight": raw["weights"][axis],
             "weighted_points": display_points(raw["weights"][axis] * raw["breakdown"][axis])} for axis in AXES]
    return _fit("scored", score=display_points(raw["score"]), axes=axes, method_version=raw["method_version"])


def avg_fit(snapshot, engine_versions, selected_rows) -> dict:
    """선택된 부품의 평균 적합도. 점수가 있는 부품의 snapshot 원본 rank_score 를 `math.fsum` 평균해 마지막에 한 번만 표시 반올림한다
    (부품별 표시 점수나 DB 네 자리 값을 평균하지 않는다). `of` 는 선택된 부품 수, `count` 는 그중 점수가 있는 수."""
    rows = list(selected_rows)
    scores = []
    for row in rows:
        status, raw = _raw_for_item(snapshot, engine_versions, variant_id=row["variant_id"],
                                    product_id=row["product_id"], slot=row["slot"])
        if status == "scored":
            scores.append(raw["score"])
    average = display_points(min(1.0, max(0.0, math.fsum(scores) / len(scores)))) if scores else None
    return {"score": average, "count": len(scores), "of": len(rows)}
