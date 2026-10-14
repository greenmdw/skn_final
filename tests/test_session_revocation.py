"""서버 쪽 로그아웃·"모든 기기 로그아웃"·전역 세션 확인(폐기된 토큰은 어느 API 도 통과하지 못한다)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app
    from src.auth import session_check
    from src.config import COOKIE_NAME

PW = "abcd1234"


def _signup(email: str) -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": email, "password": PW, "display_name": "세션", "terms_agreed": True,
                                     "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c, c.cookies.get(COOKIE_NAME)


def _login(email: str) -> tuple[TestClient, str]:
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": email, "password": PW}).status_code == 200
    return c, c.cookies.get(COOKIE_NAME)


def _with(token: str) -> TestClient:
    c = TestClient(app)
    c.cookies.set(COOKIE_NAME, token)
    return c


def _email() -> str:
    return f"sess-{uuid4().hex[:10]}@example.test"


def test_logout_revokes_the_token_on_the_server():
    email = _email()
    c, token = _signup(email)
    assert c.get("/me/pc").status_code == 200
    assert c.post("/auth/logout").status_code == 204
    # 쿠키를 훔쳐 갔다고 치고 같은 토큰을 다시 쓴다 — 서버가 거절해야 한다
    stolen = _with(token)
    assert stolen.get("/auth/me").status_code == 401
    r = _with(token).put("/me/pc", json={"parts": {"cpu": "x"}})
    assert r.status_code == 401
    r = _with(token).post("/community/posts", json={"board_type": "free", "title": "t", "body": "b"})
    assert r.status_code == 401
    # 같은 계정의 다른 로그인은 영향이 없다
    other, _ = _login(email)
    assert other.get("/auth/me").status_code == 200


def test_logout_without_login_is_still_204():
    assert TestClient(app).post("/auth/logout").status_code == 204


def test_revoked_cookie_does_not_block_public_apis():
    c, token = _signup(_email())
    c.post("/auth/logout")
    stale = _with(token)
    assert stale.get("/community/posts", params={"page_size": 1}).status_code == 200      # 낡은 쿠키는 비로그인으로 취급


def test_logout_all_keeps_this_device_and_ends_the_others():
    email = _email()
    a, token_a = _signup(email)
    _, token_b = _login(email)
    r = a.post("/auth/logout-all", json={})
    assert r.status_code == 204
    assert a.get("/auth/me").status_code == 200                       # 새 토큰으로 이 기기는 유지
    assert a.cookies.get(COOKIE_NAME) != token_a
    assert _with(token_a).get("/auth/me").status_code == 401
    assert _with(token_b).get("/me/pc").status_code == 401            # 사용자 id 만 읽는 API 에서도 막힌다
    assert _with(token_b).get("/auth/me").status_code == 401


def test_logout_all_including_current_clears_everything():
    email = _email()
    a, token_a = _signup(email)
    assert a.post("/auth/logout-all", json={"include_current": True}).status_code == 204
    assert _with(token_a).get("/auth/me").status_code == 401
    fresh, _ = _login(email)                                          # 다시 로그인하면 정상
    assert fresh.get("/auth/me").status_code == 200


def test_logout_all_requires_login():
    assert TestClient(app).post("/auth/logout-all", json={}).status_code == 401


def test_password_change_now_blocks_old_tokens_on_every_api():
    email = _email()
    a, token_a = _signup(email)
    _, token_b = _login(email)
    r = a.post("/auth/password", json={"current_password": PW, "new_password": "newpass1234"})
    assert r.status_code in (200, 204), r.text
    assert _with(token_b).get("/me/pc").status_code == 401            # 이전에는 이런 API 가 옛 토큰을 통과시켰다
    assert a.get("/me/pc").status_code == 200                         # 변경한 기기는 새 토큰으로 유지


def test_withdrawn_account_tokens_stop_working():
    email = _email()
    a, token = _signup(email)
    assert a.post("/auth/withdraw", json={"password": PW}).status_code in (200, 204)
    assert _with(token).get("/me/pc").status_code == 401


def test_check_result_is_cached_for_the_ttl_and_invalidated_on_revocation(monkeypatch):
    email = _email()
    c, token = _signup(email)
    monkeypatch.setattr(session_check, "TTL_SECONDS", 60.0)
    session_check.reset_cache()
    calls = []
    real = session_check._query
    monkeypatch.setattr(session_check, "_query", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    for _ in range(3):
        assert c.get("/me/pc").status_code == 200
    assert len(calls) == 1                                            # 짧은 시간 안의 연속 요청은 DB 를 한 번만 친다
    assert c.post("/auth/logout").status_code == 204                  # 같은 프로세스의 폐기는 캐시를 바로 비운다
    assert _with(token).get("/me/pc").status_code == 401


def test_db_failure_during_the_check_fails_open(monkeypatch):
    c, _ = _signup(_email())

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(session_check, "_query", boom)
    session_check.reset_cache()
    assert c.get("/me/pc").status_code == 200                         # 확인 실패가 서비스 전체를 막지 않는다
