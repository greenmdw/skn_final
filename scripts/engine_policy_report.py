"""추천 엔진 정책 변경 전후 덤프(engine_policy_compare.py 출력)와 고정 시나리오 덤프(engine_policy_scenarios.py 출력)를 읽어
정책 §10·구현계획 7단계의 지표를 마크다운 표로 출력한다. 수치는 모두 덤프에서 계산한다(손으로 쓰지 않는다).

    PYTHONPATH=. uv run python scripts/engine_policy_report.py \\
        --dump 0.기준선=docs/validation/engine_policy_baseline_20261012.json \\
        --dump 1.점수식=<스크래치>/phase1.json ... --dump 최종=docs/validation/engine_policy_after_20261013.json \\
        --scenarios docs/validation/engine_policy_scenarios_20261013.json --timing-note "단독 실행" > report.md

--dump 는 순서대로 쓴다(마지막이 최종, 첫째가 기준선). 단계별 덤프는 스크래치 경로를 그대로 받는다(저장소에 넣지 않는다).
옛 덤프에 없는 필드(적격성·여유·리뷰 근거 등)는 'n/a' 로 둔다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.eligibility import is_fail_state  # noqa: E402

RECOMMENDABLE, NOT_RECOMMENDABLE, SHORTAGE, ERROR, UNJUDGED = "recommendable", "not_recommendable", "shortage", "error", "unjudged"
STATUSES = (RECOMMENDABLE, NOT_RECOMMENDABLE, SHORTAGE, ERROR, UNJUDGED)
STATUS_LABEL = {RECOMMENDABLE: "정상 추천", NOT_RECOMMENDABLE: "부적격", SHORTAGE: "후보 부족", ERROR: "오류", UNJUDGED: "판정 없음(구버전)"}
TOL = 1e-9


# ── 공통 ──────────────────────────────────────────────────────────────────────────

def classify(rec: dict) -> str:
    """요청 한 건의 결과 분류. 후보 부족(CandidateShortage)과 다른 오류를 가르고, 적격성 필드가 없는 옛 결과는 판정 없음."""
    error = rec.get("error")
    if error:
        return SHORTAGE if error.get("type") == "CandidateShortage" else ERROR
    eligibility = (rec.get("build") or {}).get("eligibility")
    if not eligibility:
        return UNJUDGED
    return RECOMMENDABLE if eligibility.get("status") == RECOMMENDABLE else NOT_RECOMMENDABLE


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return math.fsum(values) / len(values) if values else None


def percentile(values: list[float], p: float) -> float | None:
    """최근접 순위(nearest-rank) 백분위수."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[max(0, math.ceil(p / 100 * len(values)) - 1)]


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.1f}%" if total else "n/a"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v):
        return fmt(v).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def requests_of(dump: dict) -> list[dict]:
    return dump.get("requests") or []


def built(dump: dict) -> list[dict]:
    return [r for r in requests_of(dump) if r.get("build")]


def items_by_slot(rec: dict) -> dict[str, dict]:
    return {i["slot"]: i for i in (rec.get("build") or {}).get("items") or []}


# ── 결과 분류·단계 표 ─────────────────────────────────────────────────────────────

def outcome_counts(dump: dict) -> dict[str, int]:
    counts = Counter(classify(r) for r in requests_of(dump))
    return {s: counts.get(s, 0) for s in STATUSES}


def ineligible_reasons(dump: dict) -> dict[str, int]:
    """부적격 결과의 사유 코드 분포(한 결과가 여러 사유를 가지면 각각 센다)."""
    out: Counter = Counter()
    for r in requests_of(dump):
        if classify(r) == NOT_RECOMMENDABLE:
            out.update(x["code"] for x in r["build"]["eligibility"].get("reasons") or [])
    return dict(sorted(out.items()))


def shortage_slots(dump: dict) -> dict[str, int]:
    out: Counter = Counter()
    for r in requests_of(dump):
        if classify(r) == SHORTAGE:
            out.update((r["error"].get("attrs") or {}).get("slots", {}).keys())
    return dict(sorted(out.items()))


def budget_stats(dump: dict, statuses: tuple[str, ...] | None = None) -> dict:
    recs = [r for r in built(dump) if statuses is None or classify(r) in statuses]
    prices = [r["build"]["totals"].get("price") for r in recs]
    used = [r.get("budget_used_pct") for r in recs]
    return {"n": len(recs), "price_mean": mean(prices), "used_mean": mean(used), "used_min": min((u for u in used if u is not None), default=None),
            "used_p50": percentile(used, 50), "used_p90": percentile(used, 90),
            "used_max": max((u for u in used if u is not None), default=None)}


def tier_means(dump: dict, statuses: tuple[str, ...] | None = None) -> dict[str, float | None]:
    recs = [r for r in built(dump) if statuses is None or classify(r) in statuses]
    return {slot: mean([items_by_slot(r).get(slot, {}).get("perf_tier") for r in recs]) for slot in ("CPU", "GPU")}


def timing(dump: dict) -> dict:
    ms = [r.get("wall_ms") for r in requests_of(dump) if r.get("wall_ms") is not None]
    return {"n": len(ms), "mean": mean(ms), "p50": percentile(ms, 50), "p90": percentile(ms, 90), "max": max(ms, default=None)}


def stage_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        c, n = outcome_counts(d), len(requests_of(d))
        b, t = budget_stats(d), tier_means(d)
        rows.append([label, (d.get("git_commit") or "")[:8], "예" if d.get("git_dirty") else "아니오", n,
                     f"{c[RECOMMENDABLE]} ({pct(c[RECOMMENDABLE], n)})", f"{c[NOT_RECOMMENDABLE]} ({pct(c[NOT_RECOMMENDABLE], n)})",
                     f"{c[SHORTAGE]} ({pct(c[SHORTAGE], n)})", c[ERROR], c[UNJUDGED],
                     fmt(b["price_mean"], 0), fmt(b["used_mean"]), fmt(t["CPU"]), fmt(t["GPU"]), fmt(timing(d)["p50"], 0)])
    return table(["단계", "커밋", "dirty", "요청", "정상 추천", "부적격", "후보 부족", "오류", "판정 없음", "평균 총가격(원)",
                  "평균 예산 사용률(%)", "CPU 등급", "GPU 등급", "p50(ms)"], rows)


# ── 슬롯별 Pass·Pending·Fail ─────────────────────────────────────────────────────

def slot_counts(dump: dict) -> dict[str, dict]:
    """슬롯별 Pass·Pending·Fail 합과 요청 평균, Pending·Fail 사유 분포(사전 필터가 끝난 요청만)."""
    out: dict[str, dict] = {}
    n_by_slot: Counter = Counter()
    for r in requests_of(dump):
        for slot, st in (r.get("hardfilter") or {}).items():
            row = out.setdefault(slot, {"pass": 0, "pending": 0, "fail": 0, "pending_reasons": Counter(), "fail_reasons": Counter()})
            n_by_slot[slot] += 1
            for k in ("pass", "pending", "fail"):
                row[k] += st.get(k, 0)
            row["pending_reasons"].update(st.get("pending_reasons") or {})
            row["fail_reasons"].update(st.get("fail_reasons") or {})
    for slot, row in out.items():
        n = n_by_slot[slot]
        row["n"] = n
        for k in ("pass", "pending", "fail"):
            row[f"{k}_mean"] = row[k] / n
        row["pending_reasons"], row["fail_reasons"] = dict(sorted(row["pending_reasons"].items())), dict(sorted(row["fail_reasons"].items()))
    return dict(sorted(out.items()))


def slot_table(dump: dict) -> str:
    rows = [[slot, r["n"], f"{r['pass_mean']:.1f} ({r['pass']})", f"{r['pending_mean']:.1f} ({r['pending']})", f"{r['fail_mean']:.1f} ({r['fail']})"]
            for slot, r in slot_counts(dump).items()]
    return table(["슬롯", "요청", "Pass 평균(합)", "Pending 평균(합)", "Fail 평균(합)"], rows)


def reason_table(dump: dict, kind: str) -> str:
    rows = [[slot, code, n] for slot, r in slot_counts(dump).items() for code, n in r[f"{kind}_reasons"].items()]
    return table(["슬롯", "사유", "후보 수 합"], rows) if rows else "(없음)"


# ── 선택 변화 ────────────────────────────────────────────────────────────────────

def selection_changes(ref: dict, cur: dict) -> dict:
    """기준 덤프와 비교한 선택 부품 변화 — 둘 다 조합이 있는 요청만. 슬롯별 변경 수와 조합 전체가 바뀐 요청 수."""
    ref_by_id = {r["id"]: r for r in built(ref)}
    per_slot: Counter = Counter()
    pairs = changed_any = 0
    for r in built(cur):
        base = ref_by_id.get(r["id"])
        if base is None:
            continue
        pairs += 1
        a, b = items_by_slot(base), items_by_slot(r)
        diff = [s for s in set(a) | set(b) if (a.get(s) or {}).get("product_key") != (b.get(s) or {}).get("product_key")]
        per_slot.update(diff)
        changed_any += bool(diff)
    return {"pairs": pairs, "changed_any": changed_any, "per_slot": dict(sorted(per_slot.items()))}


def rank_stats(dump: dict) -> dict[str, dict]:
    """선택 부품의 3-B 순위. 단계별 덤프는 rank.top(상위 5)만 있어 비교 기준을 상위 5로 맞춘다:
    mean_top5 = 상위 5 안에 있는 선택의 평균 순위, outside_top5 = 상위 5 밖 선택 수, full_mean = 전체 풀 순위(rank_in_3b 가 있는 덤프만)."""
    inside: dict[str, list[int]] = {}
    full: dict[str, list[int]] = {}
    outside: Counter = Counter()
    slots: set[str] = set()
    for r in built(dump):
        top = (r.get("rank") or {}).get("top") or {}
        for slot, item in items_by_slot(r).items():
            slots.add(slot)
            rank = item.get("rank_in_3b")
            if rank is not None:
                full.setdefault(slot, []).append(rank)
            else:
                keys = [c["product_key"] for c in top.get(slot) or []]
                rank = keys.index(item["product_key"]) + 1 if item["product_key"] in keys else None
            if rank is None or rank > 5:
                outside[slot] += 1
            else:
                inside.setdefault(slot, []).append(rank)
    return {slot: {"mean_top5": mean(inside.get(slot, [])), "n_top5": len(inside.get(slot, [])), "outside_top5": outside.get(slot, 0),
                   "full_mean": mean(full.get(slot, []))} for slot in sorted(slots)}


def selection_table(dumps: list[tuple[str, dict]]) -> str:
    ref = dumps[0][1]
    slots = sorted({s for _, d in dumps for r in built(d) for s in items_by_slot(r)})
    rows = []
    for label, d in dumps[1:]:
        ch = selection_changes(ref, d)
        rows.append([label, ch["pairs"], f"{ch['changed_any']} ({pct(ch['changed_any'], ch['pairs'])})"] + [ch["per_slot"].get(s, 0) for s in slots])
    return table(["단계(기준선 대비)", "비교 요청", "하나라도 바뀐 요청"] + slots, rows)


def adjacent_table(dumps: list[tuple[str, dict]]) -> str:
    """직전 단계 덤프와 비교한 선택 변경 — 단계가 선택을 바꿨는지(또는 기록 필드만 바꿨는지)를 가른다."""
    slots = sorted({s for _, d in dumps for r in built(d) for s in items_by_slot(r)})
    rows = []
    for (_, prev), (label, cur) in zip(dumps, dumps[1:]):
        ch = selection_changes(prev, cur)
        rows.append([label, ch["pairs"], f"{ch['changed_any']} ({pct(ch['changed_any'], ch['pairs'])})"] + [ch["per_slot"].get(s, 0) for s in slots])
    return table(["단계(직전 단계 대비)", "비교 요청", "하나라도 바뀐 요청"] + slots, rows)


def rank_table(dumps: list[tuple[str, dict]]) -> str:
    slots = sorted({s for _, d in dumps for s in rank_stats(d)})
    rows = []
    for label, d in dumps:
        st = rank_stats(d)
        rows.append([label] + [f"{fmt(st[s]['mean_top5'])} (밖 {st[s]['outside_top5']}"
                               + (f", 전체 {fmt(st[s]['full_mean'])})" if st[s]["full_mean"] is not None else ")") if s in st else "n/a" for s in slots])
    return table(["단계"] + slots, rows)


def budget_same_requests(dumps: list[tuple[str, dict]]) -> str:
    """최종 덤프에서 정상 추천인 요청과 같은 요청만 모아 단계별 평균 예산 사용률·총가격을 비교한다(집합이 달라서 생기는 착시를 없앤다)."""
    ids = {r["id"] for r in requests_of(dumps[-1][1]) if classify(r) == RECOMMENDABLE}
    rows = []
    for label, d in dumps:
        recs = [r for r in built(d) if r["id"] in ids]
        rows.append([label, len(recs), fmt(mean([r.get("budget_used_pct") for r in recs])), fmt(mean([r["build"]["totals"].get("price") for r in recs]), 0)])
    return table(["단계", "요청", "평균 예산 사용률(%)", "평균 총가격(원)"], rows)


def budget_monotonic(dump: dict, tolerance: float = 0.05) -> list[dict]:
    """성능 우선·noise=0 에서 예산이 늘 때 총가격이 허용 오차(기본 5%) 안에서 줄지 않는지(용도별).
    tests/test_data_coverage.py::test_a_bigger_budget_never_gets_a_cheaper_performance_build 와 같은 기준을 덤프의 예산 구간에 적용한 것이다."""
    by_purpose: dict[str, list[tuple[int, int]]] = {}
    for r in built(dump):
        v = r.get("values") or {}
        if v.get("mode") == "build" and v.get("priority") == "performance" and v.get("noise_sensitive") is False and v.get("purpose"):
            by_purpose.setdefault(v["purpose"], []).append((v["budget_max"], r["build"]["totals"]["price"]))
    rows = []
    for purpose, pairs in sorted(by_purpose.items()):
        pairs.sort()
        ok = all(t2 >= t1 * (1 - tolerance) for (_, t1), (_, t2) in zip(pairs, pairs[1:]))
        rows.append({"purpose": purpose, "totals": [t for _, t in pairs], "ok": ok})
    return rows


def budget_monotonic_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        for r in budget_monotonic(d):
            rows.append([label, r["purpose"], " → ".join(f"{t:,}" for t in r["totals"]), "예" if r["ok"] else "아니오"])
    return table(["단계", "용도", "총가격(예산 100만 → 200만 → 350만)", "예산이 늘 때 총가격 유지(−5% 허용)"], rows)


def counter_stats(dump: dict) -> dict:
    """조합 탐색 카운터 — pruned_*(가지치기 사유별 합과 1회 이상 발생한 요청 수), 확대 탐색(widened)·노드 상한 도달(capped) 요청 수."""
    totals: Counter = Counter()
    requests_with: Counter = Counter()
    for r in built(dump):
        alt = r["build"].get("alternatives") or {}
        for k, v in alt.items():
            if k.startswith("pruned_") and isinstance(v, (int, float)):
                totals[k] += v
                requests_with[k] += bool(v)
        for k in ("widened", "capped"):
            requests_with[k] += bool(alt.get(k))
    return {"pruned_total": dict(sorted((k, v) for k, v in totals.items())), "requests_with": dict(sorted(requests_with.items())),
            "requests": len(built(dump))}


def counter_table(dumps: list[tuple[str, dict]]) -> str:
    keys = sorted({k for _, d in dumps for k in counter_stats(d)["requests_with"]})
    rows = [[label] + [counter_stats(d)["requests_with"].get(k, 0) for k in keys] + [counter_stats(d)["requests"]] for label, d in dumps]
    return table(["단계"] + [f"{k} 발생 요청" for k in keys] + ["조합이 나온 요청"], rows)


def budget_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        for scope, statuses in (("조합이 나온 전체", None), ("정상 추천만", (RECOMMENDABLE, UNJUDGED))):
            b = budget_stats(d, statuses)
            rows.append([label, scope, b["n"], fmt(b["price_mean"], 0), fmt(b["used_mean"]), fmt(b["used_min"]), fmt(b["used_p50"]),
                         fmt(b["used_p90"]), fmt(b["used_max"])])
    return table(["단계", "범위", "요청", "평균 총가격(원)", "예산 사용률 평균(%)", "최소", "p50", "p90", "최대"], rows)


def ram_stats(dump: dict) -> dict:
    """선택된 RAM 의 구성(단품 2개 qty=2 / 키트 qty=1)과 평균 구성 가격."""
    rams = [i for r in built(dump) for i in [items_by_slot(r).get("RAM")] if i]
    return {"n": len(rams), "single_pair": sum(1 for i in rams if i.get("qty") == 2), "kit": sum(1 for i in rams if (i.get("qty") or 1) == 1),
            "price_mean": mean([i["price"] for i in rams])}


def ram_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        r = ram_stats(d)
        rows.append([label, r["n"], r["single_pair"], r["kit"], fmt(r["price_mean"], 0)])
    text = table(["단계", "RAM 선택 수", "단품 2개 구성(qty=2)", "qty=1(키트 또는 단품 1개)", "평균 구성 가격(원)"], rows)
    prices = dumps[-1][1].get("ram_pair_prices")
    if prices:
        text += "\n\n카탈로그 기준 규격·총용량별 가장 싼 구성 가격(원, 덤프의 ram_pair_prices):\n\n" + table(
            ["규격-총용량", "가장 싼 키트", "가장 싼 단품 2개"], [[k, v.get("kit"), v.get("single_pair")] for k, v in prices.items()])
    return text


# ── 저소음 ───────────────────────────────────────────────────────────────────────

def noise_pairs(dump: dict) -> dict:
    """같은 (용도·우선순위·예산)에서 noise=0/1 쌍 비교 + 선택 부품 리뷰 근거의 정숙성 기여.

    review 필드(덤프에 있으면): 요청 프로필의 정숙성 가중(profile_quiet_alpha)과 실제 기여 항목(quiet) — 없으면 n/a."""
    groups: dict[tuple, dict[bool, dict]] = {}
    for r in requests_of(dump):
        v = r.get("values") or {}
        if v.get("mode") == "build" and "noise_sensitive" in v and v.get("purpose") and "budget_max" in v:
            groups.setdefault((v["purpose"], v.get("priority"), v["budget_max"]), {})[bool(v["noise_sensitive"])] = r
    pairs = diff_sel = diff_weights = diff_quiet_alpha = 0
    per_slot: Counter = Counter()
    deltas: dict[str, list[float]] = {}
    for pair in groups.values():
        if True not in pair or False not in pair:
            continue
        quiet, normal = pair[True], pair[False]
        if not (quiet.get("build") and normal.get("build")):
            continue
        pairs += 1
        a, b = items_by_slot(normal), items_by_slot(quiet)
        diff = [s for s in set(a) | set(b) if (a.get(s) or {}).get("product_key") != (b.get(s) or {}).get("product_key")]
        diff_sel += bool(diff)
        per_slot.update(diff)
        diff_weights += (normal.get("rank") or {}).get("weights_used") != (quiet.get("rank") or {}).get("weights_used")
        diff_quiet_alpha += _quiet_alpha_total(normal) != _quiet_alpha_total(quiet)
        if _quiet_alpha_total(normal) is not None and _quiet_alpha_total(quiet) is not None:
            deltas.setdefault(quiet["values"].get("priority") or "none", []).append(_quiet_alpha_total(quiet) - _quiet_alpha_total(normal))

    def review_side(noise: bool) -> dict:
        items = [i for r in built(dump) if bool((r.get("values") or {}).get("noise_sensitive")) is noise
                 for i in items_by_slot(r).values() if i.get("review")]
        with_contrib = [i for i in items if any(q["alpha"] > 0 for q in i["review"]["quiet"])]
        return {"items": len(items), "with_quiet_contribution": len(with_contrib),
                "profile_quiet_alpha_mean": mean([i["review"]["profile_quiet_alpha"] for i in items]) if items else None}

    return {"pairs": pairs, "selection_differs": diff_sel, "per_slot": dict(sorted(per_slot.items())),
            "outer_weights_differ": diff_weights, "profile_quiet_alpha_differs": diff_quiet_alpha,
            "quiet_alpha_delta_by_priority": {k: mean(v) for k, v in sorted(deltas.items())},
            "noise0": review_side(False), "noise1": review_side(True)}


def _quiet_alpha_total(rec: dict) -> float | None:
    values = [i["review"]["profile_quiet_alpha"] for i in items_by_slot(rec).values() if i.get("review")]
    return math.fsum(values) if values else None


def noise_delta_table(dump: dict) -> str:
    """noise=1 − noise=0 인 같은 조건 쌍에서 선택 부품들의 정숙성 요청 가중(profile_quiet_alpha) 합의 차이 평균 — 우선순위별.
    priority=quiet 은 이미 정숙성을 높게 요청하므로 0 이어야 한다(중복 배율 없음)."""
    deltas = noise_pairs(dump)["quiet_alpha_delta_by_priority"]
    return table(["우선순위", "정숙성 요청 가중 합의 차이 평균(noise=1 − noise=0)"], [[k, fmt(v, 3)] for k, v in deltas.items()]) if deltas else "(리뷰 근거가 있는 덤프 없음)"


def noise_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        n = noise_pairs(d)
        n0, n1 = n["noise0"], n["noise1"]
        rows.append([label, n["pairs"], n["selection_differs"], n["outer_weights_differ"], n["profile_quiet_alpha_differs"],
                     f"{n0['with_quiet_contribution']}/{n0['items']}" if n0["items"] else "n/a",
                     f"{n1['with_quiet_contribution']}/{n1['items']}" if n1["items"] else "n/a",
                     fmt(n0["profile_quiet_alpha_mean"], 3), fmt(n1["profile_quiet_alpha_mean"], 3)])
    return table(["단계", "noise 쌍", "선택이 다른 쌍", "바깥 가중치가 다른 쌍", "정숙성 요청 가중이 다른 쌍",
                  "noise=0 선택 부품 중 정숙성 기여 있음", "noise=1 선택 부품 중 정숙성 기여 있음",
                  "정숙성 요청 가중 평균(noise=0)", "(noise=1)"], rows)


# ── 필수 조건 위반 ───────────────────────────────────────────────────────────────

def violations(dump: dict) -> dict:
    """정상 추천(판정 없는 옛 결과 포함) 결과의 필수 조건 위반 — 예산 초과·최소 성능 미달·호환 위반·필수 정보 누락."""
    checked, found, no_floors = 0, [], 0
    for r in built(dump):
        if classify(r) not in (RECOMMENDABLE, UNJUDGED):
            continue
        checked += 1
        b = r["build"]
        budget = b.get("budget") or {}
        if budget.get("max") is not None and budget.get("used") is not None and budget["used"] > budget["max"]:
            found.append({"id": r["id"], "kind": "budget_exceeded", "detail": f"{budget['used']} > {budget['max']}"})
        floors = r.get("target_floors")
        if floors is None:
            no_floors += 1
        else:
            items = items_by_slot(r)
            for slot, floor in floors.items():
                tier = (items.get(slot) or {}).get("perf_tier")
                if slot in items and (tier is None or tier < floor):
                    found.append({"id": r["id"], "kind": "perf_below_min", "detail": f"{slot} {tier} < {floor}"})
        for axis, state in (b.get("link_check") or {}).items():
            if axis not in ("budget", "예산") and is_fail_state(state):
                found.append({"id": r["id"], "kind": "compat_violation", "detail": f"{axis}={state}"})
        for x in (b.get("eligibility") or {}).get("reasons") or []:
            found.append({"id": r["id"], "kind": x["code"], "detail": "정상 추천인데 부적격 사유가 있음"})
        for t in r.get("verification") or []:
            if t.get("eligible") is False or t.get("blocking"):
                found.append({"id": r["id"], "kind": "verification_blocking", "detail": json.dumps(t.get("blocking"), ensure_ascii=False)})
    return {"checked": checked, "count": len(found), "list": found, "requests_without_target_floors": no_floors}


def violation_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        v = violations(d)
        by_kind = Counter(x["kind"] for x in v["list"])
        rows.append([label, v["checked"], v["count"], ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items())) or "—",
                     v["requests_without_target_floors"]])
    return table(["단계", "검사한 결과", "위반 건수", "종류", "성능 하한 정보 없는 요청(성능 검사 생략)"], rows)


# ── 누락 키·보완 ─────────────────────────────────────────────────────────────────

def missing_by_part(dump: dict) -> dict[str, int]:
    """부적격 사유 중 필수 정보 누락을 부품 측(구매/유지)·슬롯·키별로 센다."""
    out: Counter = Counter()
    for r in requests_of(dump):
        if classify(r) != NOT_RECOMMENDABLE:
            continue
        for x in r["build"]["eligibility"].get("reasons") or []:
            for m in x.get("missing") or []:
                out[f"{'유지' if m.get('side') == 'owned' else '구매'}:{m['slot']}.{m['key']}"] += 1
    return dict(sorted(out.items()))


def enrichment_stats(dump: dict) -> dict:
    """사전 필터 보완(시도·채움·Pass 복귀)과 조합 보완(시도·채움·재실행)."""
    attempts = [a for r in requests_of(dump) for a in r.get("enrichment") or []]
    status = Counter(a["status"] for a in attempts)
    returned = sum(1 for a in attempts if a.get("returned_to_pass"))
    combo = [r["combo_enrichment"] for r in requests_of(dump) if r.get("combo_enrichment")]
    combo_status = Counter(a.get("status") for c in combo for a in c.get("attempts") or [])
    return {"prefilter_attempted": len(attempts), "prefilter_status": dict(sorted(status.items())),
            "prefilter_filled": status.get("filled", 0), "prefilter_returned": returned,
            "prefilter_fill_rate": (status.get("filled", 0) / len(attempts)) if attempts else None,
            "prefilter_return_rate": (returned / len(attempts)) if attempts else None,
            "combo_requests": len(combo), "combo_attempted": sum(c.get("attempted", 0) for c in combo),
            "combo_filled": sum(c.get("filled", 0) for c in combo), "combo_rerun": sum(1 for c in combo if c.get("rerun") is True),
            "combo_status": dict(sorted((k or "-", v) for k, v in combo_status.items()))}


def enrichment_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        e = enrichment_stats(d)
        rows.append([label, e["prefilter_attempted"], e["prefilter_filled"], pct(e["prefilter_filled"], e["prefilter_attempted"]),
                     e["prefilter_returned"], pct(e["prefilter_returned"], e["prefilter_attempted"]),
                     ", ".join(f"{k} {v}" for k, v in e["prefilter_status"].items()) or "—",
                     e["combo_requests"], e["combo_attempted"], e["combo_filled"], e["combo_rerun"]])
    return table(["단계", "사전 필터 시도", "채움", "채움률", "Pass 복귀", "복귀율(시도 대비)", "상태별", "조합 보완 요청 수",
                  "조합 시도", "조합 채움", "재실행"], rows)


def scenario_group_table(sc: dict, ids: tuple[str, ...]) -> str:
    rows = []
    for s in sc.get("scenarios") or []:
        if s["id"] in ids:
            for c in s["cases"]:
                rows.append([f"{s['id']} {s['title']}", c["name"], c["actual"].get("outcome"), "예" if not c["mismatch"] else "아니오"])
    recommendable = sum(1 for r in rows if r[2] == RECOMMENDABLE)
    return table(["시나리오", "경우", "결과", "기대와 일치"], rows) + f"\n\n정상 추천 {recommendable}/{len(rows)} ({pct(recommendable, len(rows))})"


# ── 여유 평가 ────────────────────────────────────────────────────────────────────

def margin_status_counts(dump: dict) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {}
    for r in built(dump):
        for name, item in ((r["build"].get("margins")) or {}).items():
            out.setdefault(name, Counter())[item["status"]] += 1
    return {name: dict(sorted(c.items())) for name, c in sorted(out.items())}


def margin_unavailable_reasons(dump: dict) -> dict[str, dict[str, int]]:
    """항목별 unavailable 의 사유·누락 키 분포(냉각은 사유만)."""
    out: dict[str, Counter] = {}
    for r in built(dump):
        for name, item in ((r["build"].get("margins")) or {}).items():
            if item["status"] != "unavailable":
                continue
            keys = item.get("missing") or [item.get("reason") or "-"]
            for k in keys:
                out.setdefault(name, Counter())[f"{item.get('reason') or '-'} / {k}" if item.get("missing") else k] += 1
    return {name: dict(sorted(c.items())) for name, c in sorted(out.items())}


def recompute_margin(name: str, item: dict) -> float | None:
    """덤프의 inputs 로 값을 다시 계산한다. 다시 계산할 수 없는 항목(요구 산정 기록·냉각)은 None."""
    inputs = item.get("inputs") or []
    by = lambda slot: [i["value"] for i in inputs if i["slot"] == slot]  # noqa: E731
    if name in ("size.gpu_length", "size.cooler_height", "size.psu_length"):
        case, actual = by("케이스"), [i["value"] for i in inputs if i["slot"] != "케이스"]
        return case[0] - actual[0] if case and actual else None
    if name == "size.gpu_slots":
        gpu, case = by("GPU"), by("케이스")
        return case[0] - math.ceil(gpu[0]) if gpu and case else None
    if name == "size.radiator":
        return float(len(item["fits_positions"])) if "fits_positions" in item else None
    if name == "power.compat_check":
        if item.get("scope") == "gpu_recommended_psu":
            psu = by("파워")
            rec = [i["value"] for i in inputs if i["key"] == "recommended_psu_w"]
            return psu[0] - rec[0] if psu and rec else None
        cpu, gpu, psu = by("CPU"), by("GPU"), by("파워")
        factor = item.get("factor")
        return psu[0] * factor - (cpu[0] + gpu[0]) if cpu and gpu and psu and factor else None
    if name == "power.total":
        psu = by("파워")
        others = [i["value"] for i in inputs if i["slot"] in ("CPU", "GPU")] + [i["value"] for i in inputs if i["slot"] is None]
        return psu[0] - math.fsum(others) if psu and others else None
    return None


def margin_reproduction(dump: dict) -> dict:
    checked = mismatches = recorded_only = 0
    bad: list[dict] = []
    for r in built(dump):
        for name, item in ((r["build"].get("margins")) or {}).items():
            if item["status"] != "available":
                continue
            value = recompute_margin(name, item)
            if value is None:
                recorded_only += 1
                continue
            checked += 1
            if abs(value - item["value"]) > TOL:
                mismatches += 1
                bad.append({"id": r["id"], "item": name, "dump": item["value"], "recomputed": value})
    return {"checked": checked, "mismatches": mismatches, "recorded_only": recorded_only, "list": bad[:20]}


def margin_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        for name, c in margin_status_counts(d).items():
            rows.append([label, name, c.get("available", 0), c.get("unavailable", 0), c.get("not_applicable", 0)])
    return table(["단계", "항목", "available", "unavailable", "not_applicable"], rows) if rows else "(여유 평가 필드가 있는 덤프 없음)"


# ── 시나리오 ─────────────────────────────────────────────────────────────────────

def _expected_base(key: str) -> str:
    for suffix in ("_min", "_has", "_sub"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def scenario_table(sc: dict) -> str:
    rows = []
    for s in sc.get("scenarios") or []:
        for c in s["cases"]:
            expected = json.dumps(c["expected"], ensure_ascii=False)
            actual = json.dumps({b: c["actual"].get(b) for b in dict.fromkeys(_expected_base(k) for k in c["expected"])}, ensure_ascii=False)
            rows.append([s["id"], s["title"], c["name"], f"`{expected}`", f"`{actual}`", "일치" if not c["mismatch"] else "**불일치**"])
    return table(["#", "시나리오", "경우", "기대", "실제", "결과"], rows)


def scenario_tests_table(sc: dict) -> str:
    return table(["#", "시나리오", "같은 성질을 검증하는 단위 테스트"],
                 [[s["id"], s["title"], "<br>".join(t.replace("tests/", "") for t in s["tests"])] for s in sc.get("scenarios") or []])


# ── 처리 시간 ────────────────────────────────────────────────────────────────────

def timing_table(dumps: list[tuple[str, dict]], note: str | None) -> str:
    rows = []
    for label, d in dumps:
        t = timing(d)
        rows.append([label, t["n"], fmt(t["mean"], 0), fmt(t["p50"], 0), fmt(t["p90"], 0), fmt(t["max"], 0)])
    text = table(["단계", "요청", "평균(ms)", "p50", "p90", "최대"], rows)
    return text + (f"\n\n측정 조건: {note}" if note else "")


# ── GPU·쿨러 미구매 규칙(computer-rules-v14) ─────────────────────────────────────────────────

LIGHT_PURPOSES = ("office", "study", "other")
BOX_COOLER_MAX_TDP_W = 65          # config/computer_verification_rules.yaml verification.box_cooler_max_tdp_w (D5)


def request_group(rec: dict) -> str:
    """요청이 속한 묶음 — 사무·학습·기타 새 PC(GPU·쿨러를 빼는 용도), 게임·창작 새 PC, 업그레이드."""
    values = rec.get("values") or {}
    if values.get("mode") == "upgrade":
        return "업그레이드"
    return "사무·학습·기타 새 PC" if values.get("purpose") in LIGHT_PURPOSES else "게임·창작 새 PC"


GROUPS = ("사무·학습·기타 새 PC", "게임·창작 새 PC", "업그레이드")


def omission_group_stats(dump: dict, group: str) -> dict:
    recs = [r for r in requests_of(dump) if request_group(r) == group]
    ok = [r for r in recs if classify(r) in (RECOMMENDABLE, UNJUDGED)]
    shares: dict[str, list[float]] = {}
    for r in ok:
        items = items_by_slot(r)
        total = math.fsum(i["price"] * (i.get("qty") or 1) for i in items.values())
        for slot, i in items.items():
            if total:
                shares.setdefault(slot, []).append(i["price"] * (i.get("qty") or 1) / total * 100)
    gpu_shares = shares.get("GPU", [])
    cpu_pass = [(r.get("hardfilter") or {}).get("CPU", {}).get("pass") for r in recs if "CPU" in (r.get("hardfilter") or {})]
    return {
        "n": len(recs), "recommendable": sum(1 for r in recs if classify(r) == RECOMMENDABLE),
        "not_recommendable": sum(1 for r in recs if classify(r) == NOT_RECOMMENDABLE),
        "shortage": sum(1 for r in recs if classify(r) == SHORTAGE), "error": sum(1 for r in recs if classify(r) == ERROR),
        "with_gpu": sum(1 for r in ok if "GPU" in items_by_slot(r)), "with_cooler": sum(1 for r in ok if "쿨러" in items_by_slot(r)),
        "built": len(ok), "used_pct_mean": mean([r.get("budget_used_pct") for r in ok]),
        "price_mean": mean([(r.get("build") or {}).get("totals", {}).get("price") for r in ok]),
        "gpu_share_median": percentile(gpu_shares, 50), "cpu_pass_mean": mean([c for c in cpu_pass if c is not None]),
        "cpu_pass_min": min((c for c in cpu_pass if c is not None), default=None),
        "shares": {slot: mean(v) for slot, v in sorted(shares.items())},
        "omitted_recorded": sum(1 for r in recs if r.get("omitted_slots")),
    }


def omission_group_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for group in GROUPS:
        for label, d in dumps:
            st = omission_group_stats(d, group)
            rows.append([group, label, st["n"], st["recommendable"], st["not_recommendable"], st["shortage"], st["error"],
                         f"{st['with_gpu']}/{st['built']}", f"{st['with_cooler']}/{st['built']}",
                         fmt(st["used_pct_mean"], 1), fmt(st["price_mean"], 0), fmt(st["gpu_share_median"], 1),
                         fmt(st["cpu_pass_mean"], 1), fmt(st["cpu_pass_min"], 0), st["omitted_recorded"]])
    return table(["묶음", "단계", "요청", "정상 추천", "부적격", "후보 부족", "오류", "GPU 품목 있음", "쿨러 품목 있음",
                  "예산 사용률 평균(%)", "평균 총가격(원)", "GPU 가격 비중 중앙값(%)", "CPU 사전 필터 Pass 평균", "CPU Pass 최소", "뺀 슬롯 기록 요청"], rows)


def share_table(dumps: list[tuple[str, dict]], group: str) -> str:
    slots = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]
    rows = []
    for label, d in dumps:
        shares = omission_group_stats(d, group)["shares"]
        rows.append([label] + [fmt(shares.get(slot), 1) if slot in shares else "—" for slot in slots])
    return table(["단계"] + [f"{s}(%)" for s in slots], rows)


def light_rule_check(dump: dict) -> dict:
    """GPU·쿨러를 빼는 용도(정상 추천)의 규칙 준수 — 요청이 기록한 omitted_slots 기준으로: 뺀 슬롯이 품목에 있는지, 선택 CPU 가 그 역할을
    할 수 있는지(내장 그래픽 O · 기본 쿨러 O · TDP 허용 이하), 부적격 사유. 쿨러를 다시 넣은 요청(저소음·소음 민감)은 따로 센다."""
    recs = [r for r in requests_of(dump) if request_group(r) == GROUPS[0]]
    built_ok = [r for r in recs if classify(r) == RECOMMENDABLE]
    leaked, bad_cpu, checked, cooler_kept, no_record = [], [], 0, 0, 0
    ox = lambda v: str(v or "").strip().upper()[:1]  # noqa: E731
    for r in built_ok:
        if "omitted_slots" not in r:
            no_record += 1                       # 옛 덤프 — 뺀 슬롯 기록이 없다
            continue
        omitted, items, cpu = r["omitted_slots"], items_by_slot(r), r.get("selected_cpu")
        leaked += [f"{r['id']}: {slot} 품목이 있음" for slot in omitted if slot in items]
        cooler_kept += int("쿨러" not in omitted)
        if cpu is None:
            continue
        checked += 1
        reasons = []
        if "GPU" in omitted and ox(cpu.get("integrated_graphics")) != "O":
            reasons.append("내장 그래픽 O 아님")
        if "쿨러" in omitted and (ox(cpu.get("cooler_included")) != "O" or cpu.get("tdp_w") is None or cpu["tdp_w"] > BOX_COOLER_MAX_TDP_W):
            reasons.append("기본 쿨러 O·TDP 허용 이하 아님")
        if reasons:
            bad_cpu.append(f"{r['id']}: {', '.join(reasons)}")
    not_rec = Counter(x["code"] for r in recs if classify(r) == NOT_RECOMMENDABLE
                      for x in (r.get("build") or {}).get("eligibility", {}).get("reasons") or [])
    set_fail = sum(1 for r in recs if (r.get("build") or {}).get("link_check", {}).get("set") == "fail")
    return {"n": len(recs), "recommendable": len(built_ok), "no_record": no_record, "leaked": leaked, "cooler_kept": cooler_kept,
            "cpu_checked": checked, "bad_cpu": bad_cpu, "not_recommendable": sum(1 for r in recs if classify(r) == NOT_RECOMMENDABLE),
            "not_recommendable_reasons": dict(not_rec), "set_fail": set_fail,
            "shortage": sum(1 for r in recs if classify(r) == SHORTAGE)}


def light_rule_table(dumps: list[tuple[str, dict]]) -> str:
    rows = []
    for label, d in dumps:
        c = light_rule_check(d)
        rows.append([label, c["n"], c["recommendable"], c["no_record"], len(c["leaked"]), c["cooler_kept"],
                     f"{c['cpu_checked']} 중 {len(c['bad_cpu'])}", c["not_recommendable"],
                     json.dumps(c["not_recommendable_reasons"], ensure_ascii=False), c["set_fail"], c["shortage"]])
    return table(["단계", "요청", "정상 추천", "뺀 슬롯 기록 없음(옛 덤프)", "뺀 슬롯이 품목에도 있는 요청", "쿨러를 다시 넣은 요청(저소음·소음 민감)",
                  "선택 CPU 조건 위반(검사 건수 중)", "부적격", "부적격 사유", "set 위반", "후보 부족"], rows)


def _fingerprint(rec: dict) -> tuple:
    b = rec.get("build") or {}
    items = tuple(sorted((i["slot"], i["product_key"], i.get("qty"), i.get("price")) for i in b.get("items") or []))
    return (classify(rec), items, (b.get("totals") or {}).get("price"), (rec.get("error") or {}).get("type"))


def unchanged_table(dumps: list[tuple[str, dict]]) -> str:
    """기준선(첫 덤프) 대비 같은 요청의 결과(분류·선택 부품·수량·가격·총가격)가 그대로인 비율 — 마지막 덤프만."""
    ref, (label, cur) = dumps[0][1], dumps[-1]
    ref_by_id = {r["id"]: r for r in requests_of(ref)}
    rows = []
    for group in GROUPS:
        pairs = [(ref_by_id[r["id"]], r) for r in requests_of(cur) if request_group(r) == group and r["id"] in ref_by_id]
        same = sum(1 for a, b in pairs if _fingerprint(a) == _fingerprint(b))
        diff = [b["id"] for a, b in pairs if _fingerprint(a) != _fingerprint(b)]
        rows.append([group, len(pairs), same, len(pairs) - same, ", ".join(diff[:6]) + (" …" if len(diff) > 6 else "") or "—"])
    return table(["묶음", "비교 요청", f"{dumps[0][0]} 결과와 같음", "다른 결과", "다른 요청(최대 6개)"], rows)


def omission_variant_table(dumps: list[tuple[str, dict]]) -> str:
    """사무·학습·기타 새 PC 를 (예산 × 쿨러 유지 여부)로 나눈 평균 — 뺀 슬롯 기록이 있는 덤프만 쿨러 유지 여부를 가른다(옛 덤프는 전부 '기록 없음')."""
    rows = []
    for label, d in dumps:
        buckets: dict[tuple, list[dict]] = {}
        for r in requests_of(d):
            if request_group(r) != GROUPS[0]:
                continue
            omitted = r.get("omitted_slots")
            kind = "기록 없음(8개 품목)" if omitted is None else ("GPU·쿨러 모두 뺌" if "쿨러" in omitted else "GPU만 뺌(쿨러 유지)")
            buckets.setdefault((kind, (r.get("values") or {}).get("budget_max")), []).append(r)
        for (kind, budget), recs in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            passes = [(r.get("hardfilter") or {}).get("CPU", {}).get("pass") for r in recs]
            passes = [x for x in passes if x is not None]
            ok = [r for r in recs if classify(r) == RECOMMENDABLE]
            rows.append([label, kind, budget, len(recs), len(ok), fmt(mean([r.get("budget_used_pct") for r in ok]), 1),
                         fmt(mean([(r.get("build") or {}).get("totals", {}).get("price") for r in ok]), 0),
                         fmt(mean(passes), 1), fmt(min(passes, default=None), 0), fmt(max(passes, default=None), 0)])
    return table(["단계", "구성", "예산(원)", "요청", "정상 추천", "예산 사용률 평균(%)", "평균 총가격(원)",
                  "CPU Pass 평균", "최소", "최대"], rows)


def omission_section(dumps: list[tuple[str, dict]]) -> list[str]:
    final_label = dumps[-1][0]
    return ["## GPU·쿨러 미구매 규칙 (computer-rules-v14)",
            "### 묶음별 결과", omission_group_table(dumps),
            "### 사무·학습·기타 새 PC — 예산·쿨러 유지 여부별 평균", omission_variant_table(dumps),
            f"### 사무·학습·기타 새 PC — 정상 추천 결과의 총가격 대비 부품 비중(%, 평균)", share_table(dumps, GROUPS[0]),
            f"### 게임·창작 새 PC — 부품 비중(%, 평균)", share_table(dumps, GROUPS[1]),
            "### 사무·학습·기타 새 PC — 규칙 준수", light_rule_table(dumps),
            *(["\n".join(f"- {final_label} {x}" for x in (light_rule_check(dumps[-1][1])["bad_cpu"] + light_rule_check(dumps[-1][1])["leaked"])[:20])]
              if (light_rule_check(dumps[-1][1])["bad_cpu"] or light_rule_check(dumps[-1][1])["leaked"]) else []),
            f"### {dumps[0][0]} 대비 같은 요청의 결과가 그대로인가 — {final_label}", unchanged_table(dumps)]


# ── 조립 ─────────────────────────────────────────────────────────────────────────

def render(dumps: list[tuple[str, dict]], scenarios: dict | None, timing_note: str | None) -> str:
    final_label, final = dumps[-1]
    parts = ["## 단계별 요약", stage_table(dumps),
             f"## 슬롯별 Pass·Pending·Fail — {dumps[0][0]}", slot_table(dumps[0][1]),
             f"## 슬롯별 Pass·Pending·Fail — {final_label}", slot_table(final),
             f"### Pending 사유 — {final_label}", reason_table(final, "pending"), f"### Fail 사유 — {final_label}", reason_table(final, "fail"),
             f"### Pending 사유 — {dumps[0][0]}", reason_table(dumps[0][1], "pending"),
             "## 부적격·후보 부족"]
    parts.append("\n".join(f"- {label}: 부적격 사유 {json.dumps(ineligible_reasons(d), ensure_ascii=False)} · "
                           f"후보 부족 슬롯 {json.dumps(shortage_slots(d), ensure_ascii=False)}" for label, d in dumps))
    parts += ["## 선택 부품 변화(기준선 대비 슬롯별 변경 수)", selection_table(dumps),
              "### 직전 단계 대비 선택 변화", adjacent_table(dumps),
              "## 총가격·예산 사용률", budget_table(dumps),
              "### 같은 요청 집합(최종 정상 추천 요청)만의 비교", budget_same_requests(dumps),
              "### 예산을 늘려도 총가격이 줄지 않는가(성능 우선, noise=0)", budget_monotonic_table(dumps[:1] + dumps[-1:]),
              "## 조합 탐색 카운터", counter_table(dumps),
              "## RAM 구성", ram_table(dumps),
              "## 3-B 순위(상위 5 안 선택의 평균 순위 · 괄호: 상위 5 밖 선택 수, 전체 풀 평균 순위는 새 덤프만)", rank_table(dumps),
              "## 저소음 요청의 정숙성 근거 반영", noise_table(dumps),
              f"### 우선순위별 정숙성 요청 가중 변화 — {final_label}", noise_delta_table(final),
              "## 필수 조건 위반", violation_table(dumps)]
    parts += ["\n".join(f"- {final_label} {v['id']}: {v['kind']} {v['detail']}" for v in violations(final)["list"][:20])
              or f"{final_label}: 위반 목록 없음"]
    parts += [f"## 부적격 결과의 누락 키(구매·유지 부품별) — {final_label}",
              table(["부품:슬롯.키", "요청 수"], [[k, n] for k, n in missing_by_part(final).items()]) if missing_by_part(final) else "(없음)",
              "## 정보 보완", enrichment_table(dumps)]
    if scenarios:
        parts += ["### 실제 연결(GPU 보조 전원)·사용자 필수 RAM 속도별 결과(고정 시나리오)", scenario_group_table(scenarios, ("13", "14"))]
    parts += ["## 전력·크기 여유 항목별 상태", margin_table(dumps[-1:] if len(dumps) else dumps)]
    unavailable = margin_unavailable_reasons(final)
    parts += [f"### unavailable 사유·누락 키 — {final_label}",
              table(["항목", "사유 / 키", "수"], [[n, k, v] for n, c in unavailable.items() for k, v in c.items()]) if unavailable else "(없음)"]
    repro = margin_reproduction(final)
    parts += [f"### 값 재현 — {final_label}", f"입력·단위·계산식으로 다시 계산: {repro['checked']}건 검사, 불일치 {repro['mismatches']}건, "
              f"기록만 있는 항목(요구 산정 등) {repro['recorded_only']}건"]
    if repro["list"]:
        parts.append("\n".join(f"- {x['id']} {x['item']}: 덤프 {x['dump']} / 재계산 {x['recomputed']}" for x in repro["list"]))
    if any(request_group(r) == GROUPS[0] for r in requests_of(final)):
        parts += omission_section(dumps)
    parts += ["## 요청당 처리 시간", timing_table(dumps, timing_note)]
    if scenarios:
        parts += ["## 고정 시나리오", scenario_table(scenarios), "### 시나리오와 단위 테스트", scenario_tests_table(scenarios)]
    return "\n\n".join(parts) + "\n"


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="append", required=True, help="라벨=경로 (순서대로, 첫째=기준선, 마지막=최종)")
    ap.add_argument("--scenarios")
    ap.add_argument("--timing-note")
    args = ap.parse_args()
    dumps = []
    for spec in args.dump:
        label, _, path = spec.partition("=")
        dumps.append((label, load(path)))
    sys.stdout.write(render(dumps, load(args.scenarios) if args.scenarios else None, args.timing_note))


if __name__ == "__main__":
    main()
