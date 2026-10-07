"""실서버 응답 시간 측정 — 사용자가 "결과가 나올 때까지" 기다리는 시간을 단계별로 반복 측정한다 (2026-10-07).

실행 중인 서버(MOCK_MODE=0, 실제 LLM)에 사용자 흐름 그대로 요청을 보내 단계마다 걸린 시간을 잰다. 실제 OpenAI 호출이 들어가므로
**비용이 든다**(1회 반복당 LLM·검색 약 10~15회). 로컬 서버(127.0.0.1/localhost)만 허용한다 — 임시 계정을 만들기 때문이다.

  uv run python scripts/measure_latency.py --runs 3 --out outputs/latency.json

측정 항목은 두 종류다.
  · 서버 시간: 요청을 보내고 응답이 올 때까지(대화·검색·확정·조회 등)
  · 사용자 대기 시간: 추천을 시작해서 "구성이 보이는" 때까지, "추천 이유 문장까지 다 채워지는" 때까지
LLM 시간은 모델·네트워크 상태에 따라 흔들리므로 중앙값(med)과 최댓값(max)을 함께 본다. 429(요청 한도)는 기다렸다 다시 보내고
기다린 시간은 측정에서 뺀다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

RATE_WAIT_SECONDS = 62
OBSCURE_PRODUCTS = [          # 카탈로그에 없는 실제 제품 — 저장소에 없어서 실제 웹 검색이 돈다(반복마다 다른 제품)
    "Lian Li Galahad II Trinity 240", "Team T-Force Delta RGB DDR5-6400 32GB", "Cooler Master MasterLiquid 360L Core",
    "Kingston Fury Beast DDR5-6000 32GB", "be quiet! Pure Loop 2 FX 280",
]
QUOTE_SPECS = {"CPU": "AMD Ryzen 7 9800X3D", "GPU": "NVIDIA GeForce RTX 5070 Ti", "메인보드": "ASRock B650 PG Lighting",
               "RAM": "삼성전자 DDR5-5600 (16GB)", "저장장치": "Samsung 990 PRO 1TB", "파워": "Corsair RM850e",
               "케이스": "NZXT H5 Flow", "쿨러": "Thermalright Peerless Assassin 120 SE"}
QUOTE_TEXT = "\n".join(f"{k}: {v}" for k, v in QUOTE_SPECS.items())


class Probe:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=180.0)
        self.samples: dict[str, list[float]] = {}
        self.notes: list[str] = []
        self.rate_waits = 0

    def timed(self, label: str, send, *, expect: tuple[int, ...] = (200, 201, 202)):
        """send() → httpx.Response. 429 면 기다렸다 다시(기다린 시간은 뺀다). 성공한 한 번의 시간만 기록한다."""
        for _ in range(3):
            start = time.perf_counter()
            response = send()
            elapsed = time.perf_counter() - start
            if response.status_code == 429:
                self.rate_waits += 1
                print(f"   (429 — {RATE_WAIT_SECONDS}초 기다림)", flush=True)
                time.sleep(RATE_WAIT_SECONDS)
                continue
            if response.status_code not in expect:
                self.notes.append(f"{label}: HTTP {response.status_code} {response.text[:120]}")
                return response, None
            self.samples.setdefault(label, []).append(elapsed)
            print(f"   {label:34} {elapsed:6.1f}s", flush=True)
            return response, elapsed
        self.notes.append(f"{label}: 429 가 계속됨")
        return None, None

    def record(self, label: str, seconds: float) -> None:
        self.samples.setdefault(label, []).append(seconds)
        print(f"   {label:34} {seconds:6.1f}s", flush=True)


def one_run(p: Probe, index: int) -> None:
    http = p.http
    print(f"\n── 반복 {index + 1} ──", flush=True)

    # 1. 새 견적 흐름
    r, _ = p.timed("세션 생성", lambda: http.post("/session"))
    if r is None or r.status_code != 200:
        return
    sid = r.json()["list_id"]
    http.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    p.timed("조건 대화 한 턴(LLM)", lambda: http.post(f"/session/{sid}/message", json={"text": "150만원으로 엘든링 돌릴 조용한 PC 맞춰줘"}))

    start = time.perf_counter()
    accepted = http.post(f"/session/{sid}/recommend")
    if accepted.status_code != 202:
        p.notes.append(f"추천 시작 실패: {accepted.status_code} {accepted.text[:120]}")
        return
    shown = ready = None
    deadline = start + 240
    while time.perf_counter() < deadline:
        data = http.get(f"/session/{sid}/result").json()
        now = time.perf_counter() - start
        if shown is None and data.get("status") in ("done", "failed"):
            shown = now
            if data.get("status") == "failed":
                p.notes.append(f"추천 실패: {data.get('error')}")
                break
        if shown is not None:
            pending = [i for i in data.get("items", []) if (i.get("reason") or {}).get("status") != "ready"]
            if (data.get("explanation") or {}).get("status") == "ready" and not pending:
                ready = now
                break
        time.sleep(0.5)
    if shown is not None:
        p.record("추천: 구성이 보이기까지", shown)
    if ready is not None:
        p.record("추천: 설명 문장까지 다 채워지기까지", ready)
    elif shown is not None:
        p.notes.append("추천 설명이 240초 안에 다 채워지지 않음")

    p.timed("결과 화면 대화: 부품 교체(LLM)", lambda: http.post(f"/session/{sid}/result-message", json={"text": "쿨러를 더 저렴한 걸로 바꿔줘"}))
    p.timed("결과 화면 대화: 질문(LLM)", lambda: http.post(f"/session/{sid}/result-message", json={"text": "이 구성이 왜 괜찮아?"}))
    p.timed("리스트 확정", lambda: http.post(f"/lists/{sid}/confirm", json={"name": f"시간 측정 {index + 1}"}))
    p.timed("리포트 조회", lambda: http.get(f"/lists/{sid}/report"))
    p.timed("목록 조회", lambda: http.get("/lists"))

    # 2. 주변기기
    p.timed("주변기기 추천(4종)", lambda: http.post(f"/session/{http.post('/session').json()['list_id']}/peripherals/recommend",
                                               json={"kinds": ["monitor", "keyboard", "mouse", "speaker"]}))

    # 3. 받은 견적 점검
    r, _ = p.timed("견적 점검 만들기(분석 포함)", lambda: http.post("/pc/reviews", json={
        "current_specs": QUOTE_SPECS, "conditions": {"purpose": "game", "resolution": "QHD_165", "budget_max": 3_000_000}}))
    if r is not None and r.status_code == 201:
        lid = r.json()["list_id"]
        p.timed("견적 점검 되묻기: 호환(LLM)", lambda: http.post(f"/pc/reviews/{lid}/messages", json={"text": "호환은 문제없어?"}))
        p.timed("견적 점검 되묻기: 제품 비교(LLM)", lambda: http.post(f"/pc/reviews/{lid}/messages", json={"text": "RTX 5080이랑 비교해줘"}))
        p.timed("견적 점검 되묻기: 시리즈 되묻기(규칙)", lambda: http.post(f"/pc/reviews/{lid}/messages", json={"text": "라이젠 9000이랑 비교해줘"}))

    # 4. 견적 초안(텍스트) + 실시간 검색
    product = OBSCURE_PRODUCTS[index % len(OBSCURE_PRODUCTS)]
    r, _ = p.timed("견적 초안 만들기(텍스트)", lambda: http.post("/pc/review-drafts", data={"text": f"쿨러: {product}\n" + QUOTE_TEXT}))
    if r is not None and r.status_code == 201:
        draft = r.json()
        p.timed("견적 초안 분석", lambda: http.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={}))
        item = next((i for i in draft["items"] if product.split()[0].lower() in i["normalized_name"].lower()), None)
        if item and item["match_status"] != "confirmed":
            url = f"/pc/review-drafts/{draft['draft_id']}/items/{item['id']}/live-lookup"
            p.timed("실시간 검색(저장소에 없음, 웹 검색)", lambda: http.post(url))
            p.timed("실시간 검색(저장소에 있음)", lambda: http.post(url))
        else:
            p.notes.append(f"실시간 검색 건너뜀: '{product}' 가 항목으로 읽히지 않았거나 카탈로그에 확정 대응됨")


def summarize(samples: dict[str, list[float]]) -> list[dict]:
    rows = []
    for label, values in samples.items():
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        rows.append({"label": label, "n": len(values), "min": min(values), "median": statistics.median(values),
                     "p95": p95, "max": max(values)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    host = urlparse(args.base).hostname
    if host not in ("127.0.0.1", "localhost"):
        print("로컬 서버만 측정한다(임시 계정을 만든다).")
        return 2

    probe = Probe(args.base)
    signup = probe.http.post("/auth/signup", json={
        "email": f"latency-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8], "display_name": "시간측정",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    if signup.status_code != 201:
        print("임시 계정을 만들지 못했다:", signup.status_code, signup.text[:150])
        return 1
    health = probe.http.get("/health")
    print(f"서버 {args.base} (health {health.status_code}), 반복 {args.runs}회", flush=True)

    for i in range(args.runs):
        try:
            one_run(probe, i)
        except Exception as exc:  # noqa: BLE001 — 한 반복의 실패가 나머지를 막지 않게
            probe.notes.append(f"반복 {i + 1} 예외: {type(exc).__name__}: {exc}")

    rows = summarize(probe.samples)
    print("\n" + "=" * 92)
    print(f"{'단계':38} {'n':>2} {'최소':>7} {'중앙값':>7} {'p95':>7} {'최대':>7}   (초)")
    print("-" * 92)
    for row in rows:
        print(f"{row['label']:38} {row['n']:>2} {row['min']:7.1f} {row['median']:7.1f} {row['p95']:7.1f} {row['max']:7.1f}")
    for note in probe.notes:
        print("※", note)
    if probe.rate_waits:
        print(f"※ 요청 한도(429)로 기다린 횟수 {probe.rate_waits}회 — 기다린 시간은 위 표에 포함되지 않음")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"), "runs": args.runs, "base": args.base,
                                   "rows": rows, "samples": probe.samples, "notes": probe.notes}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
