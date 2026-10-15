"""서로 다른 두 견적의 기준별 비교표 — 호환·용도 충족·성능 등급·총액을 **기준마다 따로** 나란히 놓는다.

"어느 쪽이 더 나은가"에 종합 우열을 말하지 않는다. 기준마다 어느 쪽 값이 높은지·낮은지만 코드가 계산해 보여 주고, 확인 못 한 값은
"확인 못 함"으로 둔다(우열을 지어내지 않는다). 채팅은 이 표의 문장을 그대로 옮긴다(`facts_lines`).
DB·LLM 없이 도는 순수 함수다."""
from __future__ import annotations

from collections import Counter
from typing import Any

from src.engine.game_requirements_check import have_from_specs
from src.engine.owned_parts import resolve_owned_parts
from src.engine.quote_items import spec_text
from src.services import quote_balance, quote_review_service

# (키, 라벨, 단위, 높을수록 좋은가) — 값이 클수록 좋은 기준과 작을수록 좋은 기준을 구분한다.
_CRITERIA = (
    ("incompatible", "확정된 비호환", "건", False),
    ("compat_ok", "호환 검사 통과", "개", True),
    ("balance_ok", "용도 기준 충족 항목", "개", True),
    ("balance_short", "용도 기준 부족 항목", "개", False),
    ("gpu_tier", "GPU 성능 등급", "", True),
    ("cpu_tier", "CPU 성능 등급", "", True),
    ("ram_gb", "RAM 용량", "GB", True),
    ("vram_gb", "VRAM", "GB", True),
    ("total", "견적 총액", "원", False),
)


def side_facts(items: list[dict[str, Any]], by_slot: dict, slots: list[str], conditions: dict | None, quote_total: int | None) -> dict[str, Any]:
    """견적 하나의 기준 값. 모르는 값은 None."""
    specs = {i["category"]: spec_text(i) for i in items}
    owned = resolve_owned_parts(specs, by_slot, slots)
    compat = quote_review_service.compat_for_quote(specs, by_slot, slots, owned)
    prices = quote_review_service.price_review(specs, owned, slots)
    balance = quote_balance.assess(conditions or {}, owned, prices)
    states = Counter(r["state"] for r in balance.get("rows") or []) if balance.get("available") else None
    sp = lambda slot: dict((owned.get(slot) or {}).get("specs") or {})        # noqa: E731
    have = have_from_specs(sp("GPU") or None, sp("CPU") or None, sp("RAM") or None, 1)
    priced = [i["quote_line_total"] for i in items if i.get("quote_line_total") is not None]
    total = quote_total or (sum(priced) if priced and len(priced) == len(items) else None)
    return {
        "incompatible": len(compat["incompatible"]), "compat_ok": compat["summary"].get("ok", 0),
        "compat_unknown": compat["summary"].get("unknown", 0),
        "balance_ok": states["ok"] if states is not None else None,
        "balance_short": states["short"] if states is not None else None,
        "gpu_tier": have["gpu"], "cpu_tier": have["cpu"], "ram_gb": have["ram_gb"], "vram_gb": have["vram_gb"],
        "total": total,
        "confirmed_parts": sum(1 for i in items if i.get("match_status") == "confirmed"), "parts": len(items),
    }


def _text(value: Any, unit: str) -> str:
    if value is None:
        return "확인 못 함"
    if unit == "원":
        return f"{int(value):,}원"
    shown = f"{value:g}" if isinstance(value, float) else str(value)
    return shown + (unit if unit in ("건", "개", "GB") else "")


def build_criteria(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """기준마다 {key, label, a, b, a_text, b_text, better('a'|'b'|'tie'|None)}. 한쪽이라도 모르는 값이면 better 는 None."""
    rows = []
    for key, label, unit, higher_better in _CRITERIA:
        va, vb = a.get(key), b.get(key)
        if va is None and vb is None and key.startswith("balance"):
            continue                                        # 용도를 안 알려 균형을 못 본 경우는 표에서 뺀다
        if va is None or vb is None or va == vb:
            better = "tie" if (va is not None and va == vb) else None
        else:
            better = "a" if (va > vb) == higher_better else "b"
        rows.append({"key": key, "label": label, "a": va, "b": vb, "a_text": _text(va, unit), "b_text": _text(vb, unit),
                     "higher_is_better": higher_better, "better": better})
    # 참고 줄(우열 없음) — 카탈로그로 확정되지 않은 부품은 호환·등급이 "확인 못 함"이 되므로 위 값을 읽을 때 같이 봐야 한다.
    if a.get("parts") and b.get("parts"):
        rows.append({"key": "confirmed_parts", "label": "카탈로그로 확정된 부품", "a": a["confirmed_parts"], "b": b["confirmed_parts"],
                     "a_text": f"{a['confirmed_parts']}/{a['parts']}개", "b_text": f"{b['confirmed_parts']}/{b['parts']}개",
                     "higher_is_better": True, "better": None, "info": True})
    return rows


def facts_lines(criteria: list[dict[str, Any]], label_a: str, label_b: str) -> list[str]:
    """채팅 근거 문장 — 기준마다 한 줄. 종합 우열은 말하지 않는다."""
    if not criteria:
        return []
    lines = ["기준별 비교(기준마다 따로 봅니다):"]
    for row in criteria:
        if row.get("info"):
            lines.append(f"- {row['label']}: {label_a} {row['a_text']} / {label_b} {row['b_text']} "
                         "(확정되지 않은 부품은 위 호환·등급 비교에서 '확인 못 함'이 됩니다)")
            continue
        verdict = {"a": f"{label_a} 쪽이 {'높음' if row['higher_is_better'] else '낮음'}",
                   "b": f"{label_b} 쪽이 {'높음' if row['higher_is_better'] else '낮음'}",
                   "tie": "같음", None: "한쪽이라도 확인 못 해 비교하지 않음"}[row["better"]]
        lines.append(f"- {row['label']}: {label_a} {row['a_text']} / {label_b} {row['b_text']} → {verdict}")
    lines.append("이 표는 기준마다 값을 나란히 놓은 것이며 어느 견적이 종합적으로 더 낫다고 판단하지 않습니다.")
    return lines


def game_lines(criteria: list[dict[str, Any]], label_a: str, label_b: str, game: str) -> str:
    """두 견적 각각의 게임 요구 사양 비교 — 기준 표의 등급·용량 값을 그대로 쓴다(표에 없는 게임이면 그 사실만)."""
    from src.engine.game_requirements_check import check_games

    row = {r["key"]: r for r in criteria}
    parts = []
    for side, label in (("a", label_a), ("b", label_b)):
        have = {"gpu": row.get("gpu_tier", {}).get(side), "cpu": row.get("cpu_tier", {}).get(side),
                "ram_gb": row.get("ram_gb", {}).get(side), "vram_gb": row.get("vram_gb", {}).get(side)}
        parts.append(f"[{label}]\n" + check_games(game, have, subject="지금"))
    return "\n".join(parts)
