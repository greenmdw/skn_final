"""결과 화면 채팅 평가 세트 — 사용자가 할 만한 질문을 실제 모델로 돌려 답·도구·구성표 변화를 본다.

질문마다 같은 조건(게임 · 예산 · 가성비)으로 새 세션을 만들어 추천을 받은 뒤 한 턴만 보낸다(앞 질문의 교체가
다음 질문에 섞이지 않게). 자동으로 보는 것은 구조뿐이다:
- 구성표가 바뀌어야 하는 말(바꿔줘)만 바뀌었는가 — 묻는 말에 바뀌면 실패
- 기대한 도구 중 하나를 불렀는가 (기대가 없는 질문 — 일반 지식·범위 밖 — 은 보지 않는다)
- 수치 가드가 답을 버렸는가 / 에이전트가 실패해 규칙 경로로 갔는가
답의 내용(지어낸 사실, 넘겨 말하기)은 사람이 보고서를 읽고 판단한다 — 오류 분석용 표를 함께 낸다.

사용 (일회용 DB, 실제 LLM — MOCK_MODE=0 · OPENAI_API_KEY · LLM_MODEL · RESULT_AGENT=1 필요):
    TEST_DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5433/truefit_test MOCK_MODE=0 \\
      python scripts/result_chat_eval.py --out /tmp/result_chat_eval.md
    python scripts/result_chat_eval.py --only upgrade,whatif      # 유형만
    python scripts/result_chat_eval.py --budget 3000000

DB 이름에 "test" 가 없으면 거부한다(세션·추천 기록이 쌓이므로). 의도한 것이면 TRUEFIT_ALLOW_ANY_DB=1.
질문을 늘릴 때는 QUESTIONS 에 한 줄 — 시연·팀원 테스트에서 답 못 한 말을 여기로 옮긴다.
"""
from __future__ import annotations

import argparse
import logging
import os
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
    Q("offtopic", "모니터도 추천해줘"),
    Q("offtopic", "오늘 날씨 어때?"),
]


@dataclass
class Row:
    q: Q
    reply: str = ""
    trace: str = ""
    changed: list[str] = field(default_factory=list)
    rejected: str = ""
    fell_back: bool = False
    seconds: float = 0.0

    @property
    def called(self) -> list[str]:
        return [part.strip().split("(", 1)[0] for part in self.trace.split(" | ") if "(" in part]

    @property
    def problems(self) -> list[str]:
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


class _Capture(logging.Handler):
    """result agent 의 trace·가드 거절·규칙 경로 전환 로그를 한 턴 동안 모은다."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(record.getMessage())


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


def run(questions: list[Q], budget: int) -> tuple[list[Row], dict]:
    from fastapi.testclient import TestClient
    from src.api import app

    cap = _Capture()
    for name in ("src.services.recommendation_service", "src.agent.result_agent"):
        logging.getLogger(name).addHandler(cap)
        logging.getLogger(name).setLevel(logging.INFO)
    c = TestClient(app)
    rows, first = [], None
    for q in questions:
        lid, before = _new_session(c, budget)
        first = first or before
        cap.records.clear()
        started = time.time()
        body = c.post(f"/session/{lid}/result-message", json={"text": q.text}).json()
        row = Row(q=q, reply=body.get("reply") or "", seconds=round(time.time() - started, 1),
                  changed=_diff(before, body.get("result") or before))
        for msg in cap.records:
            if msg.startswith("result agent ["):
                row.trace = msg.split("]: ", 1)[1]
            elif msg.startswith("result agent reply rejected"):
                row.rejected = msg
            elif msg.startswith("result agent failed"):
                row.fell_back = True
        rows.append(row)
        mark = "OK " if not row.problems else "!! "
        print(f"{mark}[{q.kind}] {q.text} ({row.seconds}s) {'; '.join(row.problems)}", flush=True)
    return rows, first


def report(rows: list[Row], base: dict, model: str, budget: int) -> str:
    t = base["totals"]
    lines = [f"# 결과 화면 채팅 평가 — 모델 {model}, 예산 {budget:,}원", "",
             "기준 구성: " + " / ".join(f"{i['slot']} {i['product']['name']} {i['price']:,}" for i in base["items"]),
             f"총액 {t['selected_price']:,} · 잔여 {t['budget_remaining']:,}", ""]
    bad = [r for r in rows if r.problems]
    lines += [f"자동 점검: {len(rows) - len(bad)}/{len(rows)} 통과 (구조만 — 답의 내용은 아래를 읽고 판단)", "",
              "| 유형 | 질문 | 부른 도구 | 자동 점검 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.q.kind} | {r.q.text} | {', '.join(r.called) or '-'} | {'; '.join(r.problems) or 'OK'} |")
    lines.append("")
    for r in rows:
        lines += [f"## [{r.q.kind}] {r.q.text}", "", f"- 도구: {r.trace or '(없음 — 규칙 경로이거나 도구 없이 답함)'}",
                  f"- 구성표 변화: {'; '.join(r.changed) or '없음'} · {r.seconds}s"]
        if r.rejected:
            lines.append(f"- 수치 가드: {r.rejected}")
        lines += ["", "> " + r.reply.replace("\n", "\n> "), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--budget", type=int, default=1_500_000)
    parser.add_argument("--only", default="", help="유형을 쉼표로 (upgrade,whatif,...)")
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
    print(f"DB: {db} · 모델: {LLM_MODEL if result_agent.available() else '규칙 경로'} · 질문 {len(questions)}개\n")
    rows, base = run(questions, args.budget)
    text = report(rows, base, LLM_MODEL if result_agent.available() else "rules", args.budget)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n보고서: {args.out}")
    bad = sum(1 for r in rows if r.problems)
    print(f"자동 점검 {len(rows) - bad}/{len(rows)} 통과")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
