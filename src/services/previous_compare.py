"""이전 견적과 이번 견적 비교 (B1: docs/채팅기록_다음세션_시나리오.md).

무엇이 바뀌었는지(조건·부품·가격)와 왜 바뀌었는지를 **규칙으로** 정한다. 추천 엔진 밖에서 저장된 두 결과만
비교하므로 엔진 단계가 바뀌어도 영향이 없다.

인과는 요구사양([2] stage2_requirement)이 실제로 달라진 부품에만 붙인다. 두 조건으로 요구사양을 다시 계산해
부품별 최소 요구(성능 등급·VRAM·용량·파워 W)가 달라졌고 그 차이를 만든 조건(게임·해상도·용도)이 바뀌었을 때만
"그래서 올렸다"고 말한다. 요구가 그대로인데 부품이 바뀌었으면 원인을 짐작하지 않고 바뀐 조건만 나란히 적는다.

reasons 는 {slot, claim, evidence[]} 목록이다 — 지금은 게임 요구 표(규칙)가 근거를 채우고, 나중에 검색(RAG)
근거를 붙일 때도 이 목록에 항목을 더하면 된다. 문장(text)은 reasons 만 가지고 만든다.
"""
from __future__ import annotations

from uuid import UUID

from src.categories import load_category
from src.engine import stage2_requirement
from src.engine.slots import slots_from_conditions

# 비교할 조건 — 화면에 보이는 조건 중 추천 결과를 바꾸는 것만.
_COMPARED_KEYS = ("purpose", "games", "resolution", "budget_max", "priority")
# 요구사양을 바꿀 수 있는 조건. 예산·우선순위는 요구 등급이 아니라 후보 선택을 바꾼다.
_REQUIREMENT_DRIVERS = ("purpose", "games", "resolution")
# (슬롯, 요구 필드) → 사람 말
_REQUIREMENT_FIELDS = {
    ("GPU", "perf_tier_min"): "그래픽 성능 등급",
    ("GPU", "vram_gb_min"): "그래픽 메모리(GB)",
    ("CPU", "perf_tier_min"): "CPU 성능 등급",
    ("RAM", "capacity_gb_min"): "메모리 용량(GB)",
    ("파워", "wattage_min"): "파워 용량(W)",
}
# 게임 요구 표의 키 → 요구 필드(슬롯, 필드)
_GAME_TIER_FIELDS = {"gpu": ("GPU", "perf_tier_min"), "vram_gb": ("GPU", "vram_gb_min"),
                     "cpu": ("CPU", "perf_tier_min"), "ram_gb": ("RAM", "capacity_gb_min")}


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _signed_won(amount: int) -> str:
    return ("+" if amount > 0 else "-" if amount < 0 else "±") + _won(abs(amount))


def _requirements(cat_def: dict, values: dict) -> dict:
    slots = slots_from_conditions("computer", cat_def, values)
    spec = stage2_requirement.run(slots, cat_def, lambda _msg: None)
    return {key: spec.targets.get(key[0], {}).get(key[1]) for key in _REQUIREMENT_FIELDS}


def _condition_display(cat_def: dict, values: dict) -> dict[str, tuple[str, str]]:
    from src.services.session_service import _build_fields     # 조건 화면과 같은 표시값
    fields = _build_fields(cat_def, values)
    return {f["key"]: (f["label"], f["display"] or "-") for f in fields if f["key"] in _COMPARED_KEYS}


def _selected_items(result: dict) -> dict[str, dict]:
    return {i["slot"]: i for i in result.get("items") or [] if i.get("selected")}


def _game_evidence(before: dict, after: dict, field: tuple[str, str], req_before, req_after) -> list[str]:
    """게임이 바뀌어 이 요구가 달라졌을 때, 그 요구값을 정한 게임만 — 새로 들어와 요구를 올린 게임
    (요구값 = 바뀐 뒤 요구) 또는 빠지면서 요구를 내린 게임(요구값 = 바뀌기 전 요구)."""
    rules = stage2_requirement.load_computer_rules()
    old_keys, _, _ = stage2_requirement.match_games(before.get("games") or [], rules)
    new_keys, _, _ = stage2_requirement.match_games(after.get("games") or [], rules)
    titles = rules["requirements"].get("game_titles") or {}
    tier_key = next((k for k, v in _GAME_TIER_FIELDS.items() if v == field), None)
    if tier_key is None:
        return []
    lines = []
    for key, verb in [*((k, "추가") for k in new_keys if k not in old_keys),
                      *((k, "제외") for k in old_keys if k not in new_keys)]:
        value = (titles.get(key) or {}).get("tier", {}).get(tier_key)
        if value is not None and value == (req_after if verb == "추가" else req_before):
            lines.append(f"{stage2_requirement.game_title_label(key, rules)} {verb}"
                         f"({_REQUIREMENT_FIELDS[field]} {value} 요구)")
    return lines


def _game_list(raw) -> list:
    return [raw] if isinstance(raw, str) else list(raw or [])


def _games_provisional(*game_values) -> bool:
    rules = stage2_requirement.load_computer_rules()
    keys, _, _ = stage2_requirement.match_games([g for raw in game_values for g in _game_list(raw)], rules)
    return any(stage2_requirement.game_title_status(k, rules)["status"] != "approved" for k in keys)


def compare(before_values: dict, after_values: dict, before_result: dict, after_result: dict,
            previous_label: str) -> dict:
    """두 견적의 조건·결과 → 비교. 순수 함수(DB 없음)."""
    cat_def = load_category("computer")
    before_cond, after_cond = _condition_display(cat_def, before_values), _condition_display(cat_def, after_values)
    condition_changes = [
        {"key": k, "label": after_cond[k][0], "before": before_cond.get(k, ("", "-"))[1], "after": after_cond[k][1]}
        for k in _COMPARED_KEYS if k in after_cond and before_cond.get(k, ("", "-"))[1] != after_cond[k][1]
    ]
    changed_keys = {c["key"] for c in condition_changes}
    drivers = [c for c in condition_changes if c["key"] in _REQUIREMENT_DRIVERS]

    req_before, req_after = _requirements(cat_def, before_values), _requirements(cat_def, after_values)
    req_changes: dict[str, list[dict]] = {}
    for field, label in _REQUIREMENT_FIELDS.items():
        if req_before[field] != req_after[field]:
            req_changes.setdefault(field[0], []).append(
                {"field": field, "label": label, "before": req_before[field], "after": req_after[field]})

    items_before, items_after = _selected_items(before_result), _selected_items(after_result)
    part_changes, unchanged, reasons = [], [], []
    for slot in [*items_after, *(s for s in items_before if s not in items_after)]:
        old, new = items_before.get(slot), items_after.get(slot)
        label = (new or old)["slot_label"]
        old_name, new_name = (old or {}).get("product", {}).get("name"), (new or {}).get("product", {}).get("name")
        if old_name == new_name:
            unchanged.append(label)
            continue
        old_price = old["price"] * old["qty"] if old else 0
        new_price = new["price"] * new["qty"] if new else 0
        part_changes.append({"slot": slot, "label": label, "before": old_name, "after": new_name,
                             "before_price": old_price if old else None, "after_price": new_price if new else None,
                             "price_diff": new_price - old_price})
        if slot in req_changes and drivers:
            # 원인 가리기: 조건 하나만 바꿔 다시 계산해 이 부품의 요구가 달라지는 조건만 원인으로 적는다.
            # 하나씩으로는 안 달라지고 함께 바꿔야 달라지면(최댓값이 겹칠 때) 바뀐 조건을 모두 적는다.
            fields = [c["field"] for c in req_changes[slot]]
            causes = [c for c in drivers
                      if any(_requirements(cat_def, {**before_values, c["key"]: after_values.get(c["key"])})[f]
                             != req_before[f] for f in fields)] or drivers
            # 게임이 원인이면 "하는 게임 A → B" 대신 요구를 정한 게임을 표 값과 함께 적는다.
            evidence = [f"{c['label']} {c['before']} → {c['after']}" for c in causes if c["key"] != "games"]
            if any(c["key"] == "games" for c in causes):
                games = []
                for change in req_changes[slot]:
                    games += [g for g in _game_evidence(before_values, after_values, change["field"],
                                                        change["before"], change["after"]) if g not in games]
                evidence += games or [f"{c['label']} {c['before']} → {c['after']}" for c in causes if c["key"] == "games"]
            claim = ", ".join(f"{c['label']} {c['before']} → {c['after']}" for c in req_changes[slot])
            reasons.append({"slot": slot, "label": label, "kind": "requirement",
                            "claim": f"요구 {claim}", "evidence": evidence, "source": "rules",
                            "cites_games": any(c["key"] == "games" for c in causes)})
        else:
            reasons.append({"slot": slot, "label": label, "kind": "unexplained",
                            "claim": "요구 사양은 그대로예요", "evidence": [], "source": "rules"})

    total_before = sum(i["price"] * i["qty"] for i in items_before.values())
    total_after = sum(i["price"] * i["qty"] for i in items_after.values())
    comparison = {
        "available": True, "previous_label": previous_label,
        "condition_changes": condition_changes, "part_changes": part_changes, "unchanged": unchanged,
        "reasons": reasons,
        "totals": {"before": total_before, "after": total_after, "diff": total_after - total_before},
        # 게임 표를 근거로 인용했고 그 표가 잠정값일 때만 알린다.
        "caveats": (["게임 요구 등급은 팀 확인 전 잠정값이에요."]
                    if any(r.get("cites_games") for r in reasons)
                    and _games_provisional(before_values.get("games"), after_values.get("games")) else []),
    }
    comparison["text"] = comparison_text(comparison)
    return comparison


def comparison_text(c: dict) -> str:
    """규칙 문장 — reasons 에 있는 것만 말한다."""
    lines = [f"{c['previous_label']} 견적과 비교했어요."]
    if c["condition_changes"]:
        lines.append("바뀐 조건: " + ", ".join(f"{x['label']} {x['before']} → {x['after']}"
                                           for x in c["condition_changes"]))
    else:
        lines.append("조건은 같아요.")
    if not c["part_changes"]:
        lines.append("부품 구성도 같아요.")
    else:
        lines.append("바뀐 부품:")
        by_slot = {r["slot"]: r for r in c["reasons"]}
        for p in c["part_changes"]:
            before = f"{p['before']}({_won(p['before_price'])})" if p["before"] else "없음"
            after = f"{p['after']}({_won(p['after_price'])})" if p["after"] else "없음"
            lines.append(f"- {p['label']}: {before} → {after} ({_signed_won(p['price_diff'])})")
            reason = by_slot.get(p["slot"])
            if reason:
                lines.append(f"  {reason['claim']}")
            if reason and reason["evidence"]:
                lines.append("  근거: " + " / ".join(reason["evidence"]))
    if c["unchanged"]:
        lines.append("그대로인 부품: " + ", ".join(c["unchanged"]))
    t = c["totals"]
    lines.append(f"총액: {_won(t['before'])} → {_won(t['after'])} ({_signed_won(t['diff'])})")
    lines += [f"※ {x}" for x in c["caveats"]]
    return "\n".join(lines)


# ── DB: 비교 대상 찾기 ──

def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "text": reason}


def _values(repo, revision_id: UUID) -> dict:
    return {r["condition_key"]: r["value"].get("value") for r in repo.load_full(revision_id)["conditions"]}


def find_previous(conn, revision_id: UUID) -> dict | None:
    """비교할 이전 목록: "이어서 하기"로 가져온 목록이 있으면 그것, 없으면 같은 사용자의 가장 최근 추천 결과."""
    from src.repo.plan_repo import RESUMED_FROM_KEY, PlanRepo
    from src.services.recommendation_service import get_stored_result
    repo = PlanRepo(conn)
    rev = repo.get_revision(revision_id)
    row = repo.active_condition(revision_id, RESUMED_FROM_KEY)
    if row is not None:
        source = repo.get_current_revision(UUID(row["value"]["value"]))
        same_owner = source is not None and (
            (rev["user_id"] is not None and source["user_id"] == rev["user_id"])
            or (rev["guest_session_hash"] is not None and source["guest_session_hash"] == rev["guest_session_hash"]))
        if same_owner and (get_stored_result(conn, source["id"]) or {}).get("status") == "done":
            summary = repo.get_summary(source["plan_id"])
            return {"list_id": source["plan_id"], "revision_id": source["id"], "last_active_at": summary["updated_at"]}
    values = _values(repo, revision_id)
    found = repo.latest_previous(user_id=rev["user_id"],
                                 guest_session_hash=None if rev["user_id"] else rev["guest_session_hash"],
                                 category=values.get("category") or "computer", mode=values.get("mode"),
                                 exclude_list_id=rev["plan_id"], require_result=True)
    return None if found is None else {"list_id": found["list_id"], "revision_id": found["revision_id"],
                                       "last_active_at": found["last_active_at"]}


def compare_with_previous(conn, revision_id: UUID) -> dict:
    from src.repo.plan_repo import PlanRepo
    from src.services.recommendation_service import get_stored_result
    from src.services.session_service import _date_label
    repo = PlanRepo(conn)
    after_values = _values(repo, revision_id)
    if after_values.get("category") != "computer" or after_values.get("mode") != "build":
        return _unavailable("이전 견적 비교는 새 PC 견적에서만 할 수 있어요.")
    after_result = get_stored_result(conn, revision_id)
    if (after_result or {}).get("status") != "done":
        return _unavailable("이번 추천이 끝난 뒤에 비교할 수 있어요.")
    previous = find_previous(conn, revision_id)
    if previous is None:
        return _unavailable("비교할 이전 견적이 없어요.")
    before_result = get_stored_result(conn, previous["revision_id"])
    comparison = compare(_values(repo, previous["revision_id"]), after_values, before_result, after_result,
                         _date_label(previous["last_active_at"]))
    comparison["previous_list_id"] = str(previous["list_id"])
    return comparison
