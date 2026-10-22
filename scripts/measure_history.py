"""이전 견적 확인(히스토리·리포트·목록) 시간 — 대화가 길어질수록 어떻게 느려지는지 (2026-10-07). 로컬 서버만, 실제 LLM.

  uv run python scripts/measure_history.py --sizes 0,5,15,30 --out outputs/history_latency.json

크기 K = 조건 대화 K번 + 부품 직접 교체 K번 + 긴 문장(500자, 입력 한도) 1번. 확정 뒤 같은 견적을 다음 순서로 잰다.
  히스토리 첫 호출(요약 LLM) → 같은 견적 두 번째 호출(캐시) → 리포트 → 목록(견적이 쌓인 계정)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

LONG_TEXT = ("게임도 하고 영상 편집도 해서 조용하고 성능 좋은 컴퓨터가 필요해요. " * 20)[:500]
BUDGETS = [1_500_000, 1_800_000, 2_000_000, 2_400_000]


def timed(fn):
    start = time.perf_counter()
    response = fn()
    return response, time.perf_counter() - start


def build_confirmed(http: httpx.Client, k: int) -> tuple[str, dict]:
    sid = http.post("/session").json()["list_id"]
    http.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    http.post(f"/session/{sid}/message", json={"text": "게임용 PC 예산 200만원 성능 위주"})
    for i in range(k):
        http.post(f"/session/{sid}/message", json={"text": f"예산을 {BUDGETS[i % len(BUDGETS)] // 10_000}만원으로 바꿔줘"})
    if k:
        http.post(f"/session/{sid}/message", json={"text": LONG_TEXT})
    assert http.post(f"/session/{sid}/recommend").status_code == 202
    data: dict = {}
    for _ in range(600):
        data = http.get(f"/session/{sid}/result").json()
        if data.get("status") in ("done", "failed"):
            break
        time.sleep(0.5)
    assert data["status"] == "done", data
    swaps = 0
    slots = [i for i in data["items"] if i["selected"] and i["slot"] in ("쿨러", "케이스", "저장장치", "RAM", "파워")]
    for n in range(k):
        item = slots[n % len(slots)] if slots else None
        if item is None:
            break
        alts = http.get(f"/session/{sid}/items/{item['item_id']}/alternatives").json().get("items", [])
        pick = next((a for a in alts if not a.get("current")), None)
        if pick and http.post(f"/session/{sid}/items/{item['item_id']}/swap", json={"candidate_id": pick["candidate_id"]}).status_code == 200:
            swaps += 1
    assert http.post(f"/lists/{sid}/confirm", json={"name": f"히스토리 {k}"}).status_code == 200
    return sid, {"swaps": swaps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--sizes", default="0,5,15,30")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if urlparse(args.base).hostname not in ("127.0.0.1", "localhost"):
        print("로컬 서버만 측정한다")
        return 2
    http = httpx.Client(base_url=args.base, timeout=300.0)
    r = http.post("/auth/signup", json={"email": f"latency-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8],
                                        "display_name": "시간측정", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text

    rows = []
    print(f"{'K':>3} {'교체':>4} {'단계':>4} {'사건':>4} {'히스토리1(LLM)':>14} {'히스토리2(캐시)':>14} {'리포트':>7} {'목록':>7}")
    for k in [int(x) for x in args.sizes.split(",")]:
        sid, info = build_confirmed(http, k)
        first, t1 = timed(lambda: http.get(f"/lists/{sid}/history"))
        _, t2 = timed(lambda: http.get(f"/lists/{sid}/history"))
        _, t3 = timed(lambda: http.get(f"/lists/{sid}/report"))
        _, t4 = timed(lambda: http.get("/lists"))
        body = first.json() if first.status_code == 200 else {}
        row = {"k": k, **info, "steps": len(body.get("steps", [])), "events": len(body.get("events", [])), "history_first": t1,
               "history_cached": t2, "report": t3, "lists": t4, "status": first.status_code,
               "summary_len": len((body.get("summary") or {}).get("text", ""))}
        rows.append(row)
        print(f"{k:>3} {info['swaps']:>4} {row['steps']:>4} {row['events']:>4} {t1:>13.2f}s {t2:>13.2f}s {t3:>6.2f}s {t4:>6.2f}s  (HTTP {first.status_code})", flush=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
