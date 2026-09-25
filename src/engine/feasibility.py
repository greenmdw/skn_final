"""[2] 예산 예비 판정 — 부품을 고르기 전에 "요구 성능의 최저 견적"이 예산 안인지 미리 본다.

각 슬롯에서 [2]가 세운 요구(perf_tier·소켓·용량 …)를 확정적으로 어기지 않는 후보(Pass·Pending) 중
가장 싼 것을 골라 합친다. 슬롯끼리의 호환(link_rules)은 보지 않으므로 이 합계는 **하한**이다 —
실제 조합은 이보다 비쌀 수 있어도 싸질 수는 없다. 그래서 하한이 예산을 넘으면 "확정적으로 불가능"이라
말할 수 있고, 예산 안이라고 해서 조합이 있다는 보장은 못 한다(그건 [4]가 찾는다).
"""
from __future__ import annotations

from typing import Any

from src.dto import Candidate, RequirementSpec
from src.engine.lang import fmt_money
from src.engine.stage3a_hardfilter import _judge_computer

# 하한이 예산의 이 비율을 넘으면 "빠듯" — 호환되는 조합을 찾다 보면 예산을 넘기기 쉬운 구간이다.
TIGHT_RATIO = 0.85

LEVEL_OK, LEVEL_TIGHT, LEVEL_INFEASIBLE = "ok", "tight", "infeasible"


def assess(spec: RequirementSpec, by_slot: dict[str, list[Candidate]]) -> dict[str, Any]:
    """{level, estimated_min, budget, shortfall, per_slot, unfillable, message}.

    예산이 없으면(0/None) 비교할 게 없어 level=ok·message=None 이다."""
    per_slot: dict[str, int] = {}
    unfillable: list[str] = []
    for slot, target in spec.targets.items():
        prices = [c.price for c in by_slot.get(slot, [])
                  if c.price and c.price > 0 and _judge_computer(c, target).verdict != "Fail"]
        if prices:
            per_slot[slot] = min(prices)
        else:
            unfillable.append(slot)

    estimated = sum(per_slot.values())
    budget = int(spec.budget.get("total") or 0)
    out: dict[str, Any] = {
        "level": LEVEL_OK, "estimated_min": estimated, "budget": budget, "shortfall": 0,
        "per_slot": per_slot, "unfillable": unfillable, "message": None,
    }
    if not budget:
        return out

    if estimated > budget:
        out["level"] = LEVEL_INFEASIBLE
        out["shortfall"] = estimated - budget
        out["message"] = (
            f"요구 성능을 만족하는 부품의 최저가만 더해도 약 {fmt_money(estimated)}이라 "
            f"예산 {fmt_money(budget)}보다 {fmt_money(estimated - budget)} 많아요. "
            "예산을 올리거나 요구 사양(해상도·게임)을 낮추면 조합을 찾을 수 있어요."
        )
    elif estimated > budget * TIGHT_RATIO:
        out["level"] = LEVEL_TIGHT
        out["message"] = (
            f"요구 성능의 최저가 합계가 약 {fmt_money(estimated)}으로 예산 {fmt_money(budget)}의 "
            f"{round(estimated / budget * 100)}%예요. 서로 호환되는 조합을 고르면 예산을 넘을 수 있어요."
        )
    if unfillable and out["message"] is None:
        # 예산 문제는 없어도, 요구를 채우는 후보가 없는 슬롯은 알려야 한다(최저가 합계에서 빠져 있다).
        out["message"] = f"{', '.join(unfillable)}은(는) 요구 사양을 만족하는 후보를 카탈로그에서 찾지 못했어요."
    return out
