"""결과 채팅 턴 점검 배치 (P2-4, 10/12 멘토링 "채팅 로그에 검사 상태 + 배치 판정").

신호 판정은 DB 없이(앞 절), 답 메시지 metadata["check"] 기록·재실행은 일회용 DB 로(뒤 절).
"""
from __future__ import annotations

import os
import uuid

import pytest

from src.workers import chat_turn_check as ctc


def _answer(content: str, **turn) -> dict:
    return {"content": content, "metadata": {"turn": {"path": "agent", **turn}}}


# ── 신호 ─────────────────────────────────────────────────────────────────────────────

def test_a_clean_turn_is_ok():
    signals = ctc.turn_signals(_answer("GPU를 RTX 4070으로 바꿨습니다.", latency_ms=4200), "그래픽카드 바꿔줘", "고마워", None)
    assert signals == [] and ctc.status_of(signals) == ctc.OK


def test_what_the_code_already_knows_failed_is_bad():
    """가드가 모델 답을 버렸거나 에이전트가 예외로 규칙 경로로 내려간 턴 — 사람이 볼 필요 없이 비정상이다."""
    guarded = _answer("구성표 기준으로만 답할 수 있어요 — 총액 1,907,128원", guard={"numbers": ["70400"]})
    assert ctc.turn_signals(guarded, "SN770은 얼마야?", None, None) == ["guard_replaced"]
    errored = {"content": "무엇을 바꿀지 이해하지 못했어요.", "metadata": {"turn": {"path": "rules_after_agent_error",
                                                                                "error": "TimeoutError"}}}
    signals = ctc.turn_signals(errored, "램 바꿔", None, None)
    assert signals == ["agent_error", "not_understood"] and ctc.status_of(signals) == ctc.BAD


@pytest.mark.parametrize("next_text", ["ㄴㄴ", "아니 그거 말고", "아뇨", "그게 아니라 램이요", "틀렸어"])
def test_a_rejection_right_after_the_answer_needs_review(next_text):
    signals = ctc.turn_signals(_answer("RAM을 16GB로 바꿨습니다."), "가격에 맞게 예산 줄여줘", next_text, None)
    assert signals == ["rejected_next"] and ctc.status_of(signals) == ctc.REVIEW


@pytest.mark.parametrize("next_text", ["고마워", "아이폰도 돼?", "아니면 RAM은?"])
def test_a_follow_up_that_is_not_a_rejection_is_not_flagged(next_text):
    assert ctc.turn_signals(_answer("RAM을 16GB로 바꿨습니다."), "램 줄여줘", next_text, None) == []


def test_saying_the_same_thing_again_means_the_answer_missed():
    signals = ctc.turn_signals(_answer("무엇을 원하시는지 조금 더 알려 주세요."), "모든걸 더 비싼걸로 바꿔줘",
                               "모든걸 더 비싼걸로 바꿔 줘!", None)
    assert signals == ["repeated_next"]


def test_asking_again_after_the_user_agreed_is_an_ask_loop():
    """되물어서 사용자가 "응"이라고 했는데 또 되묻는 것 — 10/7 실패 6("괜찮아, 바꿔줘"를 다시 물음)의 모양."""
    prev = "WD_BLACK SN770으로 바꾸면 총액은 1,977,528원입니다. 바꿔 드릴까요?"
    again = _answer("WD_BLACK SN770으로 바꾸면 예산 안에 들어갑니다. 바꿔 드릴까요?")
    assert ctc.turn_signals(again, "응 바꿔줘", None, prev) == ["ask_loop"]
    done = _answer("WD_BLACK SN770으로 바꿨습니다.")
    assert ctc.turn_signals(done, "응 바꿔줘", None, prev) == []


def test_a_slow_turn_needs_review():
    assert ctc.turn_signals(_answer("답", latency_ms=ctc.SLOW_MS + 1), "왜?", None, None) == ["slow"]


def test_judge_all_pairs_each_result_chat_answer_with_its_question_and_the_next_one():
    """조건 대화 답(턴 기록 없음)은 판정하지 않고, 되묻기 이어짐도 끊는다."""
    conv = uuid.uuid4()
    rows = [
        {"id": 1, "conversation_id": conv, "role": "user", "content": "게임용 200만원", "metadata": {}},
        {"id": 2, "conversation_id": conv, "role": "assistant", "content": "바꿔 드릴까요?", "metadata": {}},
        {"id": 3, "conversation_id": conv, "role": "user", "content": "응", "metadata": {}},
        {"id": 4, "conversation_id": conv, "role": "assistant", "content": "바꿔 드릴까요?", "metadata": {"turn": {}}},
        {"id": 5, "conversation_id": conv, "role": "user", "content": "ㄴㄴ", "metadata": {}},
        {"id": 6, "conversation_id": conv, "role": "assistant", "content": "알겠습니다.", "metadata": {"turn": {}}},
    ]
    judged = ctc.judge_all(rows)
    assert [(t["id"], t["user_text"], t["next_user_text"], t["signals"]) for t in judged] == [
        (4, "응", "ㄴㄴ", ["rejected_next"]),
        (6, "ㄴㄴ", None, []),
    ]


def test_intent_rates_count_flagged_turns_per_intent():
    judged = [{"answer": _answer("a", intent="other"), "status": ctc.OK},
              {"answer": _answer("b", intent="other"), "status": ctc.REVIEW},
              {"answer": _answer("c", intent="change"), "status": ctc.BAD},
              {"answer": {"content": "d", "metadata": {"turn": {"path": "previous_compare"}}}, "status": ctc.OK}]
    assert ctc.intent_rates(judged) == {"other": {"turns": 2, "flagged": 1}, "change": {"turns": 1, "flagged": 1},
                                        "-": {"turns": 1, "flagged": 0}}


def test_condition_summary_counts_only_conversations_that_reached_a_recommendation_for_asks():
    rows = [{"reached": True, "asks": 2, "not_understood": 0}, {"reached": True, "asks": 0, "not_understood": 1},
            {"reached": True, "asks": 3, "not_understood": 0}, {"reached": False, "asks": 5, "not_understood": 2}]
    assert ctc.condition_summary(rows) == {"conversations": 4, "reached": 3, "asks_median": 2, "asks_max": 3,
                                           "not_understood": 3}
    assert ctc.condition_summary([])["asks_median"] is None


def test_report_carries_the_other_ratio_and_condition_asks():
    result = {"turns": 4, "counts": {}, "updated": 0, "llm_calls": 0, "judged": [],
              "intents": {"other": {"turns": 3, "flagged": 0}, "ask": {"turns": 1, "flagged": 1}},
              "condition": {"conversations": 2, "reached": 1, "asks_median": 2, "asks_max": 2, "not_understood": 1}}
    text = ctc.report(result)
    assert "other) 3/4 (75%)" in text and "ask 1/1 (100%)" in text
    assert "추천까지 1개" in text and "중앙값 2" in text and "'이해하지 못했어요' 1번" in text


# ── DB: 기록과 재실행 ─────────────────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="set DATABASE_URL to a disposable migrated database")
def test_run_writes_the_check_into_the_answer_metadata_and_is_idempotent(monkeypatch):
    import psycopg

    from src.repo.user_repo import ConversationRepo

    with psycopg.connect(DSN) as conn:
        repo = ConversationRepo(conn)
        cid = repo.create(user_id=None, guest_session_hash=f"turn-check-{uuid.uuid4()}")
        repo.add_message(cid, "user", "가격에 맞게 예산 줄여줘")
        first = repo.add_message(cid, "assistant", "RAM을 16GB로 바꿨습니다.", metadata={"turn": {"path": "agent"}})
        repo.add_message(cid, "user", "ㄴㄴ")
        second = repo.add_message(cid, "assistant", "알겠습니다.", metadata={"turn": {"path": "agent"}})

        calls = []
        monkeypatch.setattr(ctc, "llm_judge", lambda *a: calls.append(a) or (ctc.BAD, "예산이 아니라 부품을 바꿈"))
        ctc.run(conn, llm=False)
        meta = {m["id"]: m["metadata"] for m in repo.messages(cid)}
        assert meta[first]["check"]["status"] == ctc.REVIEW and meta[first]["check"]["signals"] == ["rejected_next"]
        assert meta[second]["check"]["status"] == ctc.OK
        assert meta[first]["turn"] == {"path": "agent"}          # 턴 기록은 그대로 둔다

        mine = lambda r: [t for t in r["judged"] if t["id"] in (first, second)]   # noqa: E731 — 다른 테스트의 대화도 기간 안에 있다
        again = ctc.run(conn, llm=False)
        assert all((t["answer"]["metadata"] or {}).get("check") for t in mine(again))

        ctc.run(conn, llm=True)
        assert len([c for c in calls if c[0] == "가격에 맞게 예산 줄여줘"]) == 1
        check = {m["id"]: m["metadata"] for m in repo.messages(cid)}[first]["check"]
        assert check["status"] == ctc.BAD and check["by"] == "llm" and check["reason"]

        ctc.run(conn, llm=True)                                   # 신호가 같으면 모델에 다시 묻지 않는다
        assert len([c for c in calls if c[0] == "가격에 맞게 예산 줄여줘"]) == 1
        conn.rollback()


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="set DATABASE_URL to a disposable migrated database")
def test_condition_rows_count_questions_after_the_first_user_message_until_the_first_run():
    """여는 질문은 빼고, 첫 추천 실행 뒤의 답(턴 기록이 없던 옛 결과 채팅 답 포함)은 조건 대화로 세지 않는다."""
    import psycopg
    from psycopg.types.json import Jsonb

    from src.repo.user_repo import ConversationRepo

    with psycopg.connect(DSN) as conn:
        repo = ConversationRepo(conn)
        version = conn.execute(
            "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
            "WHERE d.code='computer' AND d.status='active' ORDER BY dv.version_no DESC LIMIT 1").fetchone()[0]

        def conversation(messages, *, run_after: int | None = None):
            cid = repo.create(user_id=None, guest_session_hash=f"cond-asks-{uuid.uuid4()}")
            plan = conn.execute("INSERT INTO planning.plan(conversation_id,name) VALUES (%s,'t') RETURNING id", (cid,)).fetchone()[0]
            rev = conn.execute("INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot) "
                               "VALUES (%s,1,%s,'t') RETURNING id", (plan, version)).fetchone()[0]
            for i, (role, text) in enumerate(messages):
                if i == run_after:
                    # 기본 created_at(now())은 트랜잭션 시작 시각이라 메시지보다 앞선다 — 실제 순서대로 찍는다
                    conn.execute("INSERT INTO engine.recommendation_run(revision_id,domain_version_id,input_snapshot,input_hash,"
                                 "draft_lock_version,engine_versions,status,created_at) "
                                 "VALUES (%s,%s,%s,'t',0,%s,'running',clock_timestamp())", (rev, version, Jsonb({}), Jsonb({})))
                repo.add_message(cid, role, text)
            return cid

        reached = conversation([
            ("assistant", "주로 어떤 용도로 쓰실 건가요?"), ("user", "영상 편집"),
            ("assistant", "예산은 얼마까지 생각하시나요?"), ("user", "130만원"),
            ("assistant", "가장 중요하게 생각하시는 건 뭔가요?"), ("user", "가성비"),
            ("assistant", "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."),
            ("user", "왜 이 CPU 골랐어?"), ("assistant", "더 궁금한 부품이 있으신가요?")], run_after=7)
        stopped = conversation([
            ("assistant", "주로 어떤 용도로 쓰실 건가요?"), ("user", "음"),
            ("assistant", "죄송해요, 이해하지 못했어요. 주로 어떤 용도로 쓰실 건가요?")])
        silent = conversation([("assistant", "주로 어떤 용도로 쓰실 건가요?")])

        rows = {r["conversation_id"]: r for r in ctc.condition_rows(conn, 30)}
        assert (rows[reached]["reached"], rows[reached]["asks"], rows[reached]["not_understood"]) == (True, 2, 0)
        assert (rows[stopped]["reached"], rows[stopped]["asks"], rows[stopped]["not_understood"]) == (False, 1, 1)
        assert silent not in rows
        conn.rollback()
