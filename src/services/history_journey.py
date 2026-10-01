"""견적 리스트 히스토리의 "이렇게 정해졌어요" — 이 견적서가 대화로 어떻게 이 구성이 됐는지 몇 단계로.

부품마다 붙는 "고른 이유"가 "이 제품이 왜 좋은가"라면, 이건 "대화가 어떻게 이 구성을 만들었나"다. 규칙은 실제
대화 3개(단순·견적서 두 장·이어가기)에 조합을 대어 보고 정했다(2026-10-01):

- 결과를 바꾼 것만 단계가 된다 — 조건이 바뀐 추천, 직접 바꾸거나 뺀 부품. 아무것도 바꾸지 않은 질문은 빠진다.
- 같은 조건을 연달아 고친 건 처음 → 끝으로 줄이고, 바꿨다 되돌린 교체·다시 추천받아 사라진 교체는 뺀다.
- 말하지 않았는데 정해진 것(기본 해상도·주사율)을 밝힌다 — "예산을 올렸는데 왜 그래픽카드는 그대로지?"의 답이
  대개 여기 있다.
- 원했지만 반영하지 못한 것(자유 요청·조건에 안 들어간 게임·CPU 밖 브랜드 선호)을 밝힌다 — 예전 요약은 세 대화
  모두에서 반영되지 않은 말을 반영된 것처럼 읽히게 썼다.
- 부품 변화의 원인은 요구 사양이 실제로 달라졌을 때만 말한다(previous_compare.compare 와 같은 판단). 요구가
  그대로면 "요구 사양은 그대로"라고만 적는다.
- 어디서 왔는지는 해당할 때만 — 견적서 수정, 지난 대화 이어가기, 선호 되묻기.

모든 문장은 기록(추천 실행의 입력 조건·후보, 조건 행, 교체 이벤트, 선호 신호)에서 코드가 만든다. 짐작하지 않는다.
"""
from __future__ import annotations

import re
from uuid import UUID

from psycopg.rows import dict_row

from src.categories import load_category
from src.engine import stage2_requirement
from src.engine.brands import brand_key, cpu_brand_pref
from src.engine.lang import fmt_money, josa
from src.services import previous_compare

# 단계에서 보여 주는 조건 — 추천 결과를 바꾸는 것만(previous_compare._COMPARED_KEYS + CPU 브랜드).
_KEYS = ("purpose", "games", "budget_max", "priority", "resolution", "brand_pref")
_BRAND_PREF = {"intel": "Intel", "amd": "AMD"}
_QUOTE_LIMIT = 60


def _clip(text: str) -> str:
    """사용자 말 인용. 칩으로 고른 금액은 숫자만 남으므로("3000000") 말하는 단위로 적는다."""
    text = " ".join(text.split())
    if text.isdigit() and len(text) >= 4:
        return _man(int(text))
    return text if len(text) <= _QUOTE_LIMIT else text[: _QUOTE_LIMIT - 1] + "…"


def _man(krw) -> str:
    """사용자가 말하는 단위로 — 만 원 단위로 떨어지면 "150만 원", 아니면 원 단위."""
    n = int(krw)
    return f"{n // 10_000:,}만 원" if n >= 10_000 and n % 10_000 == 0 else fmt_money(n)


def _display(cat_def: dict, values: dict) -> dict[str, tuple[str, str]]:
    """조건 키 → (이름, 표시값). 조건 화면과 같은 표시값을 쓰고, 예산은 만 원, CPU 브랜드는 대표 표기로."""
    from src.services.session_service import _build_fields
    shown = {f["key"]: (f["label"], f["display"]) for f in _build_fields(cat_def, values)
             if f["key"] in _KEYS and f["display"]}
    if values.get("budget_max"):
        shown["budget_max"] = ("예산", _man(values["budget_max"]))
    if values.get("brand_pref") in _BRAND_PREF:
        shown["brand_pref"] = ("CPU 브랜드", _BRAND_PREF[values["brand_pref"]])
    return shown


def _wanted(cat_def: dict, values: dict) -> str:
    """처음 원한 것 한 줄 — "게임 · 150만 원 · 성능 우선 · Intel CPU". 화면 표시값은 말하지 않은 조건에 기본값을
    채우므로(해상도 → FHD 144Hz) 실제로 정해진 조건만 넣는다 — 기본값은 따로 "말씀 안 하셔서"로 밝힌다."""
    shown = {k: v for k, v in _display(cat_def, values).items() if values.get(k) not in (None, "", [])}
    parts = [shown[k][1] for k in ("purpose", "games", "budget_max", "priority", "resolution") if k in shown]
    if "brand_pref" in shown:
        parts.append(f"{shown['brand_pref'][1]} CPU")
    return " · ".join(parts)


# ── 기록 읽기 ──

def _cur(conn):
    return conn.cursor(row_factory=dict_row)


def _runs(conn, revision_id: UUID) -> list[dict]:
    return _cur(conn).execute(
        "SELECT id, created_at, completed_at, input_snapshot FROM engine.recommendation_run "
        "WHERE revision_id=%s AND status IN ('completed','stale') AND completed_at IS NOT NULL ORDER BY created_at",
        (revision_id,),
    ).fetchall()


def _is_clone(run: dict) -> bool:
    """견적 수정하기로 복사한 실행 — 원본의 완료 시각을 그대로 가져와 생성 시각보다 앞선다(PlanRepo.clone_revision)."""
    return run["completed_at"] < run["created_at"]


def _result(conn, run_id: UUID) -> dict:
    from src.repo.engine_repo import EngineRepo
    return {"items": [
        {"item_id": str(r["id"]), "slot": r["slot"], "slot_label": r["slot_label"],
         "variant_id": str(r["variant_id"]),
         "product": {"name": r["product_name"], "brand": r["brand"] or ""},
         "price": int(r["price"] or 0), "qty": r["qty"] if r["qty"] is not None else 1, "selected": r["selected"]}
        for r in EngineRepo(conn).get_candidates(run_id)
    ]}


def _state(conn, run: dict) -> dict:
    return {"values": (run["input_snapshot"] or {}).get("values") or {}, "result": _result(conn, run["id"]),
            "at": run["created_at"], "run_id": run["id"]}


def _condition_rows(conn, revision_id: UUID) -> list[dict]:
    """이 견적서의 조건 행 전부(바뀌어 밀려난 것 포함) — 값마다 그 값을 정한 사용자 말을 찾는 데 쓴다."""
    return _cur(conn).execute(
        "SELECT pc.condition_key AS key, pc.value->'value' AS value, pc.origin, pc.status, pc.created_at, "
        "pc.source_message_id, m.content AS said "
        "FROM planning.plan_condition pc LEFT JOIN identity.message m ON m.id=pc.source_message_id "
        "WHERE pc.revision_id=%s ORDER BY pc.created_at",
        (revision_id,),
    ).fetchall()


def _user_messages(conn, revision: dict) -> list[dict]:
    """대화 처음부터 이 견적서를 확정할 때까지의 사용자 말 — 견적 수정하기로 만든 견적서도 앞 견적서 때 한 말을
    이어받으므로("오버워치 하려고요"), 반영 못 한 것은 대화 전체에서 찾는다."""
    end = revision.get("confirmed_at")
    return _cur(conn).execute(
        "SELECT id, content, created_at FROM identity.message WHERE conversation_id=%s AND role='user' "
        "AND (%s::timestamptz IS NULL OR created_at <= %s) ORDER BY created_at",
        (revision["conversation_id"], end, end),
    ).fetchall()


def _total(result: dict) -> int:
    return sum(i["price"] * i["qty"] for i in result["items"] if i["selected"])


def _said(rows: list[dict], key: str, value, after, until) -> str | None:
    """(after, until] 사이에 key 를 value 로 정한 사용자 말. 이어가기 문장처럼 사용자가 값을 말하지 않은 것은 뺀다."""
    from src.services.session_service import _RESUME_USER_TEXT
    for row in reversed(rows):
        if (row["key"] == key and row["value"] == value and row["said"] and row["said"] != _RESUME_USER_TEXT
                and (after is None or row["created_at"] > after) and (until is None or row["created_at"] <= until)):
            return _clip(row["said"])
    return None


# ── 출발점: 견적서 수정 / 지난 대화 이어가기 / 새로 ──

def _revised_base(conn, revision: dict, clone: dict) -> dict | None:
    """복사해 온 견적서. 표시(revised_from)가 있으면 그 번호, 없으면(표시 전 기록) 완료 시각이 같은 실행의 견적서."""
    from src.repo.plan_repo import REVISED_FROM_KEY, PlanRepo
    row = PlanRepo(conn).active_condition(revision["id"], REVISED_FROM_KEY)
    query = ("SELECT rr.id, rr.created_at, rr.completed_at, rr.input_snapshot, pr.revision_no, pr.deleted_at "
             "FROM engine.recommendation_run rr JOIN planning.plan_revision pr ON pr.id=rr.revision_id "
             "WHERE pr.plan_id=%s AND pr.id<>%s AND pr.state='confirmed' ")
    if row is not None:
        found = _cur(conn).execute(query + "AND pr.revision_no=%s ORDER BY rr.created_at DESC LIMIT 1",
                                   (revision["plan_id"], revision["id"], int(row["value"]["value"]))).fetchone()
    else:
        found = _cur(conn).execute(query + "AND rr.completed_at=%s ORDER BY pr.confirmed_at DESC LIMIT 1",
                                   (revision["plan_id"], revision["id"], clone["completed_at"])).fetchone()
    if found is None:
        return None
    state = _state(conn, found)
    state["at"] = revision["created_at"]
    no = found["revision_no"]
    state["origin"] = {"kind": "revised", "revision_no": no, "overwritten": found["deleted_at"] is not None,
                       "text": f"견적서 {no}에서 고쳐 시작했어요"
                               + (" (원래 견적서는 이 견적서로 덮어썼어요)" if found["deleted_at"] is not None else "")}
    return state


def _resumed_base(conn, revision: dict) -> dict | None:
    """'지난 조건으로 이어서 하기'로 가져온 목록 — 같은 주인의 것일 때만(previous_compare.find_previous 와 같게)."""
    from src.repo.plan_repo import RESUMED_FROM_KEY, PlanRepo
    from src.services.session_service import _date_label
    repo = PlanRepo(conn)
    row = repo.active_condition(revision["id"], RESUMED_FROM_KEY)
    if row is None:
        return None
    source = repo.get_current_revision(UUID(row["value"]["value"]))
    if source is None or not ((revision["user_id"] is not None and source["user_id"] == revision["user_id"])
                              or (revision["guest_session_hash"] is not None
                                  and source["guest_session_hash"] == revision["guest_session_hash"])):
        return None
    runs = _runs(conn, source["id"])
    if not runs:
        return None
    state = _state(conn, runs[-1])
    state["at"] = revision["created_at"]
    summary = repo.get_summary(source["plan_id"])
    name = (summary or {}).get("name") or "지난 대화"
    when = _date_label(summary["updated_at"]) if summary else ""
    state["origin"] = {"kind": "resumed", "list_id": str(source["plan_id"]),
                       "text": f"{when} ‘{name}’의 조건을 이어서 시작했어요".strip()}
    return state


# ── 단계 만들기 ──

def _changed_keys(cat_def: dict, before: dict, after: dict) -> set[str]:
    b, a = _display(cat_def, before["values"]), _display(cat_def, after["values"])
    return {k for k in _KEYS if b.get(k, ("", None))[1] != a.get(k, ("", None))[1]}


def _requirement_notes(cat_def: dict, before: dict, after: dict, comparison: dict,
                       changed: set[str]) -> list[str]:
    """부품이 바뀐 까닭 — 요구 사양이 달라진 부품만 원인을 말하고, 그대로면 그렇다고만 적는다."""
    notes: list[str] = []
    drivers = [c["label"] for c in comparison["condition_changes"] if c["key"] in previous_compare._REQUIREMENT_DRIVERS]
    req_before = previous_compare._requirements(cat_def, before["values"])
    req_after = previous_compare._requirements(cat_def, after["values"])
    explained = False
    for reason in comparison["reasons"]:
        if reason["kind"] != "requirement":
            continue
        fields = [f for f in previous_compare._REQUIREMENT_FIELDS if f[0] == reason["slot"] and req_before[f] != req_after[f]]
        up = any((req_after[f] or 0) > (req_before[f] or 0) for f in fields)
        cause = "·".join(drivers) or "조건"
        notes.append(f"{josa(cause, '이/가')} 바뀌어 {reason['label']} 요구 사양이 {'올라갔어요' if up else '내려갔어요'}")
        explained = True
    if comparison["part_changes"] and not explained and changed and not changed & set(previous_compare._REQUIREMENT_DRIVERS):
        labels = "·".join(_display(cat_def, after["values"]).get(k, (k, ""))[0] for k in _KEYS if k in changed)
        notes.append(f"요구 사양은 그대로라, 바뀐 {labels}에 맞춰 다시 골랐어요")
    return notes


def _group_steps(cat_def: dict, states: list[dict], rows: list[dict], user_times: list,
                 user_slots: set[str]) -> list[dict]:
    """이어지는 추천 사이의 조건 변화를 단계로. 사이에 직접 바꾼 부품이 없고 같은 조건을 다시 고친 것뿐이면 하나로
    줄인다(150만 → 180만 → 200만 = 150만 → 200만).

    마지막 추천은 그 위에서 직접 바꾼 부품까지 담고 있다 — 그 부품(user_slots)은 '직접 바꾸셨어요' 단계가 말하므로
    마지막 추천으로 가는 조건 변화의 결과에서는 뺀다."""
    groups: list[list] = []
    for i in range(1, len(states)):
        keys = _changed_keys(cat_def, states[i - 1], states[i])
        if (groups and keys and keys <= groups[-1][2]
                and not any(states[groups[-1][1]]["at"] < t <= states[i]["at"] for t in user_times)):
            groups[-1][1] = i
            continue
        groups.append([i - 1, i, set(keys)])

    steps = []
    for start, end, _keys in groups:
        before, after = states[start], states[end]
        changed = _changed_keys(cat_def, before, after)
        comparison = previous_compare.compare(before["values"], after["values"], before["result"], after["result"], "")
        if end == len(states) - 1 and user_slots:
            comparison["part_changes"] = [p for p in comparison["part_changes"] if p["slot"] not in user_slots]
            comparison["reasons"] = [r for r in comparison["reasons"] if r["slot"] not in user_slots]
        if not changed and not comparison["part_changes"]:
            continue
        b, a = _display(cat_def, before["values"]), _display(cat_def, after["values"])
        cond = [f"{a.get(k, b.get(k))[0]} {b.get(k, ('', '없음'))[1]} → {a.get(k, ('', '없음'))[1]}"
                for k in _KEYS if k in changed]
        quote = next((q for k in _KEYS if k in changed
                      for q in [_said(rows, k, after["values"].get(k), before["at"], after["at"])] if q), None)
        notes = []
        budget = before["values"].get("budget_max")
        if budget and _total(before["result"]) > int(budget):
            notes.append(f"앞선 구성이 예산을 {fmt_money(_total(before['result']) - int(budget))} 넘었어요")
        parts = [f"{p['label']} {p['before'] or '없음'} → {p['after'] or '없음'} ({fmt_money(p['price_diff'], signed=True)})"
                 for p in comparison["part_changes"]]
        notes += _requirement_notes(cat_def, before, after, comparison, changed)
        if not parts:
            notes.append("부품 구성은 그대로예요")
        elif after["values"].get("purpose") == "game" and not any(p["slot"] == "GPU" for p in comparison["part_changes"]):
            notes.append("그래픽카드는 그대로예요")
        steps.append({"kind": "change", "at": after["at"], "keys": changed,
                      "text": ", ".join(cond) if cond else "같은 조건으로 다시 추천받았어요",
                      "quote": quote, "changes": parts, "notes": notes})
    return steps


def _variant_names(conn, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT v.id, p.name FROM catalog.product_variant v JOIN catalog.product p ON p.id=v.product_id "
        "WHERE v.id = ANY(%s::uuid[])", (list(ids),)).fetchall()
    return {str(i): name for i, name in rows}


def _user_part_steps(conn, revision: dict, final_run: dict, final: dict) -> list[dict]:
    """직접 바꾸거나 뺀 부품 — 지금 구성에 남은 것만. 같은 품목을 여러 번 바꿨으면 처음 → 마지막, 되돌렸으면 뺀다."""
    events = _cur(conn).execute(
        "SELECT event_type, payload, occurred_at FROM engine.feedback_event WHERE revision_id=%s "
        "AND recommendation_run_id=%s AND event_type IN ('item_replaced','item_removed') ORDER BY occurred_at",
        (revision["id"], final_run["id"]),
    ).fetchall()
    selected = {i["item_id"]: i for i in final["result"]["items"] if i["selected"]}
    swaps: dict[str, dict] = {}
    steps = []
    for e in events:
        p = e["payload"] or {}
        if e["event_type"] == "item_replaced" and p.get("item_id"):
            seen = swaps.setdefault(p["item_id"], {"from": p.get("from_variant_id"), "slot": p.get("slot"),
                                                   "at": e["occurred_at"]})
            seen["to"] = p.get("to_variant_id")
        elif e["event_type"] == "item_removed":
            item = next((i for i in final["result"]["items"] if i["slot"] == p.get("slot")), None)
            if item is not None and not item["selected"]:
                steps.append({"kind": "remove", "at": e["occurred_at"], "keys": set(), "slot": item["slot"],
                              "text": f"{josa(item['slot_label'], '을/를')} 견적에서 빼셨어요",
                              "quote": None, "changes": [], "notes": []})
    names = _variant_names(conn, {v for s in swaps.values() for v in (s["from"], s.get("to")) if v})
    for item_id, s in swaps.items():
        if s["from"] == s.get("to") or item_id not in selected:
            continue
        label = selected[item_id]["slot_label"] or s["slot"] or "부품"
        before, after = names.get(s["from"] or ""), names.get(s.get("to") or "")
        steps.append({"kind": "swap", "at": s["at"], "keys": set(), "slot": selected[item_id]["slot"],
                      "text": f"{josa(label, '을/를')} 직접 바꾸셨어요", "quote": None,
                      "changes": [f"{before} → {after}"] if before and after else [], "notes": []})
    return steps


def _assumed_notes(cat_def: dict, final: dict, rows: list[dict]) -> list[tuple[str, str]]:
    """말하지 않았는데 정해진 것 → [(조건 키, 문장)]. 해상도가 없으면 엔진이 기본 해상도를 쓰고, "QHD"처럼 주사율 없이
    말하면 표의 주사율이 붙는다."""
    values = final["values"]
    rules = stage2_requirement.load_computer_rules()["requirements"]
    if (rules.get("purpose_profiles") or {}).get(values.get("purpose")):
        return []     # 사무·학습·창작은 해상도 대신 용도 표를 쓴다
    labels = next((m.get("display") or {} for m in cat_def.get("fields", []) if m["key"] == "resolution"), {})
    resolution = values.get("resolution")
    if not resolution:
        default = rules["default_resolution"]
        return [("resolution", f"해상도는 말씀 안 하셔서 {labels.get(default, default)} 기준으로 봤어요")]
    hz = re.search(r"(\d+)Hz", labels.get(resolution, ""))
    said = _said(rows, "resolution", resolution, None, None)
    if hz and said and hz.group(1) not in said:
        return [("resolution", f"주사율은 말씀 안 하셔서 {hz.group(1)}Hz로 봤어요")]
    return []


def _source_notes(final: dict, rows: list[dict]) -> list[str]:
    """선호 되묻기로 들어온 CPU 브랜드 — 이번 대화에서 말하지 않은 값이 들어간 까닭."""
    value = final["values"].get("brand_pref")
    row = next((r for r in reversed(rows) if r["key"] == "brand_pref" and r["status"] == "active"), None)
    if value in _BRAND_PREF and row is not None and row["origin"] == "inferred" and row["source_message_id"] is None:
        brand = _BRAND_PREF[value]
        return [f"CPU는 지난번에 {josa(brand, '이/가')} 좋다고 하셔서 {josa(brand, '으로/로')} 봤어요"]
    return []


def _unapplied(conn, revision: dict, final: dict, messages: list[dict]) -> list[str]:
    """말씀했지만 이번 추천에 반영하지 못한 것 — 자유 요청, 조건에 안 들어간 게임, CPU 밖·비선호 브랜드."""
    values = final["values"]
    lines = [f"‘{x}’ — 기록했지만 추천에 반영하는 기준이 아직 없어요" for x in values.get("extra") or []]

    rules = stage2_requirement.load_computer_rules()
    if not (rules["requirements"].get("purpose_profiles") or {}).get(values.get("purpose")):
        have, _, _ = stage2_requirement.match_games(values.get("games") or [], rules)
        said: list[str] = []
        for m in messages:
            keys, _, _ = stage2_requirement.match_games([m["content"]], rules)
            said += [k for k in keys if k not in said and k not in have]
        lines += [f"{josa(stage2_requirement.game_title_label(k, rules), '은/는')} 게임 조건으로 들어가지 않아, "
                  "일반 게임 기준으로 봤어요" for k in said]

    if revision.get("owner_user_id"):
        signals = _cur(conn).execute(
            "SELECT slot, value, direction FROM identity.preference_signal WHERE user_id=%s AND source='explicit_chat' "
            "AND dimension='brand' AND last_observed_at >= %s AND (%s::timestamptz IS NULL OR last_observed_at <= %s) "
            "ORDER BY last_observed_at",
            (revision["owner_user_id"], messages[0]["created_at"] if messages else revision["created_at"],
             revision.get("confirmed_at"), revision.get("confirmed_at")),
        ).fetchall()
        items = {i["slot"]: i for i in final["result"]["items"] if i["selected"]}
        for s in signals:
            if s["slot"] == "CPU" and s["direction"] == "prefer" and cpu_brand_pref(s["value"]) == values.get("brand_pref"):
                continue      # 이번 조건에 들어갔다
            item = items.get(s["slot"])
            label = item["slot_label"] if item else s["slot"]
            same = item is not None and brand_key(item["product"]["brand"]) == brand_key(s["value"])
            if s["direction"] == "prefer":
                line = f"{label} 브랜드는 {josa(s['value'], '이/가')} 좋다고 하셨지만, 이번 추천 조건에는 넣지 못했어요"
                lines.append(line + (f" (지금 {josa(label, '은/는')} 마침 {s['value']} 제품이에요)" if same else ""))
            else:
                line = f"{josa(s['value'], '은/는')} 별로라고 하셨지만, 이번 추천에서 빼지는 못했어요"
                lines.append(line + (f" (지금 {josa(label, '이/가')} {s['value']} 제품이에요)" if same else ""))
    return lines


def build_steps(conn, revision: dict) -> list[dict]:
    """확정한 견적서 하나의 단계 목록. 각 단계는 {kind, text, quote, changes[], notes[]} —
    kind: start | change | swap | remove | unapplied | confirm."""
    cat_def = load_category("computer")
    runs = _runs(conn, revision["id"])
    if not runs:
        return []
    rows = _condition_rows(conn, revision["id"])
    messages = _user_messages(conn, revision)

    base = _revised_base(conn, revision, runs[0]) if _is_clone(runs[0]) else _resumed_base(conn, revision)
    live = [_state(conn, r) for r in runs if not _is_clone(r)]
    states = ([base] if base else []) + live
    if not states:
        return []
    final = _state(conn, runs[-1])

    first = states[0]
    if base:
        start = {"kind": "start", "text": base["origin"]["text"], "quote": None,
                 "changes": [_wanted(cat_def, base["values"])], "notes": []}
    else:
        quotes = []
        for r in rows:
            if (r["said"] and r["created_at"] <= first["at"] and r["origin"] in ("explicit", "extracted")
                    and _clip(r["said"]) not in quotes):
                quotes.append(_clip(r["said"]))
        start = {"kind": "start", "text": "원하신 것: " + _wanted(cat_def, first["values"]),
                 "quote": " / ".join(quotes[:3]) or None, "changes": [], "notes": []}

    user_parts = _user_part_steps(conn, revision, runs[-1], final)
    middle = _group_steps(cat_def, states, rows, [s["at"] for s in user_parts],
                          {s["slot"] for s in user_parts}) + user_parts
    middle.sort(key=lambda s: s["at"])

    # 말하지 않았는데 정해진 것은 그 조건이 마지막으로 바뀐 단계에, 없으면 시작 단계에 붙인다.
    for key, note in _assumed_notes(cat_def, final, rows):
        owner = next((s for s in reversed(middle) if key in s["keys"]), start)
        owner["notes"].append(note)
    start["notes"] += _source_notes(final, rows)

    steps = [start, *middle]
    unapplied = _unapplied(conn, revision, final, messages)
    if unapplied:
        steps.append({"kind": "unapplied", "text": "말씀하셨지만 이번 추천에 반영하지 못한 것", "quote": None,
                      "changes": [], "notes": unapplied})
    if revision.get("confirmed_at") is not None and revision.get("confirmed_total") is not None:
        steps.append({"kind": "confirm", "text": f"{josa(fmt_money(revision['confirmed_total']), '으로/로')} 확정했어요",
                      "quote": None, "changes": [], "notes": []})
    return [{k: s[k] for k in ("kind", "text", "quote", "changes", "notes")} for s in steps]
