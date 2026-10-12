"""추천 엔진 정책 변경 전후 비교용 덤프 — 고정 요청 목록을 현재 엔진 [2]→[4]+세트 검증 루프로 돌려 JSON 으로 저장한다.

`execute_recommendation`(src/services/recommendation_service.py)의 엔진 부분만 따라 하고 DB 에는 아무것도 쓰지 않는다
(트랜잭션 READ ONLY, run_id 없음). 설명 문장(LLM) 단계는 돌지 않는다. 같은 스크립트를 정책 변경 뒤에 다시 돌려 diff 한다
(docs/추천엔진_수정_구현계획_20261012.md §4 0·7단계).

    MOCK_MODE=1 CATALOG_SOURCE=db PYTHONPATH=. uv run python scripts/engine_policy_compare.py --out <path.json> [--limit N]

MOCK_MODE=1 을 환경변수로 직접 줘야 한다(.env 는 읽지도 출력하지도 않는다). 개발 DB 를 읽기만 한다.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("MOCK_MODE") != "1":
    sys.exit("MOCK_MODE=1 환경변수를 명시해야 실행합니다(설명 문장 단계가 LLM 을 부를 수 있습니다).")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOP_N = 5
PURPOSES = ["game", "office", "study", "creation", "other"]
PRIORITIES = [None, "performance", "value", "quiet"]
BUDGETS = [1_000_000, 2_000_000, 3_500_000]

# 업그레이드 요청의 현재 사양 — 개발 카탈로그에 실제 있는 제품명(owned_parts._match_catalog 로 대응됨).
_UPGRADE_GPU_ONLY_SPECS = {
    "CPU": "AMD Ryzen 5 7600", "GPU": "NVIDIA GeForce RTX 3060 12GB", "RAM": "삼성전자 DDR5-5600 (16GB)",
    "메인보드": "ASUS Prime B650M-A II", "저장장치": "Crucial P310 2230", "파워": "Corsair RM750e ATX 3.1",
    "케이스": "안텍 (Antec) FLUX Pro", "쿨러": "Deepcool AG400 G2",
}
_UPGRADE_RAM_BOARD_SPECS = {
    "CPU": "AMD Ryzen 7 5800X", "GPU": "NVIDIA GeForce RTX 4060 Ti", "RAM": "삼성전자 DDR4-3200 (16GB)",
    "메인보드": "ASUS PRIME A520M-A II", "저장장치": "Crucial P310 2230", "파워": "Corsair RM750e ATX 3.1",
    "케이스": "안텍 (Antec) FLUX Pro", "쿨러": "Deepcool AG400 G2",
}


def build_requests() -> list[dict]:
    """고정 순서의 요청 목록. values 는 조건 키(category 는 실행 시 붙인다). priority 미지정이면 키를 뺀다."""
    reqs: list[dict] = []

    def add(rid: str, **values):
        reqs.append({"id": rid, "values": {"mode": "build", **values}})

    for purpose in PURPOSES:
        for priority in PRIORITIES:
            for noise in (False, True):
                for budget in BUDGETS:
                    v = {"purpose": purpose, "budget_max": budget, "noise_sensitive": noise}
                    if priority:
                        v["priority"] = priority
                    rid = f"{purpose}|{priority or 'none'}|noise={int(noise)}|{budget}"
                    add(rid, **v)
    add("extra|game|QHD_165|3500000", purpose="game", budget_max=3_500_000, resolution="QHD_165")
    add("extra|game|4K|3500000", purpose="game", budget_max=3_500_000, resolution="4K")
    add("extra|game|cyberpunk|2000000", purpose="game", budget_max=2_000_000, games=["사이버펑크"])
    add("extra|game|4K|1500000", purpose="game", budget_max=1_500_000, resolution="4K")
    reqs.append({"id": "upgrade|GPU|2000000", "values": {
        "mode": "upgrade", "purpose": "game", "budget_max": 2_000_000, "upgrade_parts": ["GPU"],
        "current_specs": dict(_UPGRADE_GPU_ONLY_SPECS)}})
    reqs.append({"id": "upgrade|RAM+메인보드|1000000", "values": {
        "mode": "upgrade", "purpose": "game", "budget_max": 1_000_000, "upgrade_parts": ["RAM", "메인보드"],
        "current_specs": dict(_UPGRADE_RAM_BOARD_SPECS)}})
    return reqs


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def _item(i) -> dict:
    d = {"slot": i.slot, "product_key": i.product_key, "name": i.name, "price": i.price,
         "score": round(i.score, 4), "perf_tier": i.perf_tier}
    for k in ("qty", "unit_price"):
        if getattr(i, k, None) is not None:
            d[k] = getattr(i, k)
    return d


def _margins_summary(margins) -> dict | None:
    """조합 여유는 항목별 status·value·사유(없으면 생략)만 덤프한다 — 입력·출처 전체는 서비스 trace 에 있다."""
    if not margins:
        return None
    from src.engine.build_margins import margin_items
    return {name: {k: item[k] for k in ("status", "value", "reason") if item.get(k) is not None or k == "status"}
            | ({"missing": [f"{m['slot']}.{m['key']}" for m in item["missing"]]} if item.get("missing") else {})
            for name, item in margin_items(margins).items()}


def _build(b) -> dict:
    return {
        "items": sorted((_item(i) for i in b.items), key=lambda d: d["slot"]),
        "totals": b.totals, "budget": b.budget, "link_check": dict(sorted(b.link_check.items())),
        "alternatives": dict(sorted(b.alternatives.items())),
        "eligibility": getattr(b, "eligibility", None), "margins": _margins_summary(getattr(b, "margins", None)),
    }


def _verification(v) -> list[dict]:
    out = []
    for t in v.targets:
        out.append({
            "subject": t.subject, "confidence": t.confidence, "passed": t.passed,
            "eligible": getattr(t, "eligible", None), "blocking": getattr(t, "blocking", None),
            "issues": sorted(({"axis": i.axis, "judge": i.judge, "penalty": i.penalty,
                               "blocking": getattr(i, "blocking", None)} for i in t.issues),
                             key=lambda d: (d["axis"], d["judge"], d["penalty"])),
        })
    return out


def _error(exc: BaseException) -> dict:
    attrs = {}
    for k, val in vars(exc).items() if hasattr(exc, "__dict__") else []:
        if not k.startswith("_"):
            try:
                json.dumps(val)
                attrs[k] = val
            except TypeError:
                attrs[k] = repr(val)
    return {"type": type(exc).__name__, "message": str(exc), "attrs": attrs}


def run_one(conn, req: dict, by_slot_master: dict, cat_def: dict, category: str) -> dict:
    from src.engine import feasibility as feasibility_engine
    from src.engine import research_loop, stage2_requirement, stage3a_hardfilter, stage3c_verify
    from src.engine.slots import slots_from_conditions
    from src.services.review_ranking import rank_with_review_aspects

    noop = lambda _m: None  # noqa: E731
    values = {"category": category, **req["values"]}
    slots = slots_from_conditions(category, cat_def, values)
    rec: dict = {"id": req["id"], "values": req["values"], "assumed_keys": sorted(slots.assumed_keys)}
    started = time.perf_counter()
    try:
        spec = stage2_requirement.run(slots, cat_def, noop)
        by_slot = {s: [c.model_copy(deep=True) for c in cands] for s, cands in by_slot_master.items()}
        current_tiers: dict = {}
        if spec.mode == "upgrade":
            from src.engine.owned_parts import constrain_targets, current_part_tiers, owned_for_conditions
            from src.services.live_spec_lookup import cached_for_kept_parts
            spec.owned = owned_for_conditions(values, by_slot, spec.targets, cat_def.get("slot_structure", []))
            cached_for_kept_parts(conn, spec.owned, values.get("current_specs"))   # 저장소 읽기만(검색 없음)
            constrain_targets(spec)
            current_tiers = current_part_tiers(values.get("current_specs"), by_slot, spec.targets)
            for slot, info in current_tiers.items():
                spec.targets[slot]["perf_tier_min"] = max(spec.targets[slot].get("perf_tier_min", 0), info["tier"])
            rec["owned"] = {s: {"source": o.get("source"), "specs": o.get("specs")} for s, o in sorted(spec.owned.items())}
            rec["current_tiers"] = {s: {"tier": i["tier"], "keys": sorted(i["keys"])} for s, i in sorted(current_tiers.items())}
        rec["targets"] = sorted(spec.targets)
        feasibility = feasibility_engine.assess(spec, by_slot)
        spec.budget["feasibility"] = feasibility["level"]
        spec.budget["feasibility_detail"] = feasibility
        rec["feasibility"] = {"level": feasibility.get("level"), "estimated_min": feasibility.get("estimated_min")}
        hf = stage3a_hardfilter.run(spec, by_slot, noop)
        rec["hardfilter"] = {s: dict(sorted(st.items())) for s, st in sorted(hf.stats.items())}
        rank, _profiles = rank_with_review_aspects(hf, spec, slots, noop, conn=conn, catalog_source="db")
        rec["rank"] = {
            "weights_used": dict(sorted(rank.weights_used.items())),
            "top": {s: [{"product_key": c["product_key"], "score": round(c.get("score", 0.0), 4)}
                        for c in (info.get("ranked") or [])[:TOP_N]]
                    for s, info in sorted(rank.slots.items())},
        }
        already_owned = {(slot, key) for slot, info in current_tiers.items() for key in info["keys"]}
        rules = stage2_requirement.load_computer_rules()
        compat_rules = rules["verification"]
        impact_slots = frozenset(rules["ranking"].get("impact_slots", []))

        def _verify(b, _i):
            chosen = research_loop.resolve_chosen(rank, b)
            return stage3c_verify.verify_build(b, category, noop, chosen=chosen, spec=spec, rules=compat_rules)

        def _choose_exclusion(b, v):
            chosen = research_loop.resolve_chosen(rank, b)
            return research_loop.rule_based_exclusion(b, v, chosen, spec, compat_rules, impact_slots=impact_slots)

        build, verification, rounds = research_loop.run_set_with_research(
            rank, spec, noop, verify=_verify, choose_exclusion=_choose_exclusion,
            base_exclude=frozenset(already_owned))
        b = _build(build)
        budget = b["budget"]
        mx, used = budget.get("max"), budget.get("used")
        rec["build"] = b
        rec["budget_used_pct"] = round(used / mx * 100, 2) if mx and used is not None else None
        rec["verification"] = _verification(verification)
        rec["research"] = {
            "rounds": len(rounds), "stop_reason": rounds[-1].stop_reason if rounds else None,
            "excluded": [r.excluded for r in rounds if r.excluded],
            "round_confidence": [[t.confidence for t in r.verification.targets] for r in rounds],
        }
    except Exception as exc:  # noqa: BLE001 — 정책 변경 뒤 새 예외가 나와도 덤프는 계속한다
        rec["error"] = _error(exc)
    rec["wall_ms"] = round((time.perf_counter() - started) * 1000)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    from src.categories import load_category
    from src.db import get_conn
    from src.engine.stage2_requirement import load_computer_rules
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    category, cat_def = "computer", load_category("computer")
    reqs = build_requests()[: args.limit]
    t0 = time.perf_counter()
    with get_conn() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        master = load_candidates_by_slot_from_db(conn)
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "rule_set_version": load_computer_rules().get("rule_set_version"),
            "catalog_counts": {s: len(c) for s, c in master.items()},
            "requests": [],
        }
        for n, req in enumerate(reqs, 1):
            rec = run_one(conn, req, master, cat_def, category)
            out["requests"].append(rec)
            print(f"[{n}/{len(reqs)}] {req['id']} {rec['wall_ms']}ms" + (" ERROR " + rec["error"]["type"] if "error" in rec else ""),
                  file=sys.stderr)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(reqs)} requests, {time.perf_counter() - t0:.1f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
