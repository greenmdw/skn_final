"""추천 전체 시간 매트릭스 + 동시 사용 측정 — 실서버, 실제 LLM (2026-10-07). 로컬 서버만. 비용이 든다.

  uv run python scripts/measure_latency_matrix.py --out outputs/latency_matrix.json [--concurrency 4]

1) 용도 × 예산 × 우선순위 조합마다 조건 대화 → 추천 → "구성이 보이기까지" / "설명까지 다 채워지기까지" / 결과 대화 한 턴
2) 주변기기 추천(종류별·4종), 확정·리포트
3) 동시 N명이 같은 흐름을 동시에 돌릴 때의 추천 시간(느려지는 정도)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

PURPOSES = {"game": "게임용", "office": "사무용", "creation": "영상 편집용"}
BUDGETS = [900_000, 1_800_000, 3_000_000]
PRIORITIES = {"value": "가성비 위주", "performance": "성능 위주"}


def client(base: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=300.0)
    r = c.post("/auth/signup", json={"email": f"latency-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8],
                                     "display_name": "시간측정", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def recommend_flow(http: httpx.Client, purpose_word: str, budget: int, priority_word: str) -> dict:
    out: dict = {}
    sid = http.post("/session").json()["list_id"]
    http.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    t = time.perf_counter()
    state = http.post(f"/session/{sid}/message", json={"text": f"{purpose_word} PC 예산 {budget // 10_000}만원 {priority_word}"}).json()
    out["조건 대화"] = time.perf_counter() - t
    if not state.get("can_recommend"):
        out["note"] = "조건이 덜 채워져 추천 못 함"
        return out
    start = time.perf_counter()
    if http.post(f"/session/{sid}/recommend").status_code != 202:
        out["note"] = "추천 시작 실패"
        return out
    shown = ready = None
    while time.perf_counter() - start < 300:
        data = http.get(f"/session/{sid}/result").json()
        now = time.perf_counter() - start
        if shown is None and data.get("status") in ("done", "failed"):
            shown = now
            if data["status"] == "failed":
                out["note"] = f"추천 실패 {(data.get('error') or {}).get('code')}"
                break
        if shown is not None:
            pending = [i for i in data.get("items", []) if (i.get("reason") or {}).get("status") != "ready"]
            if (data.get("explanation") or {}).get("status") == "ready" and not pending:
                ready = now
                break
        time.sleep(0.5)
    out["추천: 구성이 보이기까지"] = shown
    out["추천: 설명까지"] = ready
    if shown is not None and "note" not in out:
        t = time.perf_counter()
        http.post(f"/session/{sid}/result-message", json={"text": "이 구성에서 제일 약한 부품이 뭐야?"})
        out["결과 대화 한 턴"] = time.perf_counter() - t
        t = time.perf_counter()
        http.post(f"/lists/{sid}/confirm", json={"name": "시간 측정"})
        out["확정"] = time.perf_counter() - t
        t = time.perf_counter()
        http.get(f"/lists/{sid}/report")
        out["리포트"] = time.perf_counter() - t
    return out


def stats(values: list[float]) -> str:
    if not values:
        return "-"
    return f"n={len(values)} 중앙 {statistics.median(values):5.1f} 최대 {max(values):5.1f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if urlparse(args.base).hostname not in ("127.0.0.1", "localhost"):
        print("로컬 서버만 측정한다")
        return 2

    http = client(args.base)
    rows: list[dict] = []
    print("── 1. 용도 × 예산 × 우선순위 ──", flush=True)
    for p, pw in PURPOSES.items():
        for b in BUDGETS:
            for pr, prw in PRIORITIES.items():
                r = recommend_flow(http, pw, b, prw)
                r.update(purpose=p, budget=b, priority=pr)
                rows.append(r)
                print(f"  {p:8} {b:>9,} {pr:12} 구성 {r.get('추천: 구성이 보이기까지') or 0:5.1f}s  설명까지 {r.get('추천: 설명까지') or 0:5.1f}s  "
                      f"대화 {r.get('결과 대화 한 턴') or 0:5.1f}s  {r.get('note', '')}", flush=True)

    print("── 2. 주변기기 ──", flush=True)
    periph: dict[str, float] = {}
    for label, kinds in [("모니터", ["monitor"]), ("키보드", ["keyboard"]), ("마우스", ["mouse"]), ("스피커", ["speaker"]),
                         ("4종", ["monitor", "keyboard", "mouse", "speaker"])]:
        sid = http.post("/session").json()["list_id"]
        t = time.perf_counter()
        http.post(f"/session/{sid}/peripherals/recommend", json={"kinds": kinds})
        periph[label] = time.perf_counter() - t
        print(f"  {label:6} {periph[label]:5.2f}s", flush=True)

    print(f"── 3. 동시 {args.concurrency}명 추천 ──", flush=True)
    clients = [client(args.base) for _ in range(args.concurrency)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.concurrency) as pool:
        conc = list(pool.map(lambda c: recommend_flow(c, "게임용", 1_800_000, "가성비 위주"), clients))
    wall = time.perf_counter() - t0
    for i, r in enumerate(conc):
        print(f"  사용자 {i + 1}: 구성 {r.get('추천: 구성이 보이기까지') or 0:5.1f}s  설명까지 {r.get('추천: 설명까지') or 0:5.1f}s  {r.get('note', '')}")
    print(f"  전체 벽시계 {wall:.1f}s", flush=True)

    print("\n" + "=" * 70)
    for key in ("조건 대화", "추천: 구성이 보이기까지", "추천: 설명까지", "결과 대화 한 턴", "확정", "리포트"):
        print(f"{key:26} {stats([r[key] for r in rows if r.get(key) is not None])}")
    for key in ("추천: 구성이 보이기까지", "추천: 설명까지"):
        print(f"동시 {args.concurrency}명 {key:20} {stats([r[key] for r in conc if r.get(key) is not None])}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"), "matrix": rows, "peripherals": periph,
                                   "concurrent": conc, "concurrent_wall": wall}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
