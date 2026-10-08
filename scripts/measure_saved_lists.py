"""저장한 견적이 많은 계정의 화면 로딩 시간 (2026-10-07). 로컬 서버만, 실제 LLM(추천 설명이 뒤에서 돈다).

  uv run python scripts/measure_saved_lists.py --stages 10,30,60,100 --out outputs/saved_lists_latency.json

한 계정에 확정 견적을 단계마다 늘려 가며(10→30→60→100개) 프론트가 화면을 여는 순서 그대로 잰다.
  · 사이드바: GET /lists  (전량 반환)
  · 저장한 견적 화면: 확정 목록마다 GET /lists/{id}/report 를 한꺼번에(브라우저는 호스트당 동시 6개까지)
  · 대화 열기: GET /session/{id}, GET /session/{id}/result
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

SEED_THREADS = 8


def signup(base: str) -> httpx.Client:
    http = httpx.Client(base_url=base, timeout=300.0)
    r = http.post("/auth/signup", json={"email": f"latency-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8],
                                        "display_name": "시간측정", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return http


def make_confirmed(http: httpx.Client, n: int) -> str:
    sid = http.post("/session").json()["list_id"]
    http.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    http.post(f"/session/{sid}/message", json={"text": f"게임용 PC 예산 {150 + n % 10 * 10}만원 {'성능' if n % 2 else '가성비'} 위주"})
    rec = http.post(f"/session/{sid}/recommend")
    assert rec.status_code == 202, f"recommend HTTP {rec.status_code} {rec.text[:200]}"
    for _ in range(240):
        r = http.get(f"/session/{sid}/result")
        if r.status_code == 200 and r.json().get("status") in ("done", "failed"):
            break
        if r.status_code not in (200, 404):
            raise RuntimeError(f"result HTTP {r.status_code} {r.text[:120]}")
        time.sleep(0.5)
    r = http.post(f"/lists/{sid}/confirm", json={"name": f"저장 견적 {n}"})
    assert r.status_code == 200, r.text
    return sid


def timed(fn):
    start = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - start


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--stages", default="10,30,60,100")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if urlparse(args.base).hostname not in ("127.0.0.1", "localhost"):
        print("로컬 서버만 측정한다")
        return 2
    http = signup(args.base)
    cookies = http.cookies
    rows, ids = [], []
    print(f"{'견적수':>5} {'/lists':>8} {'응답KB':>7} {'리포트 하나(중앙/최대)':>20} {'리포트 전부 동시6':>16} {'대화 열기':>9}")
    for target in [int(x) for x in args.stages.split(",")]:
        missing = list(range(len(ids), target))
        clients = [httpx.Client(base_url=args.base, timeout=300.0, cookies=cookies) for _ in range(SEED_THREADS)]
        with ThreadPoolExecutor(SEED_THREADS) as pool:
            ids += list(pool.map(lambda n: make_confirmed(clients[n % SEED_THREADS], n), missing))

        lists_resp, t_lists = timed(lambda: http.get("/lists"))
        size_kb = len(lists_resp.content) / 1024

        def one_report(sid):
            _, t = timed(lambda: http.get(f"/lists/{sid}/report"))
            return t

        singles = sorted(one_report(sid) for sid in ids[:10])
        shared = [httpx.Client(base_url=args.base, timeout=300.0, cookies=cookies) for _ in range(6)]

        def report_on(pair):
            i, sid = pair
            return shared[i % 6].get(f"/lists/{sid}/report").status_code

        _, t_all = timed(lambda: list(ThreadPoolExecutor(6).map(report_on, list(enumerate(ids)))))
        sid = ids[len(ids) // 2]
        _, t_open = timed(lambda: (http.get(f"/session/{sid}"), http.get(f"/session/{sid}/result")))
        row = {"count": target, "lists": t_lists, "lists_kb": size_kb, "report_median": singles[len(singles) // 2], "report_max": singles[-1],
               "reports_all": t_all, "open": t_open}
        rows.append(row)
        print(f"{target:>5} {t_lists:>7.2f}s {size_kb:>6.0f} {row['report_median']:>10.2f}/{row['report_max']:<8.2f}s {t_all:>15.2f}s {t_open:>8.2f}s", flush=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
