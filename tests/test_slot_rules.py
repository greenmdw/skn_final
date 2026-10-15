"""규칙 기반 금액 파싱 — 숫자 표현과 한글 숫자 단어(만·억) 모두를 다룬다."""
from __future__ import annotations

import pytest

from src.engine import slot_rules
from src.engine.slot_rules import _parse_won, extract_computer


@pytest.mark.parametrize("raw, expected", [
    ("300만", 3_000_000), ("300만원", 3_000_000), ("3,000,000원", 3_000_000),
    ("1.5억", 150_000_000), ("1500만원", 15_000_000),
    ("이백만", 2_000_000), ("이백만원", 2_000_000), ("삼백만원", 3_000_000),
    ("백만원", 1_000_000), ("이천오백만원", 25_000_000), ("일억", 100_000_000),
    ("백오십만원", 1_500_000),
])
def test_parse_won_accepts_digit_and_korean_word_amounts(raw, expected):
    assert _parse_won(raw) == expected


def test_parse_won_korean_amount_inside_a_sentence():
    # 실제 대화 문장 속에 섞여 있어도(문장 앞뒤 조사 포함) 금액만 뽑아야 한다
    assert _parse_won("예산은 이백만원 정도로 생각해요") == 2_000_000
    assert _parse_won("게임용이고 예산은 백오십만원이요") == 1_500_000


def test_parse_won_does_not_mistake_grammar_particles_for_digits():
    # "게임용이고"의 '이' 처럼 한글 숫자 글자와 겹치는 조사·어미가 먼저 매칭되면
    # 뒤에 나오는 진짜 금액("백오십만원")을 놓치고 2원으로 오인했던 회귀 버그.
    assert _parse_won("그냥 궁금해서 이거 물어봐요") is None
    assert _parse_won("보유 물품이 없어요") is None


def test_extract_computer_picks_up_korean_word_budget():
    out = extract_computer("게임용이고 예산은 백오십만원이요")
    assert out["budget_max"] == 1_500_000
    assert out["purpose"] == "game"


# ── 금액만 말한 답 — 조건 대화가 모델 없이 바로 반영 (10/15 QA #26 예산 10초) ──────────────
@pytest.mark.parametrize("text, budget_turn, expected", [
    ("200", True, 2_000_000), ("  300  ", True, 3_000_000),
    ("200만원", False, 2_000_000), ("예산은 200만 원 정도요", False, 2_000_000), ("150만원까지", False, 1_500_000),
    ("예산 150만원으로 해주세요", False, 1_500_000), ("1500000원", False, 1_500_000), ("2천만원", False, 20_000_000),
])
def test_budget_only_answer_is_read(text, budget_turn, expected):
    assert slot_rules.parse_budget_answer(text, budget_turn=budget_turn) == expected


@pytest.mark.parametrize("text, budget_turn", [
    ("200", False),                                   # 예산 차례가 아니면 단위 없는 수는 모른다
    ("200만원인데 조용하게", True), ("100~150만원", True),   # 다른 말·범위 — 모델에 맡긴다
    ("3천만원", True), ("5", True),                    # 범위 밖 — 모델이 범위를 설명한다
    ("삼백만원", True), ("1500000", True), ("2025년", True),
])
def test_other_answers_are_left_to_the_model(text, budget_turn):
    assert slot_rules.parse_budget_answer(text, budget_turn=budget_turn) is None
