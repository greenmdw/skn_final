"""FastAPI 인증 의존성."""
from __future__ import annotations
from uuid import UUID
from fastapi import Cookie, Depends, Header, Response
from src.auth import jwt, session_check
from src.config import COOKIE_NAME
from src.errors import Unauthorized

class Principal:
    def __init__(self, user_id: UUID | None, browser_token: str | None, session_iat: float | None = None,
                 session_jti: str | None = None, session_exp: int | None = None):
        self.user_id = user_id
        self.browser_token = browser_token
        self.session_iat = session_iat  # 로그인 토큰 발급 시각(초, 마이크로초 포함) — 비밀번호 변경 이전 토큰 무효화용
        self.session_jti = session_jti  # 로그인 토큰 id — 로그아웃한 토큰 폐기용
        self.session_exp = session_exp  # 로그인 토큰 만료 시각(epoch 초)

def optional_principal(
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    browser_token_header: str | None = Header(default=None, alias="X-Browser-Token"),
    browser_token_cookie: str | None = Cookie(default=None, alias="truefit_guest"),
) -> Principal:
    token = None
    if authorization is not None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise Unauthorized("Authorization 헤더 형식이 올바르지 않습니다.")
        token = value
    elif session_cookie:
        token = session_cookie

    user_id = None
    session_iat = None
    session_jti = None
    session_exp = None
    if token is not None:
        try:
            claims = jwt.verify(token)
            # 서명·만료가 맞아도 로그아웃·비밀번호 변경·탈퇴로 폐기된 세션이면 같은 취급을 한다
            if not session_check.is_session_valid(UUID(claims["sub"]), claims.get("jti"), claims["iat"]):
                raise Unauthorized("세션이 만료되었습니다. 다시 로그인해주세요.")
        except Unauthorized:
            # 명시적으로 보낸 Authorization 토큰이 잘못됐으면 호출자가 알아야 하니 401 을 그대로 낸다.
            # 쿠키의 토큰은 만료·손상돼도 브라우저가 알아서 보내는 값이라 로그아웃 상태로 취급하고, 낡은 쿠키는 지워 준다 —
            # 그러지 않으면 "로그인 유지"를 끈 사용자는 12시간 뒤 글 목록 같은 공개 화면도 401 로 막힌다.
            # 로그인이 필요한 API 는 user_id 가 없으니 원래대로 401("로그인이 필요합니다")을 낸다.
            if authorization is not None:
                raise
            response.delete_cookie(COOKIE_NAME, path="/")
        else:
            user_id = UUID(claims["sub"])
            session_iat = claims["iat"]
            session_jti = claims.get("jti")
            session_exp = claims["exp"]

    browser_token = browser_token_header or browser_token_cookie
    if browser_token is not None and not browser_token.strip():
        raise Unauthorized("browser token이 비어 있습니다.")
    return Principal(user_id, browser_token, session_iat, session_jti, session_exp)

def current_user(principal: Principal = Depends(optional_principal)) -> UUID:
    if principal.user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    return principal.user_id
