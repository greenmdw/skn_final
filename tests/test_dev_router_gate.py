"""ACC-05 — /dev/* 는 운영(APP_ENV=production)에서 등록되지 않는다.

앱은 import 시점에 라우터를 붙이므로 환경을 바꿔 새 프로세스로 확인한다(DB 불필요).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_PROBE = (
    "import json; from src.api import app; "
    "print(json.dumps(sorted(p for p in app.openapi()['paths'] if p.startswith('/dev'))))"
)


def _dev_paths(**env: str) -> list[str]:
    base = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "JWT_SECRET")}
    run = subprocess.run(
        [sys.executable, "-c", _PROBE], env={**base, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **env},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("env", [{}, {"APP_ENV": "development"}])
def test_dev_routes_are_available_outside_production(env):
    assert "/dev/run" in _dev_paths(**env)


def test_dev_routes_are_not_registered_in_production():
    assert _dev_paths(APP_ENV="production", JWT_SECRET="x" * 32) == []
