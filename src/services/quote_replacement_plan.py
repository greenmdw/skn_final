"""받은 견적 점검 — 교체 대상 추천과 교체 후 점검 (재기획 2단계).

점검 결과(호환·용도 균형·게임 요구 사양)를 입력으로 받아 **어느 부품을 먼저 바꾸면 좋은지**와 **바꿀 후보**를 정한다. 판정은 전부 코드다
(LLM 은 설명 문장만 쓴다). 추천 엔진을 새로 짜지 않는다 — 점검에 쓰는 같은 함수(호환 `compat_for_quote`, 균형 `quote_balance.assess`,
게임 `requirement_status`)로 "그 후보로 바꾸면 이유가 풀리는가"를 다시 계산해 거른다.

부품마다 종류(kind)를 낸다:
- `replace` 비호환·게임 요구 미달·용도 기준 부족 중 하나가 확인됨 → 후보를 보인다.
- `verify`  카탈로그 제품으로 확정되지 않아 확인하지 못함 → 후보를 보이지 않고 "먼저 확인"(정보 찾기)을 권한다.
- `keep`    짚을 점이 없거나(과한 부품 포함) 바꾸지 않아도 되는 부품. 비용 절감 제안은 하지 않는다.

후보 규칙(필수):
1. 현재 부품보다 성능이 같거나 높아야 한다(CPU·GPU 성능 등급, RAM·저장장치 용량, 파워 용량). 현재 값을 모르면 후보를 보이지 않는다.
2. 견적의 나머지 부품과 새로 확정 비호환이 생기면 안 된다.
3. 짚은 이유를 모두 해소해야 한다(해소하지 못하면 일부만 해소하는 후보를 따로 표시해 보인다).

위 규칙으로 거른 뒤의 **순서**는 새 컴퓨터 본체 추천과 같은 점수(가격·성능·리뷰 세 축, 우선순위별 가중치)로 정한다."""
from __future__ import annotations

import logging
import statistics
from typing import Any

from src.categories import load_category
from src.dto import Candidate
from src.engine import game_requirements_check as grc
from src.engine.owned_parts import resolve_owned_parts
from src.engine.stage3c_verify import AXIS_SLOTS
from src.services import quote_balance
from src.services import quote_review_service as qrs

log = logging.getLogger(__name__)
DEFAULT_LIMIT = 6      # 화면은 처음 3개를 보이고 "더 보기"로 6개까지(결정 ⑧)
_PRIORITY = {"incompatible": 1, "game_unmet": 2, "balance_short": 3}
_REPLACE_REASONS = frozenset(_PRIORITY)
_BALANCE_ASPECTS = ("성능 등급", "VRAM", "용량")


def _slots() -> list[str]:
    return list(load_category("computer")["slot_structure"])


def _conditions(review: dict) -> dict:
    return dict((review.get("input") or {}).get("conditions") or {})


def _have(owned: dict[str, dict]) -> dict[str, Any]:
    sp = lambda slot: dict((owned.get(slot) or {}).get("specs") or {})        # noqa: E731
    return grc.have_from_specs(sp("GPU") or None, sp("CPU") or None, sp("RAM") or None, 1)


def _game_rows(conditions: dict, owned: dict[str, dict]) -> list[dict]:
    have = _have(owned)
    rows: list[dict] = []
    for game in conditions.get("games") or []:
        rows += grc.requirement_status(str(game), have)
    return rows


def _measure(slot: str, specs: dict) -> tuple[str, float | None]:
    """부품의 성능 척도 — 같은 부품군끼리만 견준다. (이름, 값) · 척도가 없는 부품군은 ("", None)."""
    if slot in ("CPU", "GPU"):
        return "성능 등급", specs.get("perf_tier")
    if slot in ("RAM", "저장장치"):
        return "용량", specs.get("capacity_gb")
    if slot == "파워":
        return "정격 용량", specs.get("wattage_w")
    return "", None


def _grade_state(slot: str, base: dict, cand: dict) -> str:
    """후보가 현재 부품보다 'worse' / 'same_or_better' / 'unknown'(척도가 없거나 값을 모른다)."""
    name, base_value = _measure(slot, base)
    _name, cand_value = _measure(slot, cand)
    if not name:
        return "same_or_better"                 # 척도가 없는 부품군(메인보드·케이스·쿨러)은 호환으로만 거른다
    if base_value is None or cand_value is None:
        return "unknown"
    return "worse" if cand_value < base_value else "same_or_better"


def _slot_reasons(review: dict, owned: dict[str, dict], by_slot: dict[str, list[Candidate]], slots: list[str]) -> dict[str, list[dict]]:
    specs = (review.get("input") or {}).get("current_specs") or {}
    conditions = _conditions(review)
    reasons: dict[str, list[dict]] = {slot: [] for slot in owned}

    compat = qrs.compat_for_quote(specs, by_slot, slots, owned)
    for check in compat["checks"]:
        if check["state"] != "fail":
            continue
        for slot in AXIS_SLOTS.get(check["axis"], ()):
            if slot in reasons:
                reasons[slot].append({"code": "incompatible", "text": f"{check['label']}: {check['detail']}", "axis": check["axis"]})

    balance = quote_balance.assess(conditions, owned, {})
    for row in balance.get("rows") or []:
        if row["part"] in reasons and row["aspect"] in _BALANCE_ASPECTS:
            if row["state"] == "short":
                reasons[row["part"]].append({"code": "balance_short", "text": row["detail"], "aspect": row["aspect"]})
            elif row["state"] == "excess":
                reasons[row["part"]].append({"code": "excess", "text": row["detail"], "aspect": row["aspect"]})

    for row in _game_rows(conditions, owned):
        if row["state"] == "unmet" and row["slot"] in reasons:
            reasons[row["slot"]].append({"code": "game_unmet", "game": row["game"], "key": row["key"],
                                         "text": f"{row['game']} 권장 사양 미달 — " + grc.requirement_phrase(row["key"], row["need"], row["have"])})

    for slot, info in owned.items():
        if info.get("source") != "catalog":
            reasons[slot].append({"code": "unknown_info", "text": "카탈로그 제품으로 확인되지 않아 호환·용도 점검을 하지 못했어요."})
    return reasons


def _is_resolved(reason: dict, slot: str, swapped: dict[str, dict], result: dict, conditions: dict) -> bool:
    if reason["code"] == "incompatible":
        return reason["axis"] not in result["incompatible"]
    if reason["code"] == "balance_short":
        rows = quote_balance.assess(conditions, swapped, {}).get("rows") or []
        return not any(r["part"] == slot and r["aspect"] == reason["aspect"] and r["state"] == "short" for r in rows)
    if reason["code"] == "game_unmet":
        return not any(r["state"] == "unmet" and r["slot"] == slot and r["key"] == reason["key"] and r["game"] == reason["game"]
                       for r in _game_rows(conditions, swapped))
    return False


def _cost(cand: Candidate, current_price: int | None) -> int | None:
    if cand.price is None:
        return None
    return cand.price - current_price if current_price is not None else cand.price


def _recommend_scores(conn, slot: str, rows: list[dict], conditions: dict, ref_budget: float) -> dict[str, float] | None:
    """새 컴퓨터 본체 추천과 같은 점수(가격·성능·리뷰 세 축, 우선순위별 가중치)를 후보에 매긴다. product_id → 점수.
    점수를 못 매기면(성능 등급 없음, 리뷰 자료 조회 실패 등) None — 호출자가 가격순으로 되돌린다."""
    from src.dto import HardFilterResult, RequirementSpec, Slots
    from src.engine.score_policy import ScoreInputError
    from src.services.review_ranking import ReviewRankingError, rank_with_review_aspects

    if not rows or ref_budget <= 0:
        return None
    values = {k: v for k, v in conditions.items() if v is not None}
    try:
        pool = [row["_cand"].model_copy() for row in rows]               # 카탈로그 객체에 리뷰 점수를 붙이지 않게 복사본으로
        hf = HardFilterResult(slots={slot: pool})
        spec = RequirementSpec(list_id="quote-replacement", category="computer", mode="upgrade",
                               budget={"total": ref_budget, "alloc": {slot: 1.0}})
        slot_values = Slots(category="computer", mode="upgrade", objective_text="받은 견적 교체 추천", values=values)
        rank, _profiles = rank_with_review_aspects(hf, spec, slot_values, lambda _msg: None, conn=conn)
    except (ReviewRankingError, ScoreInputError, ValueError) as exc:
        log.warning("replacement ranking fell back to price order for %s: %s", slot, exc)
        return None
    return {str(c["product_id"]): float(c["score"]) for c in rank.slots[slot]["pool"] if c.get("product_id")}


VALUE_GRADE_ALLOWANCE = 1.0                 # 우선순위가 가성비일 때 CPU·GPU 후보의 성능 등급을 현재보다 이만큼까지 낮게 허용한다(결정 ④)
_ALLOWANCE_SLOTS = ("CPU", "GPU")           # RAM·저장장치·파워는 용량을 줄이는 것이 위험해 허용하지 않는다
SAVINGS_LIMIT = 3


def _dedupe(rows: list[dict]) -> list[dict]:
    """카탈로그에 같은 제품이 표기만 달리(괄호·공백) 두 번 들어 있는 경우 한 번만 보인다 — 이름을 공백·괄호 없이 견주고 가격이 같으면 같은 제품이다."""
    seen: set[tuple[str, int | None]] = set()
    out = []
    for row in rows:
        key = ("".join(ch for ch in row["name"].lower() if ch.isalnum()), row.get("price"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _reference_budget(conditions: dict, slot: str, current_price: int | None, prices: list[int]) -> float:
    """점수의 가격 축 기준(결정 ②): 총예산을 적었으면 새 컴퓨터 본체 추천과 같은 부품별 배분, 아니면 현재 부품 가격(모르면 후보 가격 중앙값)."""
    total = conditions.get("budget_max")
    if total:
        from src.engine.stage2_requirement import load_computer_rules
        requirements = load_computer_rules()["requirements"]
        profile = (requirements.get("purpose_profiles") or {}).get(conditions.get("purpose") or "") or {}
        allocation = profile.get("budget_allocation") or requirements.get("budget_allocation") or {}      # 용도별 배분, 없으면 기본(게임) 배분
        if allocation.get(slot):
            return float(total) * float(allocation[slot])
    return float(current_price or (statistics.median(prices) if prices else 0))


def _candidates(slot: str, owned: dict[str, dict], reasons: list[dict], review: dict, by_slot: dict[str, list[Candidate]],
                slots: list[str], base_incompat: set[str], limit: int,
                conn=None) -> tuple[list[dict], str | None]:
    from src.services.quote_alternatives import _spec_rows

    info = owned[slot]
    base_specs = dict(info.get("specs") or {})
    needed = [r for r in reasons if r["code"] in _REPLACE_REASONS]
    name, base_value = _measure(slot, base_specs)
    grade_unknown = bool(name) and base_value is None
    specs = (review.get("input") or {}).get("current_specs") or {}
    conditions = _conditions(review)
    value_first = conditions.get("priority") == "value"
    current_price = info.get("catalog_price") if info.get("source") == "catalog" else None

    rows: list[dict] = []
    for cand in by_slot.get(slot, []):
        if info.get("source") == "catalog" and cand.name == info.get("name"):
            continue
        cand_specs = dict(cand.specs or {})
        state = _grade_state(slot, base_specs, cand_specs)
        cautions: list[str] = []
        cand_value = _measure(slot, cand_specs)[1]
        if grade_unknown:
            cautions.append("현재 부품의 성능을 몰라 비교하지 못했어요")        # 결정 ③: 숨기지 않고 안내를 붙인다
        elif state == "unknown":
            continue                                                  # 후보의 성능 값을 몰라 낮은지 확인할 수 없다
        elif state == "worse":
            gap = (base_value or 0) - (cand_value or 0)
            if not (value_first and slot in _ALLOWANCE_SLOTS and gap <= VALUE_GRADE_ALLOWANCE):
                continue                                              # 결정 ④: 가성비 우선일 때 CPU·GPU 만 등급 1 이내를 허용
            cautions.append("성능이 낮아요")
        swapped = {**owned, slot: {"name": cand.name, "specs": cand_specs, "source": "catalog"}}
        result = qrs.compat_for_quote(specs, by_slot, slots, swapped)
        if [a for a in result["incompatible"] if a not in base_incompat]:
            continue                                                  # 이 후보 때문에 새로 비호환이 생긴다
        cost = _cost(cand, current_price)
        resolved = [r for r in needed if _is_resolved(r, slot, swapped, result, conditions)]
        if not resolved:
            continue
        rows.append({"product_id": cand.product_id, "product_key": cand.product_key, "name": cand.name, "price": cand.price,
                     "price_delta": cost if current_price is not None else None, "perf_tier": cand_specs.get("perf_tier"),
                     "grade_label": name or None,
                     "grade_change": (round(cand_value - base_value, 2) if cand_value is not None and base_value is not None else None),
                     "specs": _spec_rows(slot, base_specs, cand_specs), "resolves": [r["text"] for r in resolved],
                     "resolves_all": len(resolved) == len(needed), "cautions": cautions,
                     "_cost": cost if cost is not None else 10**12, "_cand": cand})
    # 순서: 이유를 모두 푸는 후보 → 일부만 푸는 후보(결정 ⑥), 각 묶음 안에서는 새 컴퓨터 본체 추천과 같은 점수 순.
    prices = [row["price"] for row in rows if row["price"]]
    scores = _recommend_scores(conn, slot, rows, conditions, _reference_budget(conditions, slot, current_price, prices))
    for row in rows:
        row["recommend_score"] = round(scores[str(row["product_id"])], 4) if scores and str(row["product_id"]) in scores else None
    rows.sort(key=lambda r: (not r["resolves_all"], -(r["recommend_score"] if r["recommend_score"] is not None else -1.0), r["_cost"], r["name"]))
    for row in rows:
        row.pop("_cost", None)
        row.pop("_cand", None)
    notes = []
    if not rows:
        notes.append("조건에 맞는 대안이 카탈로그에 없어요.")
    else:
        if not any(r["resolves_all"] for r in rows):
            notes.append("이유를 모두 풀어 주는 후보는 없어서 일부만 풀어 주는 후보를 보여 드려요.")
        elif not all(r["resolves_all"] for r in rows):
            notes.append("‘일부만 해결’ 표시가 붙은 후보는 짚은 이유 중 일부만 풀어 줘요.")
    if grade_unknown:
        notes.append(f"현재 부품의 {name}을 확인하지 못해 낮은 부품이 섞일 수 있어요. 먼저 정보를 확인하면 더 정확해져요.")
    rows = _dedupe(rows)
    return rows[:limit], " ".join(notes) or None


def _saving_candidates(slot: str, owned: dict[str, dict], review: dict, by_slot: dict[str, list[Candidate]], slots: list[str],
                       base_incompat: set[str]) -> tuple[list[dict], str | None]:
    """과한 부품의 절감 후보(결정 ⑪) — 우선순위가 가성비이고 균형 점검이 "기준보다 높음"으로 본 부품에만, 선택 사항으로 보인다.
    조건: 현재보다 저렴, 새 확정 비호환 없음, 용도 기준(균형 부족·게임 요구)이 새로 깨지지 않음."""
    from src.services.quote_alternatives import _spec_rows

    info = owned[slot]
    current_price = info.get("catalog_price") if info.get("source") == "catalog" else None
    if current_price is None:
        return [], "현재 부품의 가격을 몰라 절감 후보를 계산하지 못했어요."
    base_specs = dict(info.get("specs") or {})
    name, base_value = _measure(slot, base_specs)
    specs = (review.get("input") or {}).get("current_specs") or {}
    conditions = _conditions(review)
    short_before = {(r["part"], r["aspect"]) for r in (quote_balance.assess(conditions, owned, {}).get("rows") or []) if r["state"] == "short"}
    unmet_before = {(r["game"], r["key"]) for r in _game_rows(conditions, owned) if r["state"] == "unmet"}
    out: list[dict] = []
    for cand in by_slot.get(slot, []):
        if cand.price is None or cand.price >= current_price or (info.get("source") == "catalog" and cand.name == info.get("name")):
            continue
        cand_specs = dict(cand.specs or {})
        swapped = {**owned, slot: {"name": cand.name, "specs": cand_specs, "source": "catalog"}}
        if [a for a in qrs.compat_for_quote(specs, by_slot, slots, swapped)["incompatible"] if a not in base_incompat]:
            continue
        short_after = {(r["part"], r["aspect"]) for r in (quote_balance.assess(conditions, swapped, {}).get("rows") or []) if r["state"] == "short"}
        unmet_after = {(r["game"], r["key"]) for r in _game_rows(conditions, swapped) if r["state"] == "unmet"}
        if short_after - short_before or unmet_after - unmet_before:
            continue                                                  # 절감하다 용도 기준이 새로 깨진다
        cand_value = _measure(slot, cand_specs)[1]
        out.append({"product_id": cand.product_id, "product_key": cand.product_key, "name": cand.name, "price": cand.price,
                    "price_delta": cand.price - current_price, "perf_tier": cand_specs.get("perf_tier"), "grade_label": name or None,
                    "grade_change": (round(cand_value - base_value, 2) if cand_value is not None and base_value is not None else None),
                    "specs": _spec_rows(slot, base_specs, cand_specs), "resolves": [], "resolves_all": True,
                    "cautions": ["성능이 낮아져요"] if cand_value is not None and base_value is not None and cand_value < base_value else [],
                    "recommend_score": None})
    out.sort(key=lambda r: (r["price_delta"], r["name"]))                  # 가장 많이 아끼는 후보부터
    note = None if out else "용도 기준을 지키면서 더 저렴한 대안이 카탈로그에 없어요."
    return _dedupe(out)[:SAVINGS_LIMIT], note


def build_targets(review: dict, by_slot: dict[str, list[Candidate]], *, conn=None, limit: int = DEFAULT_LIMIT) -> dict:
    """저장된 점검 결과(`review`)로 부품별 교체 필요도와 후보를 만든다. DB·LLM 은 쓰지 않는다(conn 은 저장된 검색 값을 읽을 때만)."""
    slots = _slots()
    specs = (review.get("input") or {}).get("current_specs") or {}
    conditions = _conditions(review)
    owned = resolve_owned_parts(specs, by_slot, slots)
    if conn is not None:
        from src.services.live_spec_lookup import cached_for_kept_parts
        cached_for_kept_parts(conn, owned, specs)
    reasons = _slot_reasons(review, owned, by_slot, slots)
    base_incompat = set(qrs.compat_for_quote(specs, by_slot, slots, owned)["incompatible"])
    targets = []
    for slot in slots:
        if slot not in owned:
            continue
        info, why = owned[slot], reasons[slot]
        replace = [r for r in why if r["code"] in _REPLACE_REASONS]
        kind = "replace" if replace else "verify" if any(r["code"] == "unknown_info" for r in why) else "keep"
        candidates, note = ([], None)
        savings, savings_note = [], None
        if kind == "keep" and conditions.get("priority") == "value" and any(r["code"] == "excess" for r in why):
            savings, savings_note = _saving_candidates(slot, owned, review, by_slot, slots, base_incompat)
        if kind == "replace":
            candidates, note = _candidates(slot, owned, why, review, by_slot, slots, base_incompat, limit, conn=conn)
        targets.append({
            "slot": slot, "current_name": info.get("name"), "current_confirmed": info.get("source") == "catalog", "kind": kind,
            "reasons": [{k: v for k, v in r.items() if k in ("code", "text")} for r in why if r["code"] != "excess" or kind == "keep"],
            "priority": min((_PRIORITY[r["code"]] for r in replace), default=None), "candidates": candidates, "note": note,
            "savings": savings, "savings_note": savings_note,
        })
    order = {"replace": 0, "verify": 1, "keep": 2}
    slot_index = {s: i for i, s in enumerate(slots)}
    targets.sort(key=lambda t: (order[t["kind"]], t["priority"] or 9, slot_index[t["slot"]]))
    rank = 0
    for t in targets:
        if t["kind"] == "replace":
            rank += 1
            t["rank"] = rank
        else:
            t["rank"] = None
    counts = {kind: sum(t["kind"] == kind for t in targets) for kind in ("replace", "verify", "keep")}
    return {"conditions": conditions, "counts": counts, "targets": targets}


# ── 교체 후 점검 ──────────────────────────────────────────────────────────────
def _compat_counts(result: dict) -> dict[str, int]:
    summary = result["summary"]
    return {"ok": summary.get("ok", 0), "fail": summary.get("fail", 0), "unknown": summary.get("unknown", 0)}


def _game_summary(rows: list[dict]) -> dict[str, str]:
    games: dict[str, str] = {}
    for row in rows:
        current = games.get(row["game"], "met")
        games[row["game"]] = "unmet" if row["state"] == "unmet" or current == "unmet" else "unknown" if row["state"] == "unknown" or current == "unknown" else "met"
    return games


def build_state(review: dict, replacements: dict[str, Candidate], by_slot: dict[str, list[Candidate]]) -> dict:
    """교체 목록(슬롯 → 후보)을 적용했을 때의 점검 변화와 교체별 경고. 조회만 한다."""
    slots = _slots()
    specs = (review.get("input") or {}).get("current_specs") or {}
    conditions = _conditions(review)
    before = resolve_owned_parts(specs, by_slot, slots)
    after = dict(before)
    for slot, cand in replacements.items():
        after[slot] = {"name": cand.name, "specs": dict(cand.specs or {}), "source": "catalog", "catalog_price": cand.price}
    compat_before, compat_after = qrs.compat_for_quote(specs, by_slot, slots, before), qrs.compat_for_quote(specs, by_slot, slots, after)
    base_incompat = set(compat_before["incompatible"])
    balance_before, balance_after = quote_balance.assess(conditions, before, {}), quote_balance.assess(conditions, after, {})
    games_before, games_after = _game_summary(_game_rows(conditions, before)), _game_summary(_game_rows(conditions, after))
    new_fail = [a for a in compat_after["incompatible"] if a not in base_incompat]

    items, spent, unpriced = [], 0, []
    for slot, cand in replacements.items():
        info = before.get(slot) or {}
        current_price = info.get("catalog_price") if info.get("source") == "catalog" else None
        delta = cand.price - current_price if cand.price is not None and current_price is not None else None
        if delta is None:
            unpriced.append(slot)
        else:
            spent += delta
        warnings = []
        if _grade_state(slot, dict(info.get("specs") or {}), dict(cand.specs or {})) == "worse":
            warnings.append("grade_lower")
        if any(slot in AXIS_SLOTS.get(axis, ()) for axis in new_fail):
            warnings.append("new_incompatible")
        items.append({"slot": slot, "candidate": {"product_id": cand.product_id, "name": cand.name, "price": cand.price,
                                                  "perf_tier": (cand.specs or {}).get("perf_tier")},
                      "from": {"name": info.get("name"), "price": current_price}, "price_delta": delta, "warnings": warnings})
    return {
        "replacements": items,
        "compat": {"before": _compat_counts(compat_before), "after": _compat_counts(compat_after), "new_issues": new_fail,
                   "resolved_issues": [a for a in compat_before["incompatible"] if a not in compat_after["incompatible"]]},
        "balance": {"available": bool(balance_after.get("available")), "before": balance_before.get("summary") or {},
                    "after": balance_after.get("summary") or {}},
        "games": [{"game": game, "before": games_before.get(game), "after": games_after.get(game)} for game in games_after],
        "price": {"delta_total": spent, "unpriced_slots": unpriced},
    }
