"""결과 채팅 질문 칩(P2-2) — 결과 상태만 보고 고르는 순수 함수와, 같은 문장이 프롬프트·규칙 경로 답에 쓰이는지."""
from __future__ import annotations

from src.agent.result_agent import system_prompt
from src.services.result_advice import SUGGEST_UPGRADE_MIN, suggested_questions


def _result(remaining=300_000, over=False, slots=("CPU", "GPU", "RAM"), **extra):
    return {"category": "computer", "status": "done",
            "items": [{"slot": s, "selected": True} for s in slots],
            "totals": {"budget_remaining": remaining, "over_budget": over}, **extra}


def test_remaining_budget_suggests_upgrade_then_why_then_game():
    qs = suggested_questions(_result(), {"purpose": "game", "games": ["배틀그라운드", "롤"]})
    assert qs == ["남은 돈으로 할 만한 업그레이드 있어?", "왜 이 그래픽카드 골랐어?", "이 구성으로 배틀그라운드 잘 돌아가?"]


def test_budget_situation_picks_the_first_chip():
    assert suggested_questions(_result(over=True, remaining=-50_000), {})[0] == "뭘 바꾸면 제일 싸져?"
    # 예산을 많이 남긴 구성(budget_notice 가 있음) — 왜 남겼는지가 먼저 궁금하다
    notice = {"remaining": 900_000}
    assert suggested_questions(_result(remaining=900_000), {}, notice)[0] == "왜 예산을 다 안 썼어?"
    # 조금만 남으면 올릴 후보가 거의 없다 — 줄이기
    assert suggested_questions(_result(remaining=SUGGEST_UPGRADE_MIN - 1), {})[0] == "뭘 바꾸면 제일 싸져?"


def test_games_given_as_one_string_use_the_first_title():
    qs = suggested_questions(_result(), {"purpose": "game", "games": "발로란트·롤, 배그"})
    assert qs[2] == "이 구성으로 발로란트 잘 돌아가?"


def test_non_game_or_no_game_falls_back_to_compat_check_and_cpu_when_no_gpu():
    qs = suggested_questions(_result(slots=("CPU", "RAM")), {"purpose": "office"})
    assert qs == ["남은 돈으로 할 만한 업그레이드 있어?", "왜 이 CPU 골랐어?", "호환 문제 없어?"]
    assert suggested_questions(_result(), {"purpose": "game"})[2] == "호환 문제 없어?"


def test_no_chips_until_a_pc_build_is_done():
    assert suggested_questions(_result(status="running"), {}) == []
    assert suggested_questions(_result(category="peripheral"), {}) == []
    assert suggested_questions(_result(slots=()), {}) == []


def test_prompt_offers_the_same_sentences_as_the_chips():
    chips = ["뭘 바꾸면 제일 싸져?", "왜 이 그래픽카드 골랐어?", "호환 문제 없어?"]
    prompt = system_prompt({**_result(slots=()), "suggested_questions": chips}, "오늘 날씨 어때?", [])
    assert all(f"'{q}'" in prompt for q in chips)
    assert "글자 하나 바꾸지 않고" in prompt
    # 칩이 없으면 예전 예시
    assert "'쿨러 빼줘'" in system_prompt(_result(slots=()), "오늘 날씨 어때?", [])
