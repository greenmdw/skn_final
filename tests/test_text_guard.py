"""다른 언어 글자가 섞인 모델 답 거르기 — 10/15 QA #40 ("日博 -vesm"), 결과 채팅 시연 DB 10/3 ("конкрет한 모델")."""
from __future__ import annotations

import pytest
import strands

from src.agent import conditions_agent as ca
from src.agent.text_guard import foreign_script
from src.categories import load_category
from src.services.session_service import _next_question, compute_missing


@pytest.mark.parametrize("reply, found", [
    ("예산을 日博 -vesm 반영했어요", ["日博"]),
    ("용도와 конкрет한 모델을 비교해야 합니다", ["конкрет"]),
    ("ゲーム용으로 맞출게요", ["ゲーム"]),
])
def test_foreign_script_is_found(reply, found):
    assert foreign_script(reply) == found


# 시연 DB 정상 답에 실제로 나온 기호들 — 막으면 안 된다
@pytest.mark.parametrize("reply", [
    "예산 ≤ 150만 원 · RTX 4060 × 1", "⚠ 예산 초과 — 다시 고르세요", "‘조용한’ PC → 저소음 쿨러…", "QHD 165Hz, 32GB",
])
def test_normal_replies_pass(reply):
    assert foreign_script(reply) == []


class _GarbageAgent:
    """모델 대신 — 도구 하나를 부르고 다른 언어가 섞인 답을 낸다."""
    def __init__(self, *, tools, **_):
        self.tools = {t.tool_name: t for t in tools}

    def __call__(self, text):
        self.tools["set_condition"]("budget_max", "100")
        return "日博 -vesm"


def test_conditions_turn_replaces_a_foreign_script_reply_but_keeps_checked_patches(monkeypatch):
    monkeypatch.setattr(strands, "Agent", _GarbageAgent)
    monkeypatch.setattr(ca, "_model", lambda: None)
    cat_def = load_category("computer")
    values = {"category": "computer", "mode": "build", "purpose": "game"}
    turn = ca.run_turn("computer", cat_def, values, [], "100",
                       missing_fn=lambda v: compute_missing(cat_def, v),
                       next_question_fn=lambda v: _next_question(cat_def, v))
    assert turn.patches == {"budget_max": 1_000_000}
    assert foreign_script(turn.reply) == []
    assert turn.reply.startswith("말씀하신 조건을 반영했어요.")
    assert _next_question(cat_def, {**values, **turn.patches})["text"] in turn.reply


# ── 초안을 두 번 쓰거나 내부 생각·형식 태그를 흘린 답 (gpt-6-luna, 10/15 실측) ──────────
from src.agent.text_guard import final_answer  # noqa: E402

_A = ("이 화면에서는 새 컴퓨터 조립만 다루고 있어 기존 PC의 그래픽 카드만 바꾸는 업그레이드는 도와드릴 수 없습니다. "
      "새로 맞출 PC의 용도와 예산을 알려주시겠어요? 먼저 용도는 무엇인가요?")
_B = "아직 추천 견적이 없어 지금은 그래픽카드를 바꿀 수 없습니다. 추천을 받은 뒤 결과 화면 대화창에서 부품을 바꾸실 수 있어요. 새 PC의 주요 용도는 무엇인가요?"
_LEAKED = chr(0x4E7D1)          # 실측 답에 나온 미할당 코드 포인트 — 모델 내부 형식 토큰


@pytest.mark.parametrize("raw, expected", [
    (f"{_A}\n日博\n-vesm\n\n{_A}", _A),                                                       # QA #40 화면 그대로
    (f"{_B[:-10]} \n{_LEAKED}assistant  (no tool call)\nShould ask first missing purpose exactly. We did. "
     f"But wording includes upgrade? \"주요 용도\" useful but likely exact first required.\n{_B}", _B),
    (f"{_B} \n</final>追加?", _B),
    (f"{_B}\n{_B.replace('바꾸실 수 있어요', '변경하실 수 있습니다')}", _B.replace("바꾸실 수 있어요", "변경하실 수 있습니다")),
])
def test_final_answer_keeps_only_the_last_korean_answer(raw, expected):
    assert final_answer(raw) == expected


@pytest.mark.parametrize("reply", [
    _B,
    "흰색 케이스는 기록해 두었지만 자동 추천에는 반영되지 않아요.\n가장 중요하게 생각하시는 건 뭔가요? (성능 우선, 가성비, 조용한 게 좋아요)",
    "RTX 4060 기준으로 FHD 144Hz를 맞출게요. 예산은 얼마까지 생각하시나요?",
])
def test_final_answer_leaves_a_normal_reply_alone(reply):
    assert final_answer(reply) == reply


class _DraftTwiceAgent:
    def __init__(self, **_):
        pass

    def __call__(self, text):
        return f"{_A}\n日博\n-vesm\n\n{_A}"


def test_conditions_turn_shows_the_answer_once_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(strands, "Agent", _DraftTwiceAgent)
    monkeypatch.setattr(ca, "_model", lambda: None)
    cat_def = load_category("computer")
    turn = ca.run_turn("computer", cat_def, {"category": "computer", "mode": "build"}, [], "그래픽 카드 바꿔줘",
                       missing_fn=lambda v: compute_missing(cat_def, v),
                       next_question_fn=lambda v: _next_question(cat_def, v))
    assert turn.reply == _A
