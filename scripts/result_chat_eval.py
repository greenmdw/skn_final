"""결과 화면 채팅 평가 세트 — 사용자가 할 만한 질문을 실제 모델로 돌려 답·도구·구성표 변화를 본다.

질문마다 같은 조건(게임 · 예산 · 가성비)으로 새 세션을 만들어 추천을 받은 뒤 한 턴만 보낸다(앞 질문의 교체가
다음 질문에 섞이지 않게). 자동으로 보는 것은 구조뿐이다:
- 구성표가 바뀌어야 하는 말(바꿔줘)만 바뀌었는가 — 묻는 말에 바뀌면 실패
- 기대한 도구 중 하나를 불렀는가 (기대가 없는 질문 — 일반 지식·범위 밖 — 은 보지 않는다)
- 수치 가드가 답을 버렸는가 / 에이전트가 실패해 규칙 경로로 갔는가
도구·경로·가드·토큰은 서버 로그가 아니라 답 메시지에 저장된 턴 기록(metadata["turn"])에서 읽는다.
답의 내용(지어낸 사실, 넘겨 말하기)은 사람이 보고서를 읽고 판단한다 — 도구 결과 원문을 함께 낸다.
보고서 첫 표가 합격 기준(아래 상수, 10/7 측정 전 확정) 판정이고, 자동 기준이 하나라도 미달이면 종료 코드 1.

사용 (일회용 DB, 실제 LLM — MOCK_MODE=0 · OPENAI_API_KEY · LLM_MODEL · RESULT_AGENT=1 필요):
    TEST_DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5433/truefit_test MOCK_MODE=0 \\
      python scripts/result_chat_eval.py --out /tmp/result_chat_eval.md
    python scripts/result_chat_eval.py --repeat 3 --out ...      # 합격 판정은 세 판(같은 문항 × 3)
    python scripts/result_chat_eval.py --only upgrade,whatif      # 유형만
    python scripts/result_chat_eval.py --budget 3000000

DB 이름에 "test" 가 없으면 거부한다(세션·추천 기록이 쌓이므로). 의도한 것이면 TRUEFIT_ALLOW_ANY_DB=1.
질문을 늘릴 때는 QUESTIONS 에 한 줄 — 시연·팀원 테스트에서 답 못 한 말을 여기로 옮긴다.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Q:
    kind: str
    text: str
    change: bool = False                       # 구성표가 바뀌어야 하는 말인가
    tools: tuple[str, ...] = ()                # 이 중 하나는 불러야 한다 (비면 보지 않음)


# 유형: upgrade 남은 예산 · whatif 바꿔도 되나 · saving 줄이기 · check 점검 · game 게임 · change 바꾸라는 말 ·
#       info 구성표 정보 · general 일반 지식 · fact 제품별 사실(지어내면 안 됨) · nodata 데이터 없는 질문 ·
#       casual 실제 말투(자모·은어·물음표 없음) · offtopic 범위 밖
QUESTIONS: list[Q] = [
    Q("upgrade", "돈 남았는데 바꿀 거 추천해 줄 수 있나?", tools=("upgrade_options",)),
    Q("upgrade", "예산 남은 걸로 뭐 업그레이드하면 좋아?", tools=("upgrade_options",)),
    Q("upgrade", "10만원 정도 더 쓸 수 있으면 뭘 올리는 게 나아?", tools=("upgrade_options",)),
    Q("upgrade", "예산 200만원으로 늘려줘", tools=("upgrade_options",)),
    Q("whatif", "CPU 더 성능 좋은 걸로 바꿔도 문제없을까?", tools=("preview_swap", "upgrade_options")),
    Q("whatif", "그래픽카드 한 단계 올리면 파워는 괜찮아?", tools=("preview_swap",)),
    Q("whatif", "램 32기가로 늘려도 돼?", tools=("preview_swap", "upgrade_options")),
    Q("whatif", "그래픽카드 더 좋은 걸로 바꾸면 어때?", tools=("preview_swap",)),
    Q("whatif", "파워 더 싼 걸로 바꿔도 괜찮아?", tools=("preview_swap",)),
    Q("saving", "뭘 바꾸면 제일 싸져?", tools=("savings_options",)),
    Q("saving", "20만원 줄이고 싶은데 어디서 줄이면 돼?", tools=("savings_options",)),
    Q("check", "파워 용량 충분해?", tools=("check_build",)),
    Q("check", "호환 문제 없어?", tools=("check_build",)),
    Q("game", "이 구성으로 배그 잘 돌아가?", tools=("game_check",)),
    Q("game", "사이버펑크도 돌아가?", tools=("game_check",)),
    Q("game", "롤이랑 발로란트 둘 다 돼?", tools=("game_check",)),
    Q("change", "CPU 한 단계 좋은 걸로 바꿔줘", change=True, tools=("swap",)),
    Q("change", "SSD 2개로 해줘", change=True, tools=("set_item",)),
    Q("change", "쿨러 빼줘", change=True, tools=("set_item",)),
    Q("info", "지금 총 얼마고 예산 얼마 남았어?"),
    Q("info", "왜 이 그래픽카드 골랐어?", tools=("explain",)),
    Q("general", "쿨러 꼭 사야 돼?"),
    Q("general", "인텔이랑 AMD 차이가 뭐야?"),
    Q("general", "DDR4랑 DDR5 차이가 뭐야?"),
    Q("general", "파워 80플러스 골드가 뭐야?"),
    Q("general", "조립 어려워?"),
    Q("general", "나중에 그래픽카드만 바꿀 수 있어?"),
    Q("general", "CPU가 그래픽카드 발목 잡지 않아?"),
    Q("fact", "라이젠 7600에 기본 쿨러 들어 있어?"),
    Q("nodata", "이 구성 조용해?"),
    Q("nodata", "지금 사는 게 나아? 가격 떨어질까?"),
    # 실제 말투 — 물음표 없음·자모·은어·띄어쓰기 없음 (한 사람이 쓴 위 질문은 85%가 '?'로 끝나고 자모·은어 0%였다)
    Q("casual", "글카 갈아타도됨?", tools=("preview_swap",)),
    Q("casual", "cpu 7600x로 가면 괜찮음?", tools=("preview_swap", "list_alternatives")),
    Q("casual", "램 32로 ㄱㄱ?", tools=("preview_swap", "upgrade_options", "list_alternatives")),
    Q("casual", "그래픽 올리는거 어케생각함", tools=("preview_swap", "upgrade_options")),
    Q("casual", "파워 바꾸는거 ㄱㅊ?", tools=("preview_swap", "list_alternatives")),
    Q("casual", "씨퓨 업글 해도 무방?", tools=("preview_swap", "upgrade_options")),
    Q("casual", "SSD 1테라 더 달아도 됨", tools=("preview_swap", "set_item", "list_alternatives")),
    Q("casual", "남는돈으로 머 올리지", tools=("upgrade_options",)),
    Q("casual", "글카 한단계 위로 바꿔주셈", change=True, tools=("swap",)),
    # 시연 대화(2026-10-02)에서 옮긴 것 — 10만원 목표에 CPU 를 등급 8→4 로 내리던 것
    Q("casual", "10만원 정도 절약할 부품바꿀거 있나 혹시", tools=("savings_options",)),
    Q("casual", "성능 좀더 좋은걸로 바꿀만한 부품 있나", tools=("upgrade_options", "preview_swap")),
    Q("offtopic", "모니터도 추천해줘"),
    Q("offtopic", "오늘 날씨 어때?"),
]


# ── 합격 기준 (2026-10-07 측정 전 확정) ─────────────────────────────────────────────────────────
# 근거·쓰지 않은 대안·대가는 팀 문서 「채팅 설계 근거」의 '평가 합격 기준 (10/7)' 탭. 요약: 숫자로 된 공인 기준은
# 없어(ISO/IEC 25059·TTA 단체표준은 정성 항목) 직접 정했다. 기준을 낮추지 않는다 — 못 넘으면 미달로 기록한다.
# 비율 기준은 표본보다 촘촘할 수 있다: 132답에서 0건이어도 실제 비율의 95% 상한은 약 3/132 = 2.3%다.
STRUCTURAL_PASS_MIN = 0.95      # 자동 점검에 문제 없는 답의 비율
WRONG_CHANGE_MAX = 0            # 바꾸라는 말이 아닌데 구성표가 바뀐 답 (안전 기준)
FAILED_MAX = 0                  # 빈 답·HTTP 오류 — 사용자에게 보이는 실패
FALLBACK_RATE_MAX = 0.05        # 규칙 경로 전환 + 수치 가드 거절 — 조용한 품질 저하
P95_SECONDS_MAX = 10.0          # 왕복 시간 p95 (Nielsen 10초 주의 한계)
# 사람이 판정하는 기준(보고서를 읽고 라벨) — 스크립트는 자리만 낸다
FABRICATED_RATE_MAX = 0.01      # 비사실: 화면·도구 결과와 다르거나 지어낸 사실이 있는 답
GROUNDED_RATE_MIN = 0.95        # 근거 정확도: 가격·부품명·수치가 나온 답 중 모두 맞는 답
# 오도(확인 안 한 것을 단정·질문을 비켜 답함)는 기준 없이 건수만 보고한다.

# 토큰 단가(USD / 100만 토큰, 입력·출력) — src/config.py 의 2026-10-01 비교 메모. 캐시 할인은 반영하지 않아
# 상한 추정이다. 단가는 바뀌므로 턴 기록에는 토큰만 남기고 비용은 여기서 곱한다.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {"gpt-6-luna": (0.10, 0.50)}


@dataclass
class Row:
    q: Q
    run: int = 1
    reply: str = ""
    status: int = 200
    turn: dict = field(default_factory=dict)       # 답 메시지의 metadata["turn"] (P1-3 턴 기록)
    changed: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def trace(self) -> list[str]:
        return list(self.turn.get("trace") or [])

    @property
    def called(self) -> list[str]:
        return list(self.turn.get("tools") or [])

    @property
    def failed(self) -> bool:
        return self.status != 200 or not self.reply.strip()

    @property
    def rejected(self) -> bool:
        return bool(self.turn.get("guard"))

    @property
    def fell_back(self) -> bool:
        # 모델이 실패해 규칙 경로로 갔거나, 도구가 바꾼 뒤 실패해 코드 문장으로 답한 경우 — 둘 다 LLM 답이 아니다
        return self.turn.get("path") == "rules_after_agent_error" or bool(self.turn.get("error"))

    @property
    def problems(self) -> list[str]:
        if self.failed:
            return [f"실패 응답(HTTP {self.status})" if self.status != 200 else "빈 답"]
        out = []
        if bool(self.changed) != self.q.change:
            out.append("구성표가 바뀜" if self.changed else "바꾸지 않음")
        if self.q.tools and not set(self.called) & set(self.q.tools):
            out.append(f"도구 안 부름({'/'.join(self.q.tools)})")
        if self.rejected:
            out.append("수치 가드가 답을 버림")
        if self.fell_back:
            out.append("규칙 경로로 넘어감")
        return out


def assert_disposable_db() -> str:
    from psycopg.conninfo import conninfo_to_dict
    from src.config import DATABASE_URL
    name = conninfo_to_dict(DATABASE_URL).get("dbname") or ""
    if "test" not in name.lower() and os.environ.get("TRUEFIT_ALLOW_ANY_DB") != "1":
        raise SystemExit(f"DB '{name}' 는 일회용(이름에 test)이 아닙니다. TEST_DATABASE_URL 을 지정하거나 "
                         "TRUEFIT_ALLOW_ANY_DB=1 을 설정하세요.")
    return name


def _new_session(c, budget: int) -> tuple[str, dict]:
    lid = c.post("/session").json()["list_id"]
    c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    for key, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value")):
        c.patch(f"/session/{lid}/slot", json={"field": key, "value": value})
    r = c.post(f"/session/{lid}/recommend", json={})
    assert r.status_code == 202, r.text
    for _ in range(60):
        res = c.get(f"/session/{lid}/result").json()
        if res.get("status") == "done":
            return lid, res
        time.sleep(1)
    raise RuntimeError("추천이 끝나지 않았습니다")


def _diff(before: dict, after: dict) -> list[str]:
    now = {i["slot"]: i for i in after.get("items", [])}
    out = []
    for a in before["items"]:
        b = now.get(a["slot"])
        if b and (a["product"]["variant_id"], a["qty"], a["selected"]) != (b["product"]["variant_id"], b["qty"], b["selected"]):
            out.append(f"{a['slot']}: {a['product']['name']}×{a['qty']}{'' if a['selected'] else '(빼둠)'}"
                       f" → {b['product']['name']}×{b['qty']}{'' if b['selected'] else '(빼둠)'}")
    return out


def _turn_log(lid: str) -> dict:
    """이 세션의 마지막 답 메시지에 남은 턴 기록 — 평가가 서버 로그 대신 실제 저장된 기록을 읽는다(기록도 같이 시험)."""
    import psycopg
    from psycopg.rows import dict_row
    from uuid import UUID
    from src.config import DATABASE_URL
    from src.repo.plan_repo import PlanRepo
    from src.repo.user_repo import ConversationRepo
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        conversation_id = PlanRepo(conn).get_current_revision(UUID(lid))["conversation_id"]
        answers = [m for m in ConversationRepo(conn).messages(conversation_id) if m["role"] == "assistant"]
    return ((answers[-1]["metadata"] or {}).get("turn") or {}) if answers else {}


def run(questions: list[Q], budget: int, repeat: int = 1) -> tuple[list[Row], dict]:
    from fastapi.testclient import TestClient
    from src.api import app

    c = TestClient(app, raise_server_exceptions=False)   # 500 도 실패 응답으로 센다
    rows, first = [], None
    for run_no in range(1, repeat + 1):
        if repeat > 1:
            print(f"\n── {run_no}/{repeat}판", flush=True)
        for q in questions:
            lid, before = _new_session(c, budget)
            first = first or before
            started = time.time()
            resp = c.post(f"/session/{lid}/result-message", json={"text": q.text})
            seconds = round(time.time() - started, 1)
            body = resp.json() if resp.status_code == 200 else {}
            row = Row(q=q, run=run_no, reply=body.get("reply") or "", status=resp.status_code, seconds=seconds,
                      changed=_diff(before, body.get("result") or before))
            if resp.status_code == 200:
                row.turn = _turn_log(lid)
            rows.append(row)
            mark = "OK " if not row.problems else "!! "
            print(f"{mark}[{q.kind}] {q.text} ({row.seconds}s) {'; '.join(row.problems)}", flush=True)
    return rows, first


def _pct(sorted_values: list[float], p: float) -> float:
    """기준선(10/7) 집계와 같은 방식 — 정렬한 값의 round(p·(n-1)) 번째."""
    return sorted_values[min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))]


def summary(rows: list[Row], model: str) -> dict:
    n = len(rows)
    runs = sorted({r.run for r in rows})
    by_q: dict[str, list[Row]] = {}
    for r in rows:
        by_q.setdefault(r.q.text, []).append(r)
    secs = sorted(r.seconds for r in rows)
    server_ms = sorted(r.turn["latency_ms"] for r in rows if isinstance(r.turn.get("latency_ms"), int))
    tokens = [r.turn["tokens"] for r in rows if r.turn.get("tokens")]
    tin, tout = sum(t["input"] for t in tokens), sum(t["output"] for t in tokens)
    price = PRICE_PER_MTOK.get(model)
    return {
        "n": n, "runs": len(runs),
        "structural": sum(1 for r in rows if not r.problems),
        "pass_k": sum(1 for rs in by_q.values() if all(not r.problems for r in rs)), "questions": len(by_q),
        "wrong_change": sum(1 for r in rows if r.changed and not r.q.change),
        "failed": sum(1 for r in rows if r.failed),
        "fallback": sum(1 for r in rows if not r.failed and (r.rejected or r.fell_back)),
        "p50": statistics.median(secs) if secs else 0.0, "p90": _pct(secs, .9) if secs else 0.0,
        "p95": _pct(secs, .95) if secs else 0.0, "max": secs[-1] if secs else 0.0,
        "over10": sum(1 for x in secs if x > P95_SECONDS_MAX),
        "server_p50_ms": statistics.median(server_ms) if server_ms else None,
        "server_p95_ms": _pct(server_ms, .95) if server_ms else None,
        "token_turns": len(tokens), "tokens_in": tin, "tokens_out": tout,
        "cost_usd": (tin * price[0] + tout * price[1]) / 1_000_000 if price and tokens else None,
    }


def criteria(s: dict) -> list[tuple[str, str, str, bool | None]]:
    """(지표, 결과, 기준, 합격 여부 — 사람 판정이면 None)."""
    n = s["n"]
    fab_max = int(FABRICATED_RATE_MAX * n)
    return [
        ("구조 자동 점검", f"{s['structural']}/{n} ({s['structural'] / n:.1%}), pass^{s['runs']} {s['pass_k']}/{s['questions']}",
         f"≥ {STRUCTURAL_PASS_MIN:.0%}", s["structural"] / n >= STRUCTURAL_PASS_MIN),
        ("구성표 오변경", f"{s['wrong_change']}건", f"{WRONG_CHANGE_MAX}건", s["wrong_change"] <= WRONG_CHANGE_MAX),
        ("실패 응답", f"{s['failed']}건", f"{FAILED_MAX}건", s["failed"] <= FAILED_MAX),
        ("대체 응답", f"{s['fallback']}/{n} ({s['fallback'] / n:.1%})", f"≤ {FALLBACK_RATE_MAX:.0%}",
         s["fallback"] / n <= FALLBACK_RATE_MAX),
        ("응답 시간", f"p95 {s['p95']:.1f}초 (p50 {s['p50']:.1f}, p90 {s['p90']:.1f}, 최대 {s['max']:.1f})",
         f"p95 ≤ {P95_SECONDS_MAX:.0f}초", s["p95"] <= P95_SECONDS_MAX),
        ("비사실", "사람 판정", f"≤ {FABRICATED_RATE_MAX:.0%} ({n}답 중 {fab_max}건 이하)", None),
        ("근거 정확도", "사람 판정", f"≥ {GROUNDED_RATE_MIN:.0%}", None),
        ("오도", "사람 판정", "건수만 보고", None),
    ]


def report(rows: list[Row], base: dict, model: str, budget: int) -> str:
    t = base["totals"]
    s = summary(rows, model)
    lines = [f"# 결과 화면 채팅 평가 — 모델 {model}, 예산 {budget:,}원, {s['runs']}판 × {s['questions']}문항", "",
             "기준 구성: " + " / ".join(f"{i['slot']} {i['product']['name']} {i['price']:,}" for i in base["items"]),
             f"총액 {t['selected_price']:,} · 잔여 {t['budget_remaining']:,}", "",
             "## 합격 기준", "", "| 지표 | 결과 | 기준 | 판정 |", "|---|---|---|---|"]
    for name, value, rule, ok in criteria(s):
        lines.append(f"| {name} | {value} | {rule} | {'—' if ok is None else '합격' if ok else '**미달**'} |")
    lines += ["", f"- 10초를 넘은 답: {s['over10']}개"]
    if s["server_p50_ms"] is not None:
        lines.append(f"- 서버 처리 시간(턴 기록): p50 {s['server_p50_ms'] / 1000:.1f}초 · p95 {s['server_p95_ms'] / 1000:.1f}초")
    if s["token_turns"]:
        per = (s["tokens_in"] + s["tokens_out"]) / s["token_turns"]
        cost = f" · 추정 비용 ${s['cost_usd']:.4f} (턴당 ${s['cost_usd'] / s['token_turns']:.5f}, 캐시 할인 미반영)" \
            if s["cost_usd"] is not None else f" · 단가 미등록 모델({model})"
        lines.append(f"- 토큰: 입력 {s['tokens_in']:,} · 출력 {s['tokens_out']:,} (턴당 평균 {per:,.0f}, "
                     f"{s['token_turns']}/{s['n']}턴에 기록){cost}")
    lines += ["", "## 문항별", "", "| 판 | 유형 | 질문 | 부른 도구 | 자동 점검 |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.run} | {r.q.kind} | {r.q.text} | {', '.join(r.called) or '-'} | {'; '.join(r.problems) or 'OK'} |")
    lines.append("")
    for r in rows:
        lines += [f"## [{r.run}판 · {r.q.kind}] {r.q.text}", "",
                  f"- 경로: {r.turn.get('path') or '-'} · 도구: {', '.join(r.called) or '(없음)'}",
                  f"- 구성표 변화: {'; '.join(r.changed) or '없음'} · {r.seconds}s"]
        if r.rejected:
            lines.append(f"- 수치 가드: {r.turn['guard']}")
        outputs = r.turn.get("outputs") or []
        if outputs:
            # 사람이 답을 판정하려면 도구 결과 원문이 있어야 한다(trace 는 160자로 잘린다 — 10/7 판정 때 DB 를 다시 봤다)
            lines += ["- 도구 결과 원문:", "", "```", *("\n".join(f"[{c.split(' → ', 1)[0]}]\n{o}"
                      for c, o in zip(r.trace, outputs)).splitlines()), "```"]
        lines += ["", "> " + r.reply.replace("\n", "\n> "), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--budget", type=int, default=1_500_000)
    parser.add_argument("--only", default="", help="유형을 쉼표로 (upgrade,whatif,...)")
    parser.add_argument("--repeat", type=int, default=1, help="같은 문항을 몇 판 돌릴지 (합격 판정은 3판 기준)")
    parser.add_argument("--out", default="", help="보고서(markdown) 경로")
    args = parser.parse_args(argv)

    if os.environ.get("TEST_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    sys.path.insert(0, str(ROOT))
    db = assert_disposable_db()
    from src.agent import result_agent
    from src.config import LLM_MODEL
    if not result_agent.available():
        print("경고: 결과 에이전트가 꺼져 있어 규칙 경로만 평가합니다 (MOCK_MODE=0 · OPENAI_API_KEY · LLM_MODEL · RESULT_AGENT=1).")
    kinds = {k.strip() for k in args.only.split(",") if k.strip()}
    questions = [q for q in QUESTIONS if not kinds or q.kind in kinds]
    model = LLM_MODEL if result_agent.available() else "rules"
    print(f"DB: {db} · 모델: {model} · 질문 {len(questions)}개 × {args.repeat}판\n")
    rows, base = run(questions, args.budget, args.repeat)
    text = report(rows, base, model, args.budget)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n보고서: {args.out}")
    results = criteria(summary(rows, model))
    for name, value, rule, ok in results:
        if ok is not None:
            print(f"{'합격' if ok else '미달'}  {name}: {value} (기준 {rule})")
    return 0 if all(ok is not False for *_, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
