"""Stage 5 carries retained review fit and exact member evidence into the run trace."""
import pytest

from src.services.review_service import REVIEW_TRACE_STEP, explanation_text_with_caveats, review_trace_steps


def test_trace_includes_neutral_slots_and_actual_observation_document_ids():
    lines = {
        "GPU": "R=0.500 — balanced (P=1, N=1, mixed=1)",
        "CPU": "R=0.500 — selected condition has no observations",
    }
    evidence = {"GPU": [{
        "direction": "positive", "text": "quiet under load",
        "observation_id": "obs-1", "document_id": "doc-1",
    }, {
        "direction": "negative", "text": "fan noise under load",
        "observation_id": "obs-2", "document_id": "doc-2",
    }, {
        "direction": "mixed", "text": "mixed user reports",
        "observation_id": "obs-3", "document_id": "doc-3",
    }]}
    steps = review_trace_steps(lines, evidence)

    assert len(steps) == 2
    assert steps[0]["step"] == REVIEW_TRACE_STEP
    assert "2개 슬롯" in steps[0]["title"]
    assert "GPU" in steps[0]["detail"] and "CPU" in steps[0]["detail"]
    member_step = steps[1]
    assert "3건" in member_step["title"]
    for value in ("obs-1", "doc-1", "obs-2", "doc-2", "obs-3", "doc-3"):
        assert value in member_step["detail"]
    assert "positive" in member_step["detail"]
    assert "negative" in member_step["detail"]
    assert "mixed" in member_step["detail"]
    assert "https://" not in member_step["detail"]


@pytest.mark.parametrize("lines", [{}, None])
def test_no_trace_without_review_lines(lines):
    assert review_trace_steps(lines) == []


def test_explanation_text_appends_caveats():
    text = explanation_text_with_caveats(
        "예산 안에서 게임 성능을 우선한 구성입니다.", ["리뷰 적합도는 확률이나 진위 판정이 아닙니다"])
    assert text.startswith("예산 안에서 게임 성능을 우선한 구성입니다.")
    assert "확인이 필요한 것:" in text
    assert "리뷰 적합도" in text


def test_explanation_text_without_caveats_is_summary_only():
    text = explanation_text_with_caveats("예산 안에서 게임 성능을 우선한 구성입니다.", [])
    assert text == "예산 안에서 게임 성능을 우선한 구성입니다."
    assert "확인이 필요한 것" not in text
