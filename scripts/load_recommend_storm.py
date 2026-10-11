"""추천을 동시에 N건 돌릴 때 풀 고갈·500 이 없는지, 그 사이 일반 요청이 막히지 않는지 — 실서버, 실제 LLM(설명 문장), 로컬만 (2026-10-08).

  uv run python scripts/load_recommend_storm.py --users 30

각 사용자: 세션 → 카테고리 → 질문 답 3개(LLM 없음) → 추천 → 결과가 보일 때까지 폴링 → 설명 문장이 다 채워질 때까지 폴링.
같은 시간에 GET /lists·GET /session/{id} 지연을 계속 잰다.
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
    c = httpx.Client(base_url=base, timeout=180.0)
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
    codes: Counter = Counter()
    lock = threading.Lock()

    def count(label: str, r: httpx.Response):
        with lock:
            codes[(label, r.status_code)] += 1
        return r

    def retrying(label: str, send):
        """서버가 응답 없이 연결을 끊으면(RemoteProtocolError 등) 세어 두고 한 번 다시 보낸다 — 끊김 횟수가 결과의 일부다."""
        try:
            return count(label, send())
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError):
            with lock:
                codes[(label, "연결 끊김")] += 1
            return count(label, send())

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

    def flow(i: int):
        c = signup(args.base)        # 연결을 사용 직전에 만든다 — 오래 놀린 연결은 서버가 먼저 닫는다(keep-alive)
        sid = c.post("/session").json()["list_id"]
        c.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
        for qid, value in (("q_purpose", "게임"), ("q_budget_max", 2_000_000), ("q_priority", "성능 우선")):
            retrying("answer", lambda: c.post(f"/session/{sid}/answer", json={"question_id": qid, "selected": [value]}))
        start = time.perf_counter()
        r = retrying("recommend", lambda: c.post(f"/session/{sid}/recommend"))
        if r.status_code != 202:
            return None
        shown = ready = None
        while time.perf_counter() - start < 240:
            data = retrying("result", lambda: c.get(f"/session/{sid}/result")).json()
            now = time.perf_counter() - start
            if shown is None and data.get("status") in ("done", "failed"):
                shown = now
                if data["status"] == "failed":
                    break
            if shown is not None and (data.get("explanation") or {}).get("status") == "ready":
                ready = now
                break
            time.sleep(0.5)
        return shown, ready

    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.users) as pool:
        results = list(pool.map(flow, range(args.users)))
    wall = time.perf_counter() - t0
    stop.set()
    watch.join()

    shown = sorted(r[0] for r in results if r and r[0] is not None)
    ready = sorted(r[1] for r in results if r and r[1] is not None)
    print(f"추천 {args.users}건 동시 → 전체 {wall:.1f}s")
    print("  HTTP 상태:", {f"{k[0]} {k[1]}": v for k, v in sorted(codes.items(), key=str)})
    if shown:
        print(f"  구성이 보이기까지: 중앙 {statistics.median(shown):.1f}s 최대 {max(shown):.1f}s ({len(shown)}건)")
    if ready:
        print(f"  설명까지: 중앙 {statistics.median(ready):.1f}s 최대 {max(ready):.1f}s ({len(ready)}건)")
    times = sorted(t for t, _ in light)
    print(f"일반 요청 {len(light)}건: 상태 {dict(Counter(c for _, c in light))}, 중앙 {statistics.median(times):.2f}s "
          f"p95 {times[max(0, int(len(times) * 0.95) - 1)]:.2f}s 최대 {max(times):.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
