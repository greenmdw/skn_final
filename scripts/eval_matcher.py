#!/usr/bin/env python3
"""
의미 대조 채점 — `MATCH_MODE=llm` 이 라벨을 얼마나 재현하는가.

    python scripts/eval_matcher.py                # 전체
    python scripts/eval_matcher.py --limit 40     # 주장당 40건만 (비용 확인용)
    python scripts/eval_matcher.py --claim ssd-write

**합성 리뷰의 정답 라벨이 있어서 채점이 가능하다.** 라벨이 공짜라는 것이
[`decisions/0008`](../docs/decisions/0008-리뷰-소스-기본값을-합성으로-둔다.md)
에서 합성을 고른 이유였는데, 그 공짜 라벨의 진짜 값이 이것이다 — 실데이터에는
정답이 없어서 대조가 맞는지 잴 방법이 없다.

[무엇을 보는가]
건별 정확도(정밀도·재현율)와 **판정이 바뀌는지**를 함께 낸다. 뒤가 더 중요하다 —
건별로 몇 개 틀려도 임계값을 넘지 않으면 화면에 나가는 판정은 같고, 반대로 몇
건만 틀려도 표본이 얇은 주장(SSD)에서는 판정이 뒤집힌다.

`OPENAI_API_KEY` 가 필요하다. 없으면 라벨끼리 비교해 채점기 자체가 도는지만 본다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine.match import LabelMatcher, gather  # noqa: E402
from app.engine.packs.pc import pack               # noqa: E402
from app.engine.verify import verdict_from         # noqa: E402


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(truth, got) -> dict:
    """건별 혼동 행렬. `bears_on` 과 `contradicts` 를 따로 센다."""
    t = {j.review_id: j for j in truth}
    out = {"bears": [0, 0, 0], "contra": [0, 0, 0], "n": 0, "quote_ok": 0, "quoted": 0}
    for j in got:
        ref = t.get(j.review_id)
        if ref is None:
            continue
        out["n"] += 1
        for key, a, b in (("bears", ref.bears_on, j.bears_on),
                          ("contra", ref.contradicts, j.contradicts)):
            if a and b:
                out[key][0] += 1          # tp
            elif b and not a:
                out[key][1] += 1          # fp
            elif a and not b:
                out[key][2] += 1          # fn
        if j.quote:
            out["quoted"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="주장당 대조할 리뷰 수 상한")
    ap.add_argument("--claim", default="", help="이 주장 하나만")
    args = ap.parse_args()

    have_key = bool(os.environ.get("OPENAI_API_KEY"))
    if have_key:
        from app.engine.match import LLMMatcher

        candidate = LLMMatcher()
        if args.limit:
            candidate.max_reviews = args.limit
    else:
        print("⚠ OPENAI_API_KEY 가 없습니다 — 라벨끼리 비교합니다(채점기 자기 점검).\n")
        candidate = LabelMatcher()

    truth_matcher = LabelMatcher()
    source = pack.review_source()
    threshold = source.threshold

    totals = {"bears": [0, 0, 0], "contra": [0, 0, 0]}
    flipped = 0
    rows = 0

    for part in pack.catalog():
        claims = pack.claims_for(part["code"])
        if not claims:
            continue
        reviews = source.fetch(part["code"])
        for claim in claims:
            if args.claim and claim.claim_id != args.claim:
                continue
            rows += 1
            kept = [r for r in reviews if r.risk < threshold]
            if args.limit:
                kept = kept[: args.limit]

            truth = truth_matcher.match(claim, kept)
            got = candidate.match(claim, kept)
            s = score(truth, got)
            for k in ("bears", "contra"):
                for i in range(3):
                    totals[k][i] += s[k][i]

            ev_t = gather(claim, kept, truth_matcher, threshold)
            ev_g = gather(claim, kept, candidate, threshold)
            vt, vg = verdict_from(ev_t), verdict_from(ev_g)
            same = "" if vt is vg else "  ← 판정이 바뀐다"
            if vt is not vg:
                flipped += 1

            bp, br, bf = prf(*s["bears"])
            cp, cr, cf = prf(*s["contra"])
            print(f"[{claim.claim_id}] {claim.text}")
            print(f"  닿음   P {bp:.2f} R {br:.2f} F {bf:.2f}   "
                  f"(닿는다 판정 {ev_g.relevant} / 정답 {ev_t.relevant})")
            print(f"  어긋남 P {cp:.2f} R {cr:.2f} F {cf:.2f}   "
                  f"(어긋난다 판정 {ev_g.hits} / 정답 {ev_t.hits})")
            print(f"  판정   {vt.value} → {vg.value}{same}")
            print(f"  인용   {s['quoted']}/{s['n']}건에 원문 인용이 붙었다\n")

    bp, br, bf = prf(*totals["bears"])
    cp, cr, cf = prf(*totals["contra"])
    print("─" * 62)
    print(f"전체  닿음 F {bf:.3f} (P {bp:.3f} R {br:.3f})  ·  "
          f"어긋남 F {cf:.3f} (P {cp:.3f} R {cr:.3f})")
    print(f"판정이 바뀐 주장: {flipped} / {rows}")
    if not have_key:
        print("\n※ 라벨끼리 비교한 결과라 전부 1.000 이 정상입니다. "
              "실제 채점은 OPENAI_API_KEY 를 넣고 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
