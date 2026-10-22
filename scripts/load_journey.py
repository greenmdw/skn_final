"""사용자 여정 부하테스트 — 게스트 가상 사용자 N명이 정해진 시간 동안 같은 여정을 반복한다 (2026-10-10). 실제 LLM 을 쓰는 서버면 비용이 든다.

  uv run python scripts/load_journey.py http://서버주소 --stages 5,10,20,30 --stage-seconds 180 --out outputs/load/aws_20261010.json

여정(계정 없이): 세션 → 조건 대화(LLM) → 추천 → 결과 폴링(구성·설명) → 결과 대화(LLM) → 대안·교체 → 주변기기 → 견적 점검 만들기 → 견적 되묻기(LLM).
단계(stage)마다 동시 사용자 수를 올리고, 단계 사이에 잠시 쉰다. 사용자는 단계가 끝날 때까지 여정을 반복하고, 끝난 시각에 진행 중이던 여정은 마저 끝낸다.
프론트처럼 503(llm_busy)은 Retry-After 만큼 기다려 최대 2번, GET 의 503(service_busy)도 같은 방식으로 다시 보낸다 — 다시 보내기 전 503 은 "혼잡 신호"로 따로 센다.
429(IP별 요청 한도)는 오류가 아니라 "한도 걸림"으로 센다 — 서버의 한도(PC_CHECK_LIMIT_PER_MIN 등)를 풀어야 서버 한계가 보인다.
안전장치: 서버 오류(5xx, 503 제외) 비율이 단계 중 25%를 넘으면 그 단계를 멈추고 다음 단계로 가지 않는다. --max-llm-calls 를 넘으면 새 여정을 시작하지 않는다.
테스트용 게스트 세션·견적 점검이 대상 DB 에 쌓인다. 계정을 만들거나 로그인하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

QUOTE = {"CPU": "AMD Ryzen 7 9800X3D", "GPU": "NVIDIA GeForce RTX 5070 Ti", "메인보드": "ASRock B650 PG Lighting", "RAM": "삼성전자 DDR5-5600 (16GB)"}
QUOTE_TEXT = "\n".join(f"{k}: {v}" for k, v in QUOTE.items())        # 받은 견적 점검(재설계 후)은 초안 만들기(인식) → 분석 → 대화 순서다
QUOTE_CONDITIONS = {"purpose": "game", "resolution": "QHD_165", "budget_max": 3_000_000}      # 분석에 용도가 필수다
LLM_STEPS = {"조건 대화(LLM)", "결과 대화(LLM)", "견적 점검 만들기(인식, LLM)", "견적 되묻기(LLM)", "추천 설명(LLM, 백그라운드)"}
lock = threading.Lock()


class Stats:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.status: Counter = Counter()          # (step, 최종 상태 코드)
        self.signals: Counter = Counter()         # 재시도 전 혼잡 신호(503 코드), 429
        self.errors: Counter = Counter()          # 최종 실패 원인
        self.journeys_ok = self.journeys_failed = 0
        self.llm_calls = 0

    def merge_into_total(self, other: "Stats") -> None:
        for k, v in other.samples.items():
            self.samples[k] += v
        self.status.update(other.status)
        self.signals.update(other.signals)
        self.errors.update(other.errors)
        self.journeys_ok += other.journeys_ok
        self.journeys_failed += other.journeys_failed
        self.llm_calls += other.llm_calls


class Abort(Exception):
    pass


def send(http: httpx.Client, stats: Stats, step: str, method: str, path: str, **kw) -> httpx.Response:
    """한 단계 요청. 혼잡 503 은 프론트처럼 최대 2번 다시 보낸다. 시간은 재시도 대기까지 합쳐 사용자가 기다린 시간이다."""
    started = time.perf_counter()
    response = None
    for attempt in range(3):
        try:
            response = http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            with lock:
                stats.errors[f"{step}: 연결 오류 {type(exc).__name__}"] += 1
                stats.status[(step, "연결오류")] += 1
            raise Abort(step)
        if response.status_code == 503:
            code = ""
            try:
                code = (response.json().get("error") or {}).get("code", "")
            except ValueError:
                pass
            with lock:
                stats.signals[f"503 {code or '?'}"] += 1
            retryable = code == "llm_busy" or (code == "service_busy" and method == "GET")
            if retryable and attempt < 2:
                time.sleep(float(response.headers.get("retry-after", "3")))
                continue
        break
    elapsed = time.perf_counter() - started
    with lock:
        stats.samples[step].append(elapsed)
        stats.status[(step, response.status_code)] += 1
        if step in LLM_STEPS:
            stats.llm_calls += 1
        if response.status_code == 429:
            stats.signals["429 요청 한도"] += 1
    return response


def check(stats: Stats, step: str, response: httpx.Response, ok=(200, 201, 202)):
    if response.status_code in ok:
        return
    with lock:
        if response.status_code == 429:
            stats.errors[f"{step}: 429(요청 한도에 걸림)"] += 1
        else:
            stats.errors[f"{step}: HTTP {response.status_code}"] += 1
    raise Abort(step)


def journey(base: str, stats: Stats, quote: bool, think: float) -> None:
    with httpx.Client(base_url=base, timeout=150.0) as http:
        r = send(http, stats, "세션 생성", "POST", "/session"); check(stats, "세션 생성", r)
        sid = r.json()["list_id"]
        r = send(http, stats, "카테고리", "POST", f"/session/{sid}/category", json={"category": "computer", "mode": "build"}); check(stats, "카테고리", r)
        r = send(http, stats, "조건 대화(LLM)", "POST", f"/session/{sid}/message", json={"text": "150만원으로 엘든링 돌릴 조용한 PC 맞춰줘"}); check(stats, "조건 대화(LLM)", r)
        if not r.json().get("can_recommend"):
            for qid, val in (("q_purpose", "게임"), ("q_budget_max", 1_500_000), ("q_priority", "가성비")):
                r = send(http, stats, "질문 답변", "POST", f"/session/{sid}/answer", json={"question_id": qid, "selected": [val]}); check(stats, "질문 답변", r)
        time.sleep(random.uniform(0.3, think))
        t0 = time.perf_counter()
        r = send(http, stats, "추천 시작", "POST", f"/session/{sid}/recommend", json={}); check(stats, "추천 시작", r)
        shown = ready = None
        data: dict = {}
        while time.perf_counter() - t0 < 150:
            r = send(http, stats, "결과 폴링", "GET", f"/session/{sid}/result")
            if r.status_code != 200:
                check(stats, "결과 폴링", r)
            data = r.json()
            now = time.perf_counter() - t0
            if shown is None and data["status"] in ("done", "failed"):
                shown = now
                with lock:
                    stats.samples["추천: 구성이 보이기까지"].append(now)
                if data["status"] == "failed":
                    with lock:
                        stats.errors["추천 실패(failed)"] += 1
                    raise Abort("추천")
            if shown is not None and data["explanation"]["status"] != "pending":
                ready = now
                with lock:
                    stats.samples["추천 설명(LLM, 백그라운드)"].append(now)
                    stats.llm_calls += 1
                    if data["explanation"]["status"] != "ready":
                        stats.errors["추천 설명이 failed(규칙 문장으로 대체)"] += 1
                break
            time.sleep(0.7)
        if shown is None:
            with lock:
                stats.errors["추천 구성이 150초 안에 안 나옴"] += 1
            raise Abort("추천")
        if ready is None:
            with lock:
                stats.errors["추천 설명이 150초 안에 안 끝남(pending)"] += 1
        time.sleep(random.uniform(0.3, think))
        r = send(http, stats, "결과 대화(LLM)", "POST", f"/session/{sid}/result-message", json={"text": "이 구성이 왜 괜찮아?"}); check(stats, "결과 대화(LLM)", r)
        items = [i for i in data["items"] if i.get("selected")]
        item = next((i for i in items if i["slot"] in ("쿨러", "케이스", "저장장치")), items[0])
        r = send(http, stats, "대안 조회", "GET", f"/session/{sid}/items/{item['item_id']}/alternatives"); check(stats, "대안 조회", r)
        other = next((a for a in r.json().get("items", []) if not a.get("current")), None)
        if other:
            r = send(http, stats, "부품 교체(버튼)", "POST", f"/session/{sid}/items/{item['item_id']}/swap", json={"candidate_id": other["candidate_id"]}); check(stats, "부품 교체(버튼)", r)
        r = send(http, stats, "목록 조회", "GET", "/lists"); check(stats, "목록 조회", r)
        r = send(http, stats, "주변기기 추천", "POST", f"/session/{sid}/peripherals/recommend", json={"kinds": ["monitor", "keyboard", "mouse", "speaker"]}); check(stats, "주변기기 추천", r)
        if quote:
            r = send(http, stats, "견적 점검 만들기(인식, LLM)", "POST", "/pc/review-drafts",
                     data={"text": QUOTE_TEXT, "conditions": json.dumps(QUOTE_CONDITIONS)}); check(stats, "견적 점검 만들기(인식, LLM)", r)
            did = r.json()["draft_id"]
            r = send(http, stats, "견적 점검 분석", "POST", f"/pc/review-drafts/{did}/analysis", json={}); check(stats, "견적 점검 분석", r)
            r = send(http, stats, "견적 되묻기(LLM)", "POST", f"/pc/reviews/{did}/messages", json={"text": "호환은 문제없어?"}); check(stats, "견적 되묻기(LLM)", r)


def run_stage(base: str, users: int, seconds: int, quote: bool, think: float, llm_budget: list[int], max_llm: int) -> Stats:
    stats = Stats()
    deadline = time.perf_counter() + seconds

    def user(_i: int) -> None:
        while time.perf_counter() < deadline and llm_budget[0] < max_llm:
            try:
                journey(base, stats, quote, think)
                with lock:
                    stats.journeys_ok += 1
            except Abort:
                with lock:
                    stats.journeys_failed += 1
            except Exception as exc:  # noqa: BLE001
                with lock:
                    stats.journeys_failed += 1
                    stats.errors[f"예외 {type(exc).__name__}"] += 1
            with lock:
                llm_budget[0] += 0
            time.sleep(random.uniform(0.5, think))

    started = time.perf_counter()
    with ThreadPoolExecutor(users) as pool:
        futures = [pool.submit(user, i) for i in range(users)]
        for f in futures:
            f.result()
    stats.wall = time.perf_counter() - started          # type: ignore[attr-defined]
    return stats


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(label: str, stats: Stats) -> dict:
    total_req = sum(stats.status.values())
    server_err = sum(v for (step, code), v in stats.status.items() if isinstance(code, int) and code >= 500)
    final_503 = sum(v for (step, code), v in stats.status.items() if code == 503)
    row = {"stage": label, "journeys_ok": stats.journeys_ok, "journeys_failed": stats.journeys_failed, "requests": total_req,
           "final_5xx": server_err, "final_503": final_503, "final_5xx_excluding_503": server_err - final_503,
           "congestion_signals": dict(stats.signals), "errors": dict(stats.errors), "llm_calls": stats.llm_calls,
           "seconds": round(getattr(stats, "wall", 0), 1),
           "steps": {s: {"n": len(v), "median": round(statistics.median(v), 2), "p95": round(pct(v, 0.95), 2), "p99": round(pct(v, 0.99), 2), "max": round(max(v), 2)}
                     for s, v in sorted(stats.samples.items())}}
    return row


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, encoding="utf-8",
                              cwd=Path(__file__).resolve().parent.parent).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("--stages", default="5,10,20,30", help="단계별 동시 사용자 수(쉼표)")
    ap.add_argument("--stage-seconds", type=int, default=180)
    ap.add_argument("--cooldown", type=int, default=20)
    ap.add_argument("--think", type=float, default=3.0, help="사용자가 화면을 보는 시간(최대 초, 0.3~이 값 사이 무작위)")
    ap.add_argument("--no-quote", action="store_true", help="견적 점검 단계(/pc/*, IP별 한도 있음) 제외")
    ap.add_argument("--max-llm-calls", type=int, default=2500, help="모델 호출(추정) 합이 이를 넘으면 새 여정을 시작하지 않는다")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    base = args.base.rstrip("/")
    health = httpx.get(f"{base}/health", timeout=10)
    print(f"대상 {base} (health {health.status_code}), 단계 {args.stages}, 단계당 {args.stage_seconds}s, 모델 호출 상한 {args.max_llm_calls}", flush=True)
    rows = []
    llm_total = [0]
    for users in [int(x) for x in args.stages.split(",")]:
        print(f"\n── 동시 {users}명 시작 {datetime.now():%H:%M:%S} ──", flush=True)
        stats = run_stage(base, users, args.stage_seconds, not args.no_quote, args.think, llm_total, args.max_llm_calls)
        llm_total[0] += stats.llm_calls
        row = summarize(f"{users}명", stats)
        rows.append(row)
        print(f"  여정 성공 {row['journeys_ok']} / 실패 {row['journeys_failed']}, 요청 {row['requests']}, 최종 5xx(503 제외) {row['final_5xx_excluding_503']}, 최종 503 {row['final_503']}, "
              f"혼잡 신호 {row['congestion_signals']}, 모델 호출(추정) {row['llm_calls']}", flush=True)
        for s, v in row["steps"].items():
            print(f"    {s:28} n={v['n']:>4} 중앙 {v['median']:6.2f}s p95 {v['p95']:6.2f}s 최대 {v['max']:6.2f}s")
        if row["errors"]:
            print("  오류:", row["errors"])
        bad = row["final_5xx_excluding_503"] / max(1, row["requests"])
        if bad > 0.25:
            print(f"  ※ 서버 오류 비율 {bad:.0%} — 안전장치로 여기서 멈춘다.")
            break
        if llm_total[0] >= args.max_llm_calls:
            print("  ※ 모델 호출 상한에 도달해 여기서 멈춘다.")
            break
        time.sleep(args.cooldown)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"measured_at": datetime.now().isoformat(timespec="seconds"), "base": base, "commit": git_commit(),
                                   "args": vars(args), "stages": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
