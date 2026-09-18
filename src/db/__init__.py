"""DB 커넥션 (psycopg 풀).

get_conn() 은 트랜잭션 1개를 열고 with 블록 종료 시 commit/rollback 한다.
커넥션 풀(PgBouncer/RDS Proxy) 전제이므로 세션 상태에 의존하지 않는다 (SET LOCAL 만).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL

_pool: ConnectionPool | None = None  # 지연 초기화


def get_pool() -> ConnectionPool:
    """전역 커넥션 풀 반환 (최초 호출 시 생성).

    connect_timeout=5 — DB가 아예 없거나 호스트가 안 뜬 경우(로컬 DB를 안 띄워둔
    팀원, CATALOG_SOURCE 기본 폴백 경로 등) 기본 풀 타임아웃(30초)까지 기다리지
    않고 몇 초 안에 실패해, 호출자가 빨리 대체 경로로 넘어갈 수 있게 한다. 실제로
    떠 있는 DB(로컬이든 RDS든) 연결은 보통 1초 안에 끝나 영향이 없다."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True, timeout=3,
                               kwargs={"connect_timeout": 2})
    return _pool


@contextmanager
def get_conn() -> Iterator["object"]:
    """트랜잭션 1개.  with get_conn() as conn: repo(conn).do(...)"""
    with get_pool().connection() as conn:
        with conn.transaction():
            yield conn


def close_pool() -> None:
    """앱 종료 시 풀을 닫는다 (FastAPI shutdown 이벤트에서 호출)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
