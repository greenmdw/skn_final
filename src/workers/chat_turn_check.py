"""결과 채팅 턴 점검 배치 — 답 메시지마다 검사 상태를 남긴다 (P2-4, 10/12 멘토링 "채팅 로그에 검사 상태 + 배치 판정").

    PYTHONPATH=. uv run python -m src.workers.chat_turn_check [--days 30] [--llm] [--dry-run]

결과 채팅 답(identity.message 중 metadata 에 턴 기록 "turn" 이 있는 것)마다 metadata["check"] 에 남긴다.

    {"status": 1, "signals": [...], "by": "rules" | "llm", "reason": "...", "checked_at": "...", "version": 1}

status — 0 미검사(check 가 없음), 1 정상, 2 비정상, 3 검증 필요. 스키마는 바꾸지 않는다(0011 의 metadata jsonb, 턴 기록과 같은 자리).

신호는 두 갈래다.
- 그 턴 자체의 기록 — 가드가 모델 답을 버림, 에이전트 실패로 규칙 경로, 규칙 경로가 "이해하지 못했어요", 느린 응답
- 다음 사용자 말 — 바로 거절("ㄴㄴ", "아니 그거 말고"), 같은 말을 다시 함, 되묻기가 두 번 이어짐.
  실제 로그로 실패를 찾는 신호다. 사용자가 아직 다음 말을 안 했으면 이 신호는 없다 — 그래서 기간 안의 턴은
  매번 처음부터 다시 판정한다(preference_signal_batch 와 같은 방식, 다시 돌려도 같고 바뀐 것만 쓴다).

`--llm` 은 '검증 필요'만 모델에게 다시 보인다(질문·답·도구 결과 원문 → 정상/비정상 + 이유). 규칙 신호는 넓게 잡아
놓치지 않는 쪽, 모델은 그중 진짜 실패를 가르는 쪽 — 멘토가 말한 "룰 뒤에 LLM 점검". 호출마다 비용이 들어 기본은 끈다.
모델이 판정한 턴은 다음 실행에서 신호가 그대로면 다시 묻지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

VERSION = 1
WINDOW_DAYS = 30
SLOW_MS = 15_000          # 10/7·10/9 측정 p95 6~7.6초의 두 배 남짓 — 이보다 느리면 사람이 볼 만하다
REPEAT_RATIO = 0.85       # 다음 말이 이 이상 같으면 같은 말을 다시 한 것("램 늘려줘" → "램 늘려 줘")

UNCHECKED, OK, BAD, REVIEW = 0, 1, 2, 3
STATUS_NAME = {UNCHECKED: "미검사", OK: "정상", BAD: "비정상", REVIEW: "검증 필요"}

# 신호 → 상태. 비정상은 코드가 이미 실패를 안 경우만(가드가 버림·에이전트 예외), 나머지는 사람이나 모델이 봐야 안다.
SIGNAL_STATUS = {
    "guard_replaced": BAD,       # 수치·표현 가드가 모델 답을 버리고 고정 문장으로 바꿈
    "agent_error": BAD,          # 에이전트 예외로 규칙 경로로 내려감
    "not_understood": REVIEW,    # 규칙 경로가 "무엇을 바꿀지 이해하지 못했어요"
    "slow": REVIEW,
    "rejected_next": REVIEW,     # 다음 말이 거절
    "repeated_next": REVIEW,     # 다음 말이 같은 말
    "ask_loop": REVIEW,          # 되물어서 "응" 했는데 또 되물음
}

_REJECT = re.compile(r"^\s*(?:ㄴㄴ|ㄴ+\s*$|아니(?:야|요|라|지)?\b|아냐|아뇨|그게\s*아니|그거\s*말고|틀렸|잘못|이상한데|뭔\s*소리)")
_ASK = re.compile(r"(?:드릴까요|할까요|바꿀까요|볼까요|넣을까요|뺄까요)\s*\??\s*$")
_AGREE = re.compile(r"^\s*(?:응|ㅇㅇ|ㅇㅋ|네|넵|예|그래|좋아|콜|ㄱㄱ|그렇게\s*해)")
_NOT_UNDERSTOOD = "무엇을 바꿀지 이해하지 못했어요"


def _norm(text: str) -> str:
    return re.sub(r"[\s.,!?~]+", "", text or "")


def turn_signals(answer: dict, user_text: str, next_user_text: str | None, prev_answer: str | None) -> list[str]:
    """답 하나의 신호. answer = {"content", "metadata"}, prev_answer = 바로 앞 답 문장(같은 대화)."""
    turn = (answer.get("metadata") or {}).get("turn") or {}
    reply = answer.get("content") or ""
    signals = []
    if turn.get("guard"):
        signals.append("guard_replaced")
    if turn.get("path") == "rules_after_agent_error" or turn.get("error"):
        signals.append("agent_error")
    if reply.startswith(_NOT_UNDERSTOOD):
        signals.append("not_understood")
    if (turn.get("latency_ms") or 0) > SLOW_MS:
        signals.append("slow")
    if next_user_text is not None:
        if _REJECT.search(next_user_text):
            signals.append("rejected_next")
        elif _norm(user_text) and SequenceMatcher(None, _norm(user_text), _norm(next_user_text)).ratio() >= REPEAT_RATIO:
            signals.append("repeated_next")
    if prev_answer and _ASK.search(prev_answer.strip()) and _AGREE.search(user_text or "") and _ASK.search(reply.strip()):
        signals.append("ask_loop")
    return signals


_SEVERITY = {OK: 0, REVIEW: 1, BAD: 2}     # 상태 번호(멘토가 말한 0~3)는 심각도 순이 아니다 — 비정상이 검증 필요보다 앞선다


def status_of(signals: list[str]) -> int:
    return max((SIGNAL_STATUS[s] for s in signals), key=_SEVERITY.get, default=OK)


# 판정 모델은 챗봇이 본 프롬프트(구성표·예산·조건)를 보지 못한다 — 턴 기록에 없다. 그래서 "예산 300만 원은 도구 결과에
# 없다"처럼 프롬프트에서 온 숫자를 지어낸 것으로 판정했다(10/13 시연 DB 47턴 시험). 숫자 사실 검사는 수치 가드가 하므로
# 여기서는 요청에 맞게 응했는지만 본다.
_JUDGE_SYSTEM = (
    "당신은 PC 견적 서비스의 결과 화면 채팅 로그를 검수합니다. 사용자 말, 챗봇 답, 그 답의 근거가 된 도구 결과 원문,"
    " 직전 챗봇 답과 다음 사용자 말(있으면)을 봅니다. '그렇게', '그걸로'는 직전 답이 제안한 것을 가리킵니다.\n"
    "- 판정 기준은 하나입니다: 챗봇이 사용자 말의 뜻대로 응했는가. 바꾸라는 말에 바꿨거나 못 바꾼 이유를 댔는지,"
    " 묻는 말에 그 질문에 답했는지, 이미 허락했는데 또 허락을 묻지 않았는지, 도구 결과와 반대로 말하지 않았는지.\n"
    "- 챗봇은 구성표·예산·조건을 따로 보고 답합니다. 도구 결과에 없는 금액이나 조건이 답에 있다는 이유만으로"
    " 틀렸다고 하지 마세요.\n"
    "- 결과 채팅이 할 수 있는 일은 부품 바꾸기·빼기·수량 바꾸기와 설명뿐입니다. 예산·용도·우선순위 같은 조건은 바꿀"
    " 수 없어 '조건 바꾸기'로 안내하는 것이 맞는 응대입니다. 사용자가 바꾸라고 하지 않았는데(묻기만 했는데) 바꾸지 않고"
    " 바꿀지 되묻는 것도 맞는 응대입니다.\n"
    "- 다음 사용자 말이 거절·반복이어도 답이 뜻대로 응했다면 ok=true 입니다(사용자가 마음을 바꾼 것).\n"
    "응했으면 ok=true, 아니면 ok=false. reason 은 한국어 한 문장."
)
_JUDGE_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
                 "required": ["ok", "reason"], "additionalProperties": False}


def llm_judge(user_text: str, answer: dict, next_user_text: str | None, prev_answer: str | None = None) -> tuple[int, str]:
    from src.clients.llm_client import call_llm

    turn = (answer.get("metadata") or {}).get("turn") or {}
    outputs = "\n".join(turn.get("outputs") or [])[:6000] or "(도구 호출 없음)"
    # 직전 답이 없으면 "응 그렇게 바꿔줘"의 '그렇게'를 모른다 — 제안과 다른 GPU로 바꾼 답을 정상으로 봤다(10/13 시험)
    prompt = (f"[직전 챗봇 답]\n{prev_answer or '(없음)'}\n\n[사용자 말]\n{user_text}\n\n[챗봇 답]\n{answer.get('content')}\n\n[도구 결과 원문]\n{outputs}\n\n"
              f"[다음 사용자 말]\n{next_user_text or '(없음)'}")
    out = call_llm(prompt, system=_JUDGE_SYSTEM, output_schema=_JUDGE_SCHEMA)
    return (OK if out.get("ok") else BAD), str(out.get("reason") or "")


def _turns(conn, days: int) -> list[dict]:
    """기간 안의 결과 채팅 대화를 메시지 순서대로. 결과 채팅 답이 하나라도 있는 대화만."""
    return conn.cursor(row_factory=dict_row).execute(
        """
        SELECT m.id, m.conversation_id, m.role, m.content, m.metadata
        FROM identity.message m
        WHERE m.conversation_id IN (
            SELECT DISTINCT conversation_id FROM identity.message
            WHERE role = 'assistant' AND metadata ? 'turn' AND created_at >= now() - (%s || ' days')::interval)
        ORDER BY m.conversation_id, m.created_at, (m.role <> 'user')
        """,
        (days,),
    ).fetchall()


def judge_all(rows: list[dict]) -> list[dict]:
    """메시지 행(대화·시각 순) → 결과 채팅 답마다 {"id", "user_text", "next_user_text", "answer", "signals", "status"}."""
    out = []
    by_conv: dict = {}
    for r in rows:
        by_conv.setdefault(r["conversation_id"], []).append(r)
    for msgs in by_conv.values():
        user_text, prev_answer = "", None
        for i, m in enumerate(msgs):
            if m["role"] == "user":
                user_text = m["content"]
                continue
            if "turn" not in (m["metadata"] or {}):
                prev_answer = None          # 조건 대화 등 다른 채팅의 답 — 되묻기 이어짐을 끊는다
                continue
            next_user = next((n["content"] for n in msgs[i + 1:] if n["role"] == "user"), None)
            signals = turn_signals(m, user_text, next_user, prev_answer)
            out.append({"id": m["id"], "user_text": user_text, "next_user_text": next_user, "answer": m,
                        "prev_answer": prev_answer, "signals": signals, "status": status_of(signals)})
            prev_answer = m["content"]
    return out


def run(conn, *, days: int = WINDOW_DAYS, llm: bool = False, dry_run: bool = False) -> dict:
    """1회 실행. 반환: 상태별 건수·바뀐 건수·점검 목록(보고용)."""
    judged = judge_all(_turns(conn, days))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated = llm_calls = 0
    for t in judged:
        old = (t["answer"]["metadata"] or {}).get("check") or {}
        check = {"status": t["status"], "signals": t["signals"], "by": "rules", "version": VERSION}
        if t["status"] == REVIEW and old.get("by") == "llm" and old.get("signals") == t["signals"]:
            check = {k: old[k] for k in ("status", "signals", "by", "reason", "version") if k in old}   # 같은 신호는 다시 묻지 않는다
        elif t["status"] == REVIEW and llm:
            status, reason = llm_judge(t["user_text"], t["answer"], t["next_user_text"], t["prev_answer"])
            check.update(status=status, by="llm", reason=reason)
            llm_calls += 1
        t["status"], t["check"] = check["status"], check
        if {k: v for k, v in old.items() if k != "checked_at"} == check:
            continue
        updated += 1
        if not dry_run:
            conn.execute("UPDATE identity.message SET metadata = metadata || %s WHERE id = %s",
                         (Jsonb({"check": {**check, "checked_at": now}}), t["id"]))
    counts = {STATUS_NAME[s]: sum(t["status"] == s for t in judged) for s in (OK, BAD, REVIEW)}
    return {"turns": len(judged), "counts": counts, "updated": updated, "llm_calls": llm_calls, "judged": judged}


def report(result: dict) -> str:
    """사람이 볼 목록 — 정상이 아닌 턴만, 신호와 말·답 앞부분."""
    lines = [f"결과 채팅 턴 {result['turns']}개: " + ", ".join(f"{k} {v}" for k, v in result["counts"].items())
             + f" · 기록 바뀜 {result['updated']} · 모델 판정 {result['llm_calls']}회"]
    signal_counts: dict[str, int] = {}
    for t in result["judged"]:
        for s in t["signals"]:
            signal_counts[s] = signal_counts.get(s, 0) + 1
    if signal_counts:
        lines.append("신호: " + ", ".join(f"{k} {v}" for k, v in sorted(signal_counts.items(), key=lambda kv: -kv[1])))
    for t in result["judged"]:
        if t["status"] == OK:
            continue
        reason = t["check"].get("reason")
        lines.append(f"- [{STATUS_NAME[t['status']]}] {','.join(t['signals'])} | 말: {t['user_text'][:40]!r} | "
                     f"답: {(t['answer']['content'] or '')[:60]!r} | 다음 말: {(t['next_user_text'] or '')[:30]!r}"
                     + (f" | 판정: {reason}" if reason else ""))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--llm", action="store_true", help="'검증 필요' 턴을 모델로 다시 판정(호출마다 비용)")
    ap.add_argument("--dry-run", action="store_true", help="판정만 하고 DB 에 쓰지 않음")
    ap.add_argument("--json", action="store_true", help="상태별 건수만 JSON 으로")
    args = ap.parse_args()
    from src.db import get_background_conn
    with get_background_conn() as conn:
        result = run(conn, days=args.days, llm=args.llm, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({k: result[k] for k in ("turns", "counts", "updated", "llm_calls")}, ensure_ascii=False))
    else:
        print(report(result))


if __name__ == "__main__":
    main()
