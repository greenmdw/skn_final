"""보안/권한(IDOR) — 전체_테스트_시나리오_실행_기획.md §10(8번).

session 라우터 전부가 `optional_principal`(인증 선택)을 쓰므로, 소유권은 로그인 `user_id`나
게스트 `browser_token` 쿠키 중 하나가 맞아야 한다(`session_service._owned`). 여기서는 그
소유권 검사가 실제로 모든 상태 변경 엔드포인트를 막는지 확인한다 — 일회용 DB 가 필요하다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"idor-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "IDOR 테스트", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _recommended_list(c) -> tuple[str, str]:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "게임용 PC 맞추고 싶어요"})
    assert r.status_code == 200, r.text
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", 2_000_000), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    item_id = data["items"][0]["item_id"]
    return lid, item_id


def test_other_logged_in_user_cannot_read_result():
    owner = _signed_up()
    lid, _item_id = _recommended_list(owner)

    other = _signed_up()
    assert other.get(f"/session/{lid}/result").status_code == 404
    # GET /session/{id}도 조건 상태를 담고 있어 소유권 검사를 받는다 — 결과뿐 아니라 조건도 404.
    assert other.get(f"/session/{lid}").status_code == 404


def test_anonymous_with_no_cookie_cannot_read_or_patch():
    owner = _signed_up()
    lid, item_id = _recommended_list(owner)

    stranger = TestClient(app)  # 쿠키·로그인 전혀 없음 — 이 list_id를 만든 적 없는 제3자
    assert stranger.get(f"/session/{lid}/result").status_code == 404
    assert stranger.patch(f"/session/{lid}/items/{item_id}", json={"qty": 2}).status_code == 404
    assert stranger.post(f"/session/{lid}/items/{item_id}/swap", json={"candidate_id": str(uuid4())}).status_code == 404
    assert stranger.patch(f"/session/{lid}/slot", json={"field": "budget_max", "value": 999}).status_code == 404
    assert stranger.post(f"/session/{lid}/message", json={"text": "아무 말"}).status_code == 404
    assert stranger.post(f"/session/{lid}/result-message", json={"text": "CPU 바꿔줘"}).status_code == 404


def test_other_logged_in_user_cannot_mutate():
    owner = _signed_up()
    lid, item_id = _recommended_list(owner)

    other = _signed_up()
    assert other.patch(f"/session/{lid}/items/{item_id}", json={"qty": 2}).status_code == 404
    assert other.post(f"/session/{lid}/items/{item_id}/swap", json={"candidate_id": str(uuid4())}).status_code == 404
    assert other.post(f"/session/{lid}/recommend").status_code == 404
    assert other.post(f"/session/{lid}/reset").status_code == 404


def test_guest_session_is_protected_by_its_own_cookie_not_just_list_id():
    """게스트(비로그인) 세션도 다른 브라우저(쿠키 없음)는 못 건드린다 — user_id 가 아니라
    browser_token 해시로 지켜지는 경로도 같은 보호를 받는지 확인."""
    owner = TestClient(app)  # 로그인 안 함 — /session 이 게스트 쿠키를 심어준다
    lid, item_id = _recommended_list(owner)
    assert "truefit_guest" in owner.cookies

    stranger = TestClient(app)  # 쿠키를 받은 적 없는 별도 클라이언트
    assert stranger.get(f"/session/{lid}/result").status_code == 404
    assert stranger.patch(f"/session/{lid}/items/{item_id}", json={"qty": 2}).status_code == 404

    # 소유자 본인은 계속 접근 가능 — 보호가 "아무도 못 들어옴"이 아니라 "소유자만" 인지 확인
    assert owner.get(f"/session/{lid}/result").status_code == 200


def test_guest_cookie_from_a_different_session_does_not_leak_access():
    """내 게스트 쿠키로 '남의' list_id를 접근해도 그 list_id의 소유자가 아니므로 막힌다 —
    쿠키 자체가 유효해도 list_id 별 소유권 해시가 다르면 통과 못 하는지 확인."""
    owner = TestClient(app)
    lid, _item_id = _recommended_list(owner)

    other_guest = TestClient(app)
    other_guest.post("/session")  # 자기 쿠키는 생김 — 하지만 owner의 lid는 모름
    assert other_guest.get(f"/session/{lid}/result").status_code == 404
