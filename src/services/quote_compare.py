"""PC 견적 점검 — 우리 추천과 나란히 비교 (CHK-07).

같은 조건(용도·해상도·게임·예산·우선순위)으로 추천엔진 2~4단계를 **그대로 호출**해 우리 구성을 만들고, 견적의 부품과
품목별로 나란히 놓는다. 리뷰 집계는 공통 서비스에서 조회해 순수 엔진 계산에 주입한다.
세션·run·저장은 필요 없으며, 5단계 설명 문장(LLM)은 부르지 않는다. 명시적 mock 모드만 DB 없이 실행한다.

우열을 가리지 않는다: 이름·가격·성능 등급과 그 차이만 숫자로 보여 주고, 판단은 사용자가 한다(기획서: 판정마다 계산 근거).
예산은 조건의 예산을 쓰고, 없으면 견적의 모든 부품에 가격이 있을 때 그 합계를 쓴다("같은 돈으로 우리가 추천하면?").
둘 다 없으면 비교하지 않는다 — 예산 없이 돌리면 제약이 사라져 GPU 한 개에 270만원을 쓰는 구성이 나온다.
엔진 결과가 예산을 넘겨도 막지 않고 그 사실을 결과에 적는다.
"""
from __future__ import annotations

import logging
from typing import Any

from src.categories import load_category
from src.dto import Candidate, Slots
from src.engine import feasibility as feasibility_engine
from src.engine import stage2_requirement, stage3a_hardfilter, stage4_optimize
from src.engine.quote_price import compare_price

log = logging.getLogger(__name__)
_noop = lambda _msg: None  # noqa: E731


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "conditions_used": None, "ours": None,
            "rows": [], "summary": {}, "notes": []}


def _slots(conditions: dict, budget: int) -> Slots:
    """추천 화면과 같은 방식으로 조건에 카테고리 기본값(해상도 FHD_144 등)을 채워 Slots 를 만든다."""
    cat = load_category("computer")
    values = {"mode": "build", "purpose": conditions["purpose"], "budget_max": budget}
    for key in ("resolution", "games", "priority"):
        if conditions.get(key):
            values[key] = conditions[key]
    defaults = cat.get("defaults") or {}
    assumed = {k: v for k, v in defaults.items() if values.get(k) in (None, [], "")}
    return Slots(category="computer", mode="build", objective_text="견적 점검", values={**assumed, **values},
                 assumed_keys=list(assumed))


def _budget(conditions: dict, prices: dict) -> tuple[int | None, str | None]:
    if conditions.get("budget_max"):
        return int(conditions["budget_max"]), "condition"
    summary = (prices or {}).get("summary") or {}
    if prices and prices.get("available") and summary.get("quote_total_complete"):
        total = sum(r["quoted"] for r in prices["rows"] if r.get("quoted") is not None)
        return (total, "quote_total") if total else (None, None)
    return None, None


def _recommend(conditions: dict, budget: int, by_slot: dict[str, list[Candidate]]):
    """추천엔진 2~4단계 — 추천 실행(recommendation_service.execute_recommendation)과 같은 순서."""
    cat = load_category("computer")
    slots = _slots(conditions, budget)
    # 엔진은 후보 객체에 판정·점수를 적어 넣는다 — 견적 분석이 쓰는 카탈로그가 오염되지 않게 복사본으로 돌린다.
    pool = {slot: [c.model_copy(deep=True) for c in cands] for slot, cands in by_slot.items()}
    spec = stage2_requirement.run(slots, cat, _noop)
    missing = [slot for slot in spec.targets if not pool.get(slot)]
    if missing:
        raise LookupError(f"가격이 확인된 카탈로그 후보가 없는 부품군: {', '.join(missing)}")
    feasibility = feasibility_engine.assess(spec, pool)
    spec.budget["feasibility"] = feasibility["level"]
    spec.budget["feasibility_detail"] = feasibility
    hf = stage3a_hardfilter.run(spec, pool, _noop)
    from src.services.review_ranking import rank_with_review_aspects
    rank, _profiles = rank_with_review_aspects(hf, spec, slots, _noop)
    return spec, stage4_optimize.run(rank, spec, _noop), feasibility


def _row(slot: str, ours, owned: dict | None, price_row: dict | None) -> dict:
    ours_side = {"name": ours.name, "price": ours.price, "perf_tier": ours.perf_tier or None}
    if owned is None:
        return {"part": slot, "quote": None, "ours": ours_side, "same_product": False, "price_diff": None,
                "price_diff_pct": None, "price_state": None, "tier_diff": None,
                "detail": f"견적에 이 부품이 없습니다. 우리 추천: {ours.name} {ours.price:,}원."}
    confirmed = owned.get("source") == "catalog" and owned.get("name") != owned.get("original")
    quoted = (price_row or {}).get("quoted")
    tier = (owned.get("specs") or {}).get("perf_tier") if owned.get("source") == "catalog" else None
    quote_side = {"name": owned.get("name"), "price": quoted, "perf_tier": tier, "confirmed": owned.get("source") == "catalog",
                  "quantity": (price_row or {}).get("quantity", 1)}
    same = owned.get("source") == "catalog" and owned.get("name") == ours.name
    compared = compare_price(quoted, ours.price)
    tier_diff = round(tier - ours.perf_tier, 1) if tier is not None and ours.perf_tier else None
    bits = [f"견적 {owned.get('name')}" + (f" {quoted:,}원" if quoted is not None else ""),
            f"우리 추천 {ours.name} {ours.price:,}원"]
    if same:
        detail = f"견적과 우리 추천이 같은 제품입니다({ours.name})."
        if compared["diff"] is not None:      # 같은 제품이어도 가격이 다르면 그 차이가 이 비교의 핵심이다
            detail += f" 견적 {quoted:,}원 · 우리 카탈로그 {ours.price:,}원 (견적 − 카탈로그 {compared['diff']:+,}원, {compared['diff_pct']:+.1f}%)"
    else:
        detail = " · ".join(bits)
        if compared["diff"] is not None:
            detail += f" (견적 − 추천 {compared['diff']:+,}원, {compared['diff_pct']:+.1f}%)"
        if tier_diff is not None:
            detail += f" · 성능 등급 견적 {tier:g} / 추천 {ours.perf_tier:g}"
    return {"part": slot, "quote": quote_side, "ours": ours_side, "same_product": same,
            "price_diff": compared["diff"], "price_diff_pct": compared["diff_pct"],
            "price_state": compared["state"] if compared["diff"] is not None else None,
            "tier_diff": tier_diff, "detail": detail, "confirmed": confirmed}


def assess(conditions: dict | None, owned: dict[str, dict], prices: dict, by_slot: dict[str, list[Candidate]],
           slot_structure: list[str]) -> dict:
    conditions = {k: v for k, v in (conditions or {}).items() if v not in (None, "", [])}
    if not conditions.get("purpose"):
        return _unavailable("용도(게임·사무 등)를 알려 주지 않아 같은 조건의 추천을 만들 수 없습니다.")
    budget, budget_source = _budget(conditions, prices)
    if budget is None:
        return _unavailable("예산을 알려 주거나 견적의 모든 부품에 가격이 있어야 같은 조건으로 비교할 수 있습니다.")
    try:
        spec, build, feasibility = _recommend(conditions, budget, by_slot)
    except LookupError as exc:
        return _unavailable(str(exc))
    except Exception:  # noqa: BLE001 — 비교가 실패해도 견적 분석(매칭·호환·가격·균형)은 그대로 낸다
        log.exception("quote compare: recommendation engine failed")
        return _unavailable("우리 추천을 계산하지 못했습니다. 잠시 후 다시 시도해주세요.")

    price_rows = {r["part"]: r for r in (prices or {}).get("rows") or []}
    by_ours = {item.slot: item for item in build.items}
    rows = [_row(slot, by_ours[slot], owned.get(slot), price_rows.get(slot)) for slot in slot_structure if slot in by_ours]
    for row in rows:
        row.pop("confirmed", None)

    our_total = sum(item.price for item in build.items)
    both = [r for r in rows if r["quote"] and r["quote"]["price"] is not None]
    quote_sum, ours_sum = sum(r["quote"]["price"] for r in both), sum(r["ours"]["price"] for r in both)
    summary = {
        "our_total": our_total, "budget": budget, "budget_source": budget_source, "over_budget": our_total > budget,
        "same_slots": [r["part"] for r in both], "quote_total": quote_sum, "our_total_same_slots": ours_sum,
        "diff": quote_sum - ours_sum,
        "diff_pct": round((quote_sum - ours_sum) / ours_sum * 100, 1) if ours_sum else None,
        "same_product": sum(r["same_product"] for r in rows), "missing_in_quote": sum(r["quote"] is None for r in rows),
    }
    notes: list[str] = []
    if budget_source == "quote_total":
        notes.append(f"예산을 알려 주지 않아 견적 합계 {budget:,}원을 예산으로 같은 조건의 추천을 만들었습니다.")
    if our_total > budget:
        notes.append(f"우리 추천도 예산 {budget:,}원을 넘습니다(합계 {our_total:,}원) — 이 조건으로는 예산 안의 구성을 찾지 못했습니다.")
    if feasibility.get("level") not in (None, "ok") and feasibility.get("message"):
        notes.append(feasibility["message"])          # 엔진이 계산한 근거(요구 성능의 부품 최저가 합계)
    if not conditions.get("priority"):
        notes.append("우선순위를 알려 주지 않아 추천엔진의 기본 가중치로 만들었습니다.")
    if not conditions.get("resolution") and "resolution_assumed" in spec.flags:
        notes.append("해상도를 알려 주지 않아 기본 해상도 기준으로 만들었습니다.")
    if summary["missing_in_quote"]:
        notes.append("견적에 없는 부품군은 우리 추천 합계에만 들어 있어, 견적과 같은 부품군끼리의 합계를 따로 냈습니다.")
    return {
        "available": True, "reason": None,
        "conditions_used": {**{k: conditions.get(k) for k in ("purpose", "resolution", "games", "priority")},
                            "budget": budget, "budget_source": budget_source},
        "ours": {"items": [{"slot": i.slot, "name": i.name, "price": i.price, "perf_tier": i.perf_tier or None}
                           for i in build.items],
                 "total": our_total, "link_check": build.link_check,
                 "incompatible": [axis for axis, state in build.link_check.items() if state == "fail" and axis != "budget"]},
        "rows": rows, "summary": summary, "notes": notes,
    }
