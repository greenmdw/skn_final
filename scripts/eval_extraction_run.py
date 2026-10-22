#!/usr/bin/env python3
"""사용기 분석 추출 정확도 평가 — 모델 추출 실행(기획 8장). 선정한 글마다 `analyze()` 를 N회 부른다.

DB 에 **쓰지 않는다**(운영 근거 테이블을 건드리지 않음). 글은 `peripheral_post_source.load_post_input` 으로 읽는다.
결과는 `data/eval_extraction/model_runs/<글번호>.json` 에 raw(확인 전 모델 항목 전부 + 확인 상태)와 confirmed 를 함께 저장한다.
모델 실제 호출이다: MOCK_MODE=0, OPENAI_API_KEY, LLM_MODEL, PERIPHERAL_POST_AGENT=1 필요.

    python scripts/eval_extraction_run.py --reps 3 --workers 5
    python scripts/eval_extraction_run.py --only A1-1,F1 --reps 1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import peripheral_post_agent as agent        # noqa: E402
from src.db import get_conn                                  # noqa: E402
from src.repo import peripheral_post_source as source        # noqa: E402

OUT_DIR = ROOT / "data" / "eval_extraction"
RUNS_DIR = OUT_DIR / "model_runs"


def _dump_item(analyzed) -> dict:
    item = analyzed.item
    return {
        "sentence": item.sentence, "product_index": item.product_index, "attribute": item.attribute,
        "direction": item.direction, "side": item.side, "evaluated_in": list(item.evaluated_in or []),
        "months_used": item.months_used, "experienced": item.experienced, "comparison": item.comparison,
        "spec_statement": item.spec_statement, "confidence": getattr(item, "confidence", None),
        "status": analyzed.status, "reasons": list(analyzed.reasons or []),
    }


def run_once(post_id: str, rep: int) -> dict:
    t0 = time.time()
    with get_conn() as conn:
        post = source.load_post_input(conn, post_id)
    run = agent.analyze(post)
    a = run.analysis
    au = a.author
    return {
        "rep": rep, "seconds": round(time.time() - t0, 1), "truncated": run.truncated,
        "analyzable": a.analyzable, "skip_reason": a.skip_reason,
        "author": {"purposes": au.purposes, "situations": au.situations, "hand_size": au.hand_size, "hand_cm": au.hand_cm},
        "items": [_dump_item(i) for i in a.items],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--only", help="글 번호 쉼표 목록(없으면 manifest 전체)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not agent.available():
        print("모델을 부를 수 없다: PERIPHERAL_POST_AGENT=1, MOCK_MODE=0, OPENAI_API_KEY, LLM_MODEL 필요", file=sys.stderr)
        return 2

    manifest = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    posts = [p for p in manifest["posts"] if p.get("post_id")]
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        posts = [p for p in posts if p["post_id_ext"] in keep]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {p["post_id_ext"]: {"post_id": p["post_id"], "post_id_ext": p["post_id_ext"],
                                                   "content_hash": p.get("content_hash"), "runs": []} for p in posts}
    jobs = [(p["post_id_ext"], p["post_id"], r) for p in posts for r in range(1, args.reps + 1)]
    print(f"글 {len(posts)}편 × {args.reps}회 = 모델 호출 {len(jobs)}회, 동시 {args.workers}", flush=True)
    done = errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_once, pid, rep): (ext, rep) for ext, pid, rep in jobs}
        for fut in as_completed(futures):
            ext, rep = futures[fut]
            try:
                results[ext]["runs"].append(fut.result())
            except Exception as exc:  # noqa: BLE001
                errors += 1
                results[ext]["runs"].append({"rep": rep, "error": f"{type(exc).__name__}: {exc}"[:300]})
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} (오류 {errors})", flush=True)
    for ext, rec in results.items():
        rec["runs"].sort(key=lambda r: r["rep"])
        (RUNS_DIR / f"{ext}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {RUNS_DIR} (호출 {len(jobs)}회, 오류 {errors})")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
