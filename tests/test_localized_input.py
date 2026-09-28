import pytest

from src.services import recommendation_service


@pytest.mark.parametrize(("message", "expected"), [
    ("그래픽카드를 더 저렴하게 바꿔줘", "cheaper"),
    ("CPU를 더 좋은 걸로 바꿔줘", "pricier"),
    ("GPU에 대해 알려줘", None),
])
def test_result_change_direction_is_read_from_korean(message, expected):
    _slot, direction, _is_question = recommendation_service._parse_swap_request(message, {"CPU", "GPU"})
    assert direction == expected


@pytest.mark.parametrize("message", [
    "이 구성 총평 알려줘",
    "전체 평가를 요약해 줘",
])
def test_result_summary_request_is_recognised(message):
    assert recommendation_service._is_result_summary_request(message)


def test_result_summary_message_returns_saved_explanation(monkeypatch):
    stored = {"explanation": {"status": "ready", "text": "부품 균형이 잘 맞는 구성입니다."}}
    monkeypatch.setattr(
        recommendation_service,
        "_require_done_run",
        lambda conn, revision_id: (object(), {"id": "run-1"}),
    )
    monkeypatch.setattr(recommendation_service, "get_stored_result", lambda conn, revision_id: stored)

    # handle_result_message(공개 함수)는 이제 채팅을 identity.message에 저장한다(CHAT-08) — 그 저장까지
    # 이 순수 로직 테스트에서 흉내 낼 필요는 없으니, 저장 전 실제 처리부(_handle_result_message_inner)를 본다.
    out = recommendation_service._handle_result_message_inner(None, None, "이 구성 총평 알려줘")

    assert out == {"reply": "부품 균형이 잘 맞는 구성입니다.", "result": stored}


def test_result_summary_message_has_a_pending_reply(monkeypatch):
    stored = {"explanation": {"status": "pending", "text": None}}
    monkeypatch.setattr(
        recommendation_service,
        "_require_done_run",
        lambda conn, revision_id: (object(), {"id": "run-1"}),
    )
    monkeypatch.setattr(recommendation_service, "get_stored_result", lambda conn, revision_id: stored)

    out = recommendation_service._handle_result_message_inner(None, None, "요약해 줘")

    assert out["reply"] == "전체 구성 총평을 아직 준비하고 있어요. 잠시 후 다시 물어봐 주세요."
