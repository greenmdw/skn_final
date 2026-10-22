"""로그인 토큰이 지금도 유효한 세션인지 DB 로 확인한다(서버 쪽 로그아웃·비밀번호 변경·탈퇴·"모든 기기 로그아웃"의 효력).

JWT 는 서명과 만료만 보므로, 그것만으로는 로그아웃한 토큰이나 비밀번호를 바꾸기 전에 발급된 토큰을 막지 못한다. 이전에는 `require_active_user` 를
부르는 API(목록·내 정보 등)만 이 검사를 했고, 커뮤니티처럼 사용자 id 만 읽는 API 는 폐기된 토큰도 통과시켰다. 이제 요청마다 이 검사를 한다.

- 한 번의 가벼운 조회(기본 키)이고, 결과를 짧게(`TTL_SECONDS`, 기본 5초) 프로세스 안에 둬서 같은 사용자의 연속 요청이 DB 를 매번 치지 않는다.
  같은 프로세스에서 일어난 폐기는 바로 반영되고(`invalidate_user`), 다른 워커 프로세스에는 최대 TTL 만큼 늦게 반영된다.
- DB 에 닿을 수 없으면(풀 고갈·장애) **통과시킨다**(예전과 같은 JWT 만 보는 동작) — 이 검사 때문에 서비스 전체가 멈추지 않게 한다.
  통과 결과는 캐시하지 않는다.
"""
from __future__ import annotations

import logging
import threading
import time
from uuid import UUID

from src.config import SESSION_CHECK_TTL_SECONDS

log = logging.getLogger(__name__)

TTL_SECONDS: float = float(SESSION_CHECK_TTL_SECONDS)
_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, bool]] = {}
_MAX_ENTRIES = 5000


def _query(user_id: UUID, jti: str | None, iat: float) -> bool:
    from src.db import get_pool

    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT u.status, u.password_updated_at, u.sessions_revoked_at, "
            "EXISTS (SELECT 1 FROM identity.revoked_session r WHERE r.jti = %s) "
            "FROM identity.app_user u WHERE u.id = %s",
            (jti or "", user_id),
        ).fetchone()
    if row is None:
        return False
    status, password_updated_at, sessions_revoked_at, revoked = row
    if status != "active" or revoked:
        return False
    for floor in (password_updated_at, sessions_revoked_at):
        # 같은 시각이면(경계) 무효 — 비밀번호 변경 직후 발급한 토큰은 iat 가 항상 그 뒤라 걸리지 않는다
        if floor is not None and iat <= floor.timestamp():
            return False
    return True


def is_session_valid(user_id: UUID, jti: str | None, iat: float) -> bool:
    key = (str(user_id), jti or "")
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < TTL_SECONDS:
            return hit[1]
    try:
        valid = _query(user_id, jti, iat)
    except Exception:  # noqa: BLE001 — DB 문제로 모든 로그인 요청을 막지 않는다(JWT 서명·만료는 이미 확인했다)
        log.warning("세션 확인 실패 — 통과시킨다: user=%s", user_id, exc_info=True)
        return True
    if TTL_SECONDS > 0:
        with _lock:
            if len(_cache) >= _MAX_ENTRIES:
                _cache.clear()
            _cache[key] = (now, valid)
    return valid


def invalidate_user(user_id: UUID) -> None:
    """이 사용자의 확인 결과를 비운다(폐기·비밀번호 변경·탈퇴 직후 이 프로세스에서 바로 반영되게)."""
    prefix = str(user_id)
    with _lock:
        for key in [k for k in _cache if k[0] == prefix]:
            del _cache[key]


def reset_cache() -> None:
    with _lock:
        _cache.clear()
