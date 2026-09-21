"""테스트 공통 설정 — 외부 호출 차단, DB 대기 상한, 개발 DB 보호.

1. MOCK_MODE=1 이 기본이다. 로컬 `.env` 가 MOCK_MODE=0 이어도(python-dotenv 는 이미 있는 환경변수를 덮지
   않는다) 테스트는 실제 LLM 을 부르지 않는다. 실호출이 필요하면 셸에서 MOCK_MODE=0 을 명시한다.
2. PGCONNECT_TIMEOUT=3 이 기본이다. DB 가 꺼져 있을 때 접속 시도가 OS 타임아웃(20초 이상)까지 매달려
   전체 스위트가 20분씩 걸리던 문제를 막는다.
3. 개발 DB 보호. 이름에 "test" 가 없는 DB 로는 접속을 *시도하는 순간* 차단한다 — 테스트가 개발 DB(truefit)에
   익명 세션·추천 기록을 쌓지 않게. 그 때문에 못 돈 테스트는 실패가 아니라 skip 으로 보고된다.
   - 일회용 DB 지정:   TEST_DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/truefit_test
     (DATABASE_URL·RAG_TEST_DATABASE_URL 을 함께 덮는다. 준비: db/setup_all.py 를 그 DB 로 실행)
   - 보호 해제(주의):  TRUEFIT_ALLOW_ANY_DB=1
"""
from __future__ import annotations

import os

# src.config 를 import 하기 전에 정한다(config 가 .env 를 읽되 이미 있는 환경변수는 덮지 않는다).
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("PGCONNECT_TIMEOUT", "3")
_TEST_URL = os.environ.get("TEST_DATABASE_URL")
if _TEST_URL:
    os.environ["DATABASE_URL"] = _TEST_URL
    os.environ["RAG_TEST_DATABASE_URL"] = _TEST_URL

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

_ALLOW_ANY = os.environ.get("TRUEFIT_ALLOW_ANY_DB") == "1"
_BLOCKED = {"count": 0, "targets": set()}
_MESSAGE = ("개발 DB 보호: '{db}' 는 테스트용 DB 가 아니라 접속을 차단했습니다. TEST_DATABASE_URL 로 이름에 'test' 가 "
            "들어간 일회용 DB 를 지정하세요(준비: db/setup_all.py). 의도한 것이면 TRUEFIT_ALLOW_ANY_DB=1.")


def _is_test_db(name: str | None) -> bool:
    return bool(name) and "test" in name.lower()


def _dbname(conninfo: str = "", kwargs: dict | None = None) -> str | None:
    if kwargs and kwargs.get("dbname"):
        return kwargs["dbname"]
    try:
        return conninfo_to_dict(conninfo or "").get("dbname")
    except Exception:  # noqa: BLE001 — 읽지 못하면 보호 쪽으로(차단)
        return None


def _deny(name: str | None) -> None:
    _BLOCKED["count"] += 1
    _BLOCKED["targets"].add(name or "?")
    raise psycopg.OperationalError(_MESSAGE.format(db=name or "?"))


def pytest_configure(config):
    if _ALLOW_ANY:
        return
    real = psycopg.Connection.__dict__["connect"].__func__     # 원래 classmethod 함수

    def guarded(cls, conninfo="", *args, **kwargs):
        name = _dbname(conninfo, kwargs)
        if not _is_test_db(name):
            _deny(name)
        return real(cls, conninfo, *args, **kwargs)

    psycopg.Connection.connect = classmethod(guarded)
    psycopg.connect = psycopg.Connection.connect              # psycopg.connect 는 별칭이라 따로 다시 묶는다

    import src.db as db_module                                # 풀: 호출마다 3초 기다리지 않고 즉시 거절

    real_pool = db_module.get_pool

    def guarded_pool():
        from src.config import DATABASE_URL

        name = _dbname(DATABASE_URL)
        if not _is_test_db(name):
            _deny(name)
        return real_pool()

    db_module.get_pool = guarded_pool


def _skip_if_blocked(before: int, exc: BaseException) -> None:
    if _BLOCKED["count"] > before and not isinstance(exc, (KeyboardInterrupt, SystemExit)):
        pytest.skip("개발 DB 보호로 DB 접속이 차단됐습니다 — TEST_DATABASE_URL 로 일회용 DB 를 지정하면 돕니다.")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    before = _BLOCKED["count"]
    try:
        return (yield)
    except BaseException as exc:  # noqa: BLE001
        _skip_if_blocked(before, exc)
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    before = _BLOCKED["count"]
    try:
        return (yield)
    except BaseException as exc:  # noqa: BLE001
        _skip_if_blocked(before, exc)
        raise


def pytest_report_header(config):
    from src.config import DATABASE_URL

    name = _dbname(DATABASE_URL)
    if _ALLOW_ANY:
        return f"DB: {name} — 개발 DB 보호 해제(TRUEFIT_ALLOW_ANY_DB=1)"
    if _is_test_db(name):
        return f"DB: {name} (일회용 테스트 DB) — DB 테스트가 실행됩니다"
    return f"DB: {name} (개발 DB) — 접속 차단, DB 가 필요한 테스트는 skip 됩니다. TEST_DATABASE_URL 로 일회용 DB 를 지정하세요"


def pytest_terminal_summary(terminalreporter):
    if _BLOCKED["count"]:
        terminalreporter.write_line(
            f"개발 DB 보호: {_BLOCKED['count']}번의 접속 시도를 차단했습니다({', '.join(sorted(_BLOCKED['targets']))}). "
            "DB 가 필요한 테스트는 skip 됐습니다 — TEST_DATABASE_URL=<이름에 test 가 든 DB> 로 실행하세요.")
