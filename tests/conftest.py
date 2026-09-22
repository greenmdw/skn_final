"""테스트 공통 설정 — 외부 호출 차단, DB 대기 상한, 개발 DB 보호.

1. MOCK_MODE=1 이 기본이다. 로컬 `.env` 가 MOCK_MODE=0 이어도(python-dotenv 는 이미 있는 환경변수를 덮지
   않는다) 테스트는 실제 LLM 을 부르지 않는다. 실호출이 필요하면 셸에서 MOCK_MODE=0 을 명시한다.
2. PGCONNECT_TIMEOUT=3 이 기본이다. DB 가 꺼져 있을 때 접속 시도가 OS 타임아웃(20초 이상)까지 매달려
   전체 스위트가 20분씩 걸리던 문제를 막는다.
3. 기본적으로 로컬 PostgreSQL 서버에 고유한 truefit_test_<UUID> DB를 만들고 setup_all.py를 적용한 뒤
   테스트 종료 시 강제 삭제한다. 서버가 없을 때 DB를 필수로 요구하려면 TRUEFIT_REQUIRE_TEST_DB=1을 쓴다.
   자동 생성을 끄려면 TRUEFIT_AUTO_TEST_DB=0, 준비된 DB를 쓰려면 TEST_DATABASE_URL을 지정한다.
4. 개발 DB 보호. 이름에 "test"가 없는 DB 접속은 차단한다. 보호 해제는 TRUEFIT_ALLOW_ANY_DB=1이다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

# src.config 를 import 하기 전에 정한다(config 가 .env 를 읽되 이미 있는 환경변수는 덮지 않는다).
os.environ.setdefault("MOCK_MODE", "1")
os.environ.setdefault("PGCONNECT_TIMEOUT", "3")
# web/dist(새 React 프론트 빌드)가 있어도 기존 서빙 테스트는 옛 frontend/ 를 대상으로 한다. SPA 모드는
# tests/test_frontend_spa_serving.py 가 임시 폴더로 따로 검사한다.
os.environ.setdefault("TRUEFIT_FRONTEND", "legacy")
_TEST_URL = os.environ.get("TEST_DATABASE_URL")
if _TEST_URL:
    os.environ["DATABASE_URL"] = _TEST_URL
    os.environ["RAG_TEST_DATABASE_URL"] = _TEST_URL

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

_ALLOW_ANY = os.environ.get("TRUEFIT_ALLOW_ANY_DB") == "1"
_ROOT = Path(__file__).resolve().parents[1]
_AUTO_DB: tuple[str, str] | None = None
_REAL_CONNECT = psycopg.Connection.__dict__["connect"].__func__
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
    global _AUTO_DB
    if os.environ.get("TRUEFIT_AUTO_TEST_DB", "1") != "0" and not _TEST_URL:
        template = os.environ.get("DATABASE_URL", "postgresql://truefit:truefit@127.0.0.1:5432/truefit")
        params = conninfo_to_dict(template)
        name = f"truefit_test_{uuid4().hex[:12]}"
        admin_params = {**params, "dbname": "postgres", "connect_timeout": "3"}
        try:
            with psycopg.connect(**admin_params, autocommit=True) as admin:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        except psycopg.OperationalError as exc:
            if os.environ.get("TRUEFIT_REQUIRE_TEST_DB") == "1":
                raise pytest.UsageError(f"자동 테스트 DB 생성 실패: {exc}") from exc
        else:
            test_params = {**params, "dbname": name}
            test_url = make_conninfo(**test_params)
            os.environ["DATABASE_URL"] = test_url
            os.environ["RAG_TEST_DATABASE_URL"] = test_url
            result = subprocess.run(
                [sys.executable, "db/setup_all.py"], cwd=_ROOT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}, capture_output=True, text=True,
            )
            if result.returncode:
                with psycopg.connect(**admin_params, autocommit=True) as admin:
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                raise pytest.UsageError(f"자동 테스트 DB 준비 실패:\n{result.stdout}\n{result.stderr}")
            _AUTO_DB = (make_conninfo(**admin_params), name)

    if _ALLOW_ANY:
        return
    real = _REAL_CONNECT                                       # 원래 classmethod 함수

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


def pytest_unconfigure(config):
    if _AUTO_DB:
        admin_url, name = _AUTO_DB
        with _REAL_CONNECT(psycopg.Connection, admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


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
