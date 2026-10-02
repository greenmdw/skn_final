"""2순위 발견 사항 수정 확인 — 전체_테스트_시나리오_실행_기획.md §9(7번)·§10(8번).

- `/lists` 페이지네이션이 없던 것을 limit/offset(선택)으로 고쳤다 — 기본값(안 주면 전량)은 그대로.
- `pc_check`(비로그인 가능, LLM 호출)에 rate limit이 없던 것을 IP당 분당 한도로 고쳤다.

일회용 DB 가 필요하다(계정을 만들어야 한다)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from src.auth import ratelimit


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """프로세스 전역 카운터라 테스트 간에 새서 서로 간섭하지 않게 매번 비운다."""
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"pg-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "페이지네이션 테스트", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def test_lists_without_limit_still_returns_everything():
    """기본 동작 불변 — limit을 안 주면 예전처럼 전량."""
    c = _signed_up()
    for _ in range(5):
        assert c.post("/session").status_code == 200
    assert len(c.get("/lists").json()["items"]) == 5


def test_lists_limit_and_offset_slice_without_overlap():
    c = _signed_up()
    for _ in range(5):
        assert c.post("/session").status_code == 200

    page1 = c.get("/lists", params={"limit": 2}).json()["items"]
    page2 = c.get("/lists", params={"limit": 2, "offset": 2}).json()["items"]
    assert len(page1) == 2 and len(page2) == 2
    assert {i["list_id"] for i in page1}.isdisjoint({i["list_id"] for i in page2})


def test_lists_limit_out_of_range_is_rejected():
    c = _signed_up()
    assert c.get("/lists", params={"limit": 0}).status_code == 422
    assert c.get("/lists", params={"limit": 201}).status_code == 422
    assert c.get("/lists", params={"offset": -1}).status_code == 422


def test_pc_check_review_create_is_rate_limited_per_ip():
    from src.config import PC_CHECK_LIMIT_PER_MIN

    c = TestClient(app)  # 비로그인 — pc_check는 로그인 없이도 호출 가능하다
    body = {"current_specs_text": "CPU: i5-14400F"}
    codes = [c.post("/pc/reviews", json=body).status_code for _ in range(PC_CHECK_LIMIT_PER_MIN + 3)]
    assert codes[:PC_CHECK_LIMIT_PER_MIN].count(429) == 0, codes  # 한도 안에서는 429가 섞이면 안 됨
    assert all(code == 429 for code in codes[PC_CHECK_LIMIT_PER_MIN:]), codes  # 한도 넘으면 전부 429


def test_pc_check_ratelimit_is_per_ip_not_global():
    """한 IP가 한도를 다 써도 다른 IP(= 다른 TestClient, 같은 로컬 주소라 실제로는 테스트가 완전히
    분리되진 않지만) 가 아니라 이 라우터의 한도가 요청 바디·세션과 무관하게 IP 단위로 걸리는지만
    확인한다 — 다른 바디를 보내도 같은 429가 나와야 공유 한도라는 뜻."""
    from src.config import PC_CHECK_LIMIT_PER_MIN

    c = TestClient(app)
    for i in range(PC_CHECK_LIMIT_PER_MIN):
        c.post("/pc/reviews", json={"current_specs_text": f"CPU: 테스트{i}"})
    r = c.post("/pc/reviews", json={"current_specs_text": "CPU: 전혀 다른 내용"})
    assert r.status_code == 429, r.text
