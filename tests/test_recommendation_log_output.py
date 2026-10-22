"""추천 시간 계측 로그(INFO)가 서버 출력에 나온다 — 앱에 로깅 설정이 없어 `uvicorn src.api:app` 에서 INFO 가 버려지던 문제.

src/api.py 가 src.services.recommendation_service 로거에만 INFO 핸들러를 붙인다. 같은 메시지가 두 번 찍히지 않고, 전역 설정(root)·
다른 로거·propagate 는 그대로여야 한다(caplog 같은 root 핸들러도 계속 기록을 받는다). pytest 프로세스는 root 로거에 자기 핸들러가
있어 실제 서버와 다르므로 새 프로세스에서 uvicorn 이 하는 순서(로깅 설정 → 앱 import)대로 확인한다. DB 는 쓰지 않는다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")

ROOT = Path(__file__).resolve().parents[1]

# uvicorn 시작과 같은 순서: Config(로깅 설정) → load(앱 import). 그 뒤 앱을 다시 import 해도(reload) 핸들러는 하나여야 한다.
UVICORN_ORDER_PROBE = r'''
import importlib, logging, sys
from uvicorn.config import Config

Config("src.api:app", log_level="info").load()
import src.api
importlib.reload(src.api)
src.api._attach_recommendation_log_handler()

service = logging.getLogger("src.services.recommendation_service")
other = logging.getLogger("src.services.session_service")
service.info("PROBE-INFO")
service.warning("PROBE-WARNING")
other.info("OTHER-INFO")
other.warning("OTHER-WARNING")

captured = []                                  # caplog 처럼 root 에 붙는 핸들러 — propagate 가 그대로라 계속 기록을 받는다
class Capture(logging.Handler):
    def emit(self, record):
        captured.append(record.getMessage())
logging.getLogger().addHandler(Capture())
service.info("PROBE-CAPTURED")

root = logging.getLogger()
print("STATE", f"handlers={len(service.handlers)}", f"level={service.level}", f"propagate={service.propagate}",
      f"root_handlers={len(root.handlers) - 1}", f"root_level={root.level}",
      f"other_handlers={len(other.handlers)}", f"other_level={other.level}", f"captured={captured.count('PROBE-CAPTURED')}")
'''

# 운영이 root 로깅을 따로 설정한 경우 — 이미 그 핸들러로 나가므로 이 로거에 또 붙이면 같은 메시지가 두 번 찍힌다.
ROOT_CONFIGURED_PROBE = r'''
import logging, sys
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="ROOT %(message)s")

import src.api
service = logging.getLogger("src.services.recommendation_service")
service.info("PROBE-INFO")
print("STATE", f"handlers={len(service.handlers)}", f"propagate={service.propagate}")
'''


def _run(probe: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "MOCK_MODE": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, f"probe 가 실패했다:\n{proc.stdout}\n{proc.stderr}"
    return proc


def test_info_timing_lines_reach_the_server_output_exactly_once():
    proc = _run(UVICORN_ORDER_PROBE)

    assert proc.stderr.count("PROBE-INFO") == 1, proc.stderr
    assert proc.stderr.count("PROBE-WARNING") == 1, proc.stderr
    assert "INFO src.services.recommendation_service: PROBE-INFO" in proc.stderr
    assert "WARNING src.services.recommendation_service: PROBE-WARNING" in proc.stderr
    # 다른 로거는 그대로다 — INFO 는 여전히 버려지고, WARNING 은 파이썬 기본 처리(lastResort)로 한 번만 나온다
    assert "OTHER-INFO" not in proc.stderr
    assert proc.stderr.count("OTHER-WARNING") == 1, proc.stderr
    # 핸들러는 하나, 전역 설정·다른 로거·propagate 는 그대로, root 핸들러(caplog 같은 것)도 기록을 받는다
    state = next(line for line in proc.stdout.splitlines() if line.startswith("STATE"))
    assert state == ("STATE handlers=1 level=20 propagate=True root_handlers=0 root_level=30 "
                     "other_handlers=0 other_level=0 captured=1")


def test_no_second_handler_when_root_logging_is_already_configured():
    proc = _run(ROOT_CONFIGURED_PROBE)

    assert proc.stderr.count("PROBE-INFO") == 1, proc.stderr          # root 의 핸들러로 한 번만 나온다
    assert "ROOT PROBE-INFO" in proc.stderr
    state = next(line for line in proc.stdout.splitlines() if line.startswith("STATE"))
    assert state == "STATE handlers=0 propagate=True"
