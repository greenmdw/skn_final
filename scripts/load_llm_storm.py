"""LLM 대기 요청이 몰릴 때 LLM 이 필요 없는 요청이 막히지 않는지 — 실서버, 실제 LLM, 로컬만 (2026-10-08).

  uv run python scripts/load_llm_storm.py --users 30

조건 대화(LLM) 요청을 --users 개 동시에 보내면서, 같은 시간에 GET /lists·GET /session/{id} 지연을 계속 잰다.
기대: LLM 요청은 성공하거나 503(llm_busy)로 정리되고, LLM 이 필요 없는 요청은 계속 빠르며 500 이 없다.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx


def signup(base: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=120.0)
    r = c.post("/auth/signup", json={"email": f"storm-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8],
                                     "display_name": "폭주시험", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=30)
    args = ap.parse_args()
    if urlparse(args.base).hostname not in ("127.0.0.1", "localhost"):
        print("로컬 서버만")
        return 2

    probe = signup(args.base)
    probe_sid = probe.post("/session").json()["list_id"]
    clients = [signup(args.base) for _ in range(args.users)]
    sessions = []
    for c in clients:
        sid = c.post("/session").json()["list_id"]
        c.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
        sessions.append(sid)

    stop = threading.Event()
    light: list[tuple[float, int]] = []

    def watcher():
        while not stop.is_set():
            for path in ("/lists", f"/session/{probe_sid}"):
                t = time.perf_counter()
                code = probe.get(path).status_code
                light.append((time.perf_counter() - t, code))
            time.sleep(0.2)

    watch = threading.Thread(target=watcher)
    watch.start()

    def talk(i: int):
        t = time.perf_counter()
        r = clients[i].post(f"/session/{sessions[i]}/message", json={"text": "150만원으로 엘든링 돌릴 조용한 PC 맞춰줘"})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        code = (body.get("error") or {}).get("code") if r.status_code >= 400 else None
        return r.status_code, code, time.perf_counter() - t

    start = time.perf_counter()
    with ThreadPoolExecutor(args.users) as pool:
        results = list(pool.map(talk, range(args.users)))
    wall = time.perf_counter() - start
    stop.set()
    watch.join()

    print(f"LLM 대화 {args.users}건 동시 → 전체 {wall:.1f}s")
    print("  결과:", dict(Counter((s, c) for s, c, _ in results)))
    ok = sorted(t for s, _, t in results if s == 200)
    if ok:
        print(f"  성공 응답 시간: 중앙 {statistics.median(ok):.1f}s 최대 {max(ok):.1f}s")
    times = sorted(t for t, _ in light)
    print(f"LLM 이 필요 없는 요청 {len(light)}건: 상태 {dict(Counter(c for _, c in light))}, 중앙 {statistics.median(times):.2f}s "
          f"p95 {times[max(0, int(len(times) * 0.95) - 1)]:.2f}s 최대 {max(times):.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
