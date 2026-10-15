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
