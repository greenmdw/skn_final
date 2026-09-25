"""JWT 발급·검증."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from uuid import UUID

from src.config import JWT_SECRET, JWT_TTL_DAYS
from src.errors import Unauthorized


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(user_id: UUID, email: str, *, ttl_seconds: int | None = None, after: float | None = None) -> str:
    """서명된 HS256 JWT 문자열. ttl_seconds 미지정 시 JWT_TTL_DAYS 사용.

    iat 는 초 단위로 버리지 않고 float 로 둔다 — password_updated_at(DB now(), 마이크로초 정밀도)과
    같은 초에 발급되는 토큰(가입 직후·비밀번호 변경 직후)이 세션 무효화 경계(_require_active_session 의
    <= 비교, §A-3)에 걸려 스스로를 무효화하지 않게 하려는 것이다. exp 는 초 단위로 충분해 int 로 버린다.

    after: DB 가 방금 기록한 시각(epoch 초). iat 는 이 값보다 항상 뒤가 된다. 앱 시계와 DB 시계가 몇 ms 만
    어긋나도(Windows 의 time.time() 은 ~16ms 단위) 방금 발급한 토큰이 그 직전에 기록된 password_updated_at
    보다 앞서 보여 무효로 판정되는 일을 막는다."""
    now = time.time()
    if after is not None and now <= after:
        now = after + 0.001
    ttl = JWT_TTL_DAYS * 86_400 if ttl_seconds is None else ttl_seconds
    # jti: iat 가 우연히 같아도(같은 마이크로초는 사실상 없지만 대비) 토큰 문자열이
    # 겹치지 않게 하는 무작위값일 뿐 — 검증에서 의미를 부여하지 않는다(블랙리스트 없음).
    jti = secrets.token_hex(8)
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps(
        {"sub": str(user_id), "email": email, "iat": now, "exp": int(now) + ttl, "jti": jti}, separators=(",", ":")
    ).encode())
    signature = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify(token: str) -> dict:
    """검증 후 클레임 dict. 실패 시 Unauthorized."""
    try:
        header, payload, signature = token.split(".")
        expected = _b64encode(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        decoded_header = json.loads(_b64decode(header))
        claims = json.loads(_b64decode(payload))
        if decoded_header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims.get("exp"), int):
            raise ValueError("claims")
        if not isinstance(claims.get("iat"), (int, float)):
            raise ValueError("claims")
        UUID(claims["sub"])
        if claims["exp"] <= int(time.time()):
            raise ValueError("expired")
        return claims
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise Unauthorized("유효하지 않거나 만료된 인증 토큰입니다.") from None
