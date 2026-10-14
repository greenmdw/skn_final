"""만료되거나 깨진 로그인 쿠키는 공개 API 를 막지 않는다(로그인이 필요한 API 만 401).

"로그인 유지"를 끄면 로그인 쿠키가 브라우저를 닫을 때까지 남지만 안의 토큰은 12시간 뒤 만료된다. 그 쿠키 때문에 로그아웃 상태의
공개 화면(글 목록 등)이 401 로 막히면 안 된다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app
    from src.auth import jwt
    from src.config import COOKIE_NAME


def _client_with_cookie(value: str) -> TestClient:
    c = TestClient(app)
    c.cookies.set(COOKIE_NAME, value)
    return c


def _expired_token() -> str:
    return jwt.issue(uuid4(), "gone@example.test", ttl_seconds=-60)


@pytest.mark.parametrize("cookie", ["expired", "garbage"])
def test_public_read_apis_work_with_a_stale_cookie_and_the_cookie_is_cleared(cookie):
    c = _client_with_cookie(_expired_token() if cookie == "expired" else "garbage.token.value")
    r = c.get("/community/posts", params={"page_size": 1})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie and ("Max-Age=0" in set_cookie or "expires=" in set_cookie.lower())     # 낡은 쿠키를 지운다
    assert c.get("/catalog/products", params={"kind": "mouse", "q": "a", "limit": 1}).status_code == 200


@pytest.mark.parametrize("cookie", ["expired", "garbage"])
def test_login_required_apis_still_return_401_with_a_stale_cookie(cookie):
    c = _client_with_cookie(_expired_token() if cookie == "expired" else "garbage.token.value")
    assert c.get("/auth/me").status_code == 401
    r = c.post("/community/posts", json={"board_type": "free", "title": "t", "body": "b"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert c.post("/community/posts/00000000-0000-0000-0000-000000000000/likes").status_code == 401


def test_an_explicit_bad_bearer_token_is_still_rejected():
    c = TestClient(app)
    r = c.get("/community/posts", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert c.get("/community/posts", headers={"Authorization": "Basic abc"}).status_code == 401


def test_a_valid_login_still_works_and_a_new_login_replaces_the_stale_cookie():
    email = f"stale-{uuid4().hex[:10]}@example.test"
    signup = TestClient(app)
    assert signup.post("/auth/signup", json={"email": email, "password": "abcd1234", "display_name": "낡은쿠키", "terms_agreed": True,
                                             "privacy_agreed": True, "marketing_agreed": False}).status_code == 201
    c = _client_with_cookie(_expired_token())
    r = c.post("/auth/login", json={"email": email, "password": "abcd1234", "remember": True})
    assert r.status_code == 200
    assert c.get("/auth/me").json()["user"]["email"] == email                       # 새 쿠키가 낡은 쿠키를 이겼다
    assert c.get("/community/posts", params={"page_size": 1}).status_code == 200


# ── 로그인 보강: 이메일 변경에 비밀번호 확인, IP별 시도 제한 ───────────────────────────────
def _signup(c: TestClient, email: str, password: str = "abcd1234") -> None:
    r = c.post("/auth/signup", json={"email": email, "password": password, "display_name": "보강", "terms_agreed": True,
                                      "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text


def test_changing_the_email_requires_the_current_password():
    old, new = f"old-{uuid4().hex[:10]}@example.test", f"new-{uuid4().hex[:10]}@example.test"
    c = TestClient(app)
    _signup(c, old)
    r = c.patch("/auth/me", json={"email": new})
    assert r.status_code == 422 and r.json()["error"]["code"] == "password_required" and r.json()["error"]["field"] == "current_password"
    r = c.patch("/auth/me", json={"email": new, "current_password": "wrong-pass1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_password"
    assert c.get("/auth/me").json()["user"]["email"] == old                          # 거절된 요청은 아무것도 바꾸지 않았다
    r = c.patch("/auth/me", json={"email": new, "current_password": "abcd1234"})
    assert r.status_code == 200 and r.json()["user"]["email"] == new
    fresh = TestClient(app)
    assert fresh.post("/auth/login", json={"email": new, "password": "abcd1234"}).status_code == 200
    assert TestClient(app).post("/auth/login", json={"email": old, "password": "abcd1234"}).status_code == 401


def test_other_profile_changes_and_the_same_email_need_no_password():
    email = f"same-{uuid4().hex[:10]}@example.test"
    c = TestClient(app)
    _signup(c, email)
    assert c.patch("/auth/me", json={"display_name": "새이름"}).json()["user"]["display_name"] == "새이름"
    assert c.patch("/auth/me", json={"marketing_agreed": True}).status_code == 200
    assert c.patch("/auth/me", json={"email": email.upper()}).status_code == 200      # 같은 이메일(대소문자만 다름)은 바뀌는 게 없다


def test_taken_email_is_still_a_conflict_after_the_password_check():
    first, second = f"a-{uuid4().hex[:10]}@example.test", f"b-{uuid4().hex[:10]}@example.test"
    _signup(TestClient(app), first)
    c = TestClient(app)
    _signup(c, second)
    r = c.patch("/auth/me", json={"email": first, "current_password": "abcd1234"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_login_attempts_are_limited_per_ip_even_for_unknown_accounts(monkeypatch):
    from src.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "LOGIN_LIMIT_PER_MIN_IP", 5)
    c = TestClient(app)
    codes = [c.post("/auth/login", json={"email": f"nobody{i}@example.test", "password": "abcd1234x"}).status_code for i in range(8)]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}                         # 계정이 달라도 같은 IP 면 막는다
    assert c.post("/auth/login", json={"email": "other@example.test", "password": "abcd1234x"}).json()["error"]["code"] == "rate_limited"


def test_signup_attempts_are_limited_per_ip(monkeypatch):
    from src.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "SIGNUP_LIMIT_PER_MIN_IP", 2)
    c = TestClient(app)
    codes = []
    for i in range(4):
        r = c.post("/auth/signup", json={"email": f"limit{i}-{uuid4().hex[:8]}@example.test", "password": "abcd1234", "display_name": "제한",
                                          "terms_agreed": True, "privacy_agreed": True})
        codes.append(r.status_code)
    assert codes == [201, 201, 429, 429]


def test_password_checks_on_profile_password_and_withdraw_share_a_per_ip_limit(monkeypatch):
    from src.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "LOGIN_LIMIT_PER_MIN_IP", 3)
    c = TestClient(app)
    _signup(c, f"cred-{uuid4().hex[:10]}@example.test")
    codes = [c.post("/auth/password", json={"current_password": "wrong-pass1", "new_password": "abcd12345"}).status_code for _ in range(3)]
    assert codes == [401, 401, 401]
    assert c.post("/auth/withdraw", json={"password": "wrong-pass1"}).status_code == 429          # 같은 한도를 나눠 쓴다
    assert c.patch("/auth/me", json={"email": "x@example.test", "current_password": "wrong-pass1"}).status_code == 429
