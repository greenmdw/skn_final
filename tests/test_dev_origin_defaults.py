"""개발요청 12번 — 개발 환경(5173 ↔ 8000)의 Origin 403을 기본값으로 막는다.

`src.config._with_dev_origins`(순수 함수, 재사용 가능한 설정값만 다룬다)와
`src.auth.origin._origin_allowed`(미들웨어가 실제로 거르는 판정 함수)를 따로 검사한다.
DB가 필요 없다."""
from __future__ import annotations

from types import SimpleNamespace

from src.auth import origin as origin_mod
from src.config import _with_dev_origins


def test_dev_origins_are_added_when_not_production():
    out = _with_dev_origins([], is_production=False)
    assert "http://localhost:5173" in out and "http://127.0.0.1:5173" in out


def test_dev_origins_do_not_duplicate_explicit_config():
    out = _with_dev_origins(["http://127.0.0.1:5173"], is_production=False)
    assert out.count("http://127.0.0.1:5173") == 1
    assert "http://localhost:5173" in out


def test_production_keeps_only_explicit_origins():
    out = _with_dev_origins(["https://truefit.example"], is_production=True)
    assert out == ["https://truefit.example"]
    assert "http://localhost:5173" not in out


def test_middleware_accepts_both_dev_origins(monkeypatch):
    monkeypatch.setattr(origin_mod, "ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"])
    request = SimpleNamespace(url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8000"))
    assert origin_mod._origin_allowed("http://localhost:5173", request)
    assert origin_mod._origin_allowed("http://127.0.0.1:5173", request)
    assert not origin_mod._origin_allowed("http://evil.example", request)
