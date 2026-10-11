"""DB 커넥션 (psycopg 풀).

get_conn() 은 트랜잭션 1개를 열고 with 블록 종료 시 commit/rollback 한다.
커넥션 풀(PgBouncer/RDS Proxy) 전제이므로 세션 상태에 의존하지 않는다 (SET LOCAL 만).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL, DB_BACKGROUND_POOL_MAX, DB_POOL_MAX, DB_POOL_MIN, DB_POOL_TIMEOUT

_pool: ConnectionPool | None = None  # 지연 초기화
_background_pool: ConnectionPool | None = None  # 백그라운드 작업(추천 실행) 전용


def get_pool() -> ConnectionPool:
    """전역 커넥션 풀 반환 (최초 호출 시 생성).

    connect_timeout=5 — DB가 아예 없거나 호스트가 안 뜬 경우(로컬 DB를 안 띄워둔
    팀원, CATALOG_SOURCE 기본 폴백 경로 등) 기본 풀 타임아웃(30초)까지 기다리지
    않고 몇 초 안에 실패해, 호출자가 빨리 대체 경로로 넘어갈 수 있게 한다. 실제로
    떠 있는 DB(로컬이든 RDS든) 연결은 보통 1초 안에 끝나 영향이 없다."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX, open=True, timeout=DB_POOL_TIMEOUT,
                               kwargs={"connect_timeout": 2})
    return _pool


def get_background_pool() -> ConnectionPool:
    """백그라운드 작업(추천 엔진·설명 저장) 전용 풀. 요청 풀(get_pool)과 분리해서, 요청이 몰려 풀이 차도 이미 접수한 추천이
    연결을 못 얻어 실패하지 않게 하고(그 반대도 마찬가지) 한쪽이 다른 쪽을 굶기지 않는다."""
    global _background_pool
    if _background_pool is None:
        _background_pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=max(1, DB_BACKGROUND_POOL_MAX), open=True,
                                          timeout=max(DB_POOL_TIMEOUT, 15), kwargs={"connect_timeout": 2})
    return _background_pool


@contextmanager
def get_background_conn() -> Iterator["object"]:
    """get_conn 과 같은 트랜잭션 1개 — 백그라운드 전용 풀에서 빌린다."""
    with get_background_pool().connection() as conn:
        with conn.transaction():
            yield conn


@contextmanager
def get_conn() -> Iterator["object"]:
    """트랜잭션 1개.  with get_conn() as conn: repo(conn).do(...)"""
    with get_pool().connection() as conn:
        with conn.transaction():
            yield conn


def close_pool() -> None:
    """앱 종료 시 풀을 닫는다 (FastAPI shutdown 이벤트에서 호출)."""
    global _pool, _background_pool
    if _pool is not None:
        _pool.close()
        _pool = None
    if _background_pool is not None:
        _background_pool.close()
        _background_pool = None
