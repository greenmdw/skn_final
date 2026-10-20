"""에이전트 모델 호출의 자동 재시도 — U-16(결과 대화 꼬리 지연 50~77초).

OpenAI SDK 기본은 재시도 2회라, 응답이 없어 시간 초과가 나면 한 번의 호출이 3번 나가고 시간도 최악 3배가 된다(부하 시험의 꼬리 지연과 같은 모양).
에이전트(Strands OpenAIModel)는 client_args 로 SDK 클라이언트를 만들므로 거기에 max_retries 를 넣어 둔다.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import config
from src.agent import conditions_agent as ca


def test_agent_model_client_does_not_retry_by_default():
    assert config.LLM_AGENT_MAX_RETRIES == 0
    args = ca._model().client_args
    assert args["max_retries"] == config.LLM_AGENT_MAX_RETRIES
    assert args["timeout"] == config.LLM_TIMEOUT_SECONDS


def test_retry_setting_is_taken_from_the_config(monkeypatch):
    monkeypatch.setattr(ca, "LLM_AGENT_MAX_RETRIES", 1)
    assert ca._model().client_args["max_retries"] == 1


@pytest.fixture()
def hanging_server():
    """요청을 받고 한참 응답하지 않는 서버 — 시간 초과를 만든다."""
    hits: list[float] = []

    class Hang(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(time.time())
            time.sleep(4)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Hang)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", hits
    server.shutdown()


def _one_turn_against(base_url: str, monkeypatch, retries: int) -> float:
    from strands import Agent

    monkeypatch.setattr(ca, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ca, "LLM_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(ca, "LLM_AGENT_MAX_RETRIES", retries)
    model = ca._model()
    model.client_args["base_url"] = base_url
    started = time.time()
    with pytest.raises(Exception):  # noqa: B017 — 시간 초과(APITimeoutError)를 호출자(규칙 경로 대체)가 받는다
        Agent(model=model, system_prompt="s", callback_handler=None)("hi")
    return time.time() - started


def test_one_timed_out_agent_call_is_one_request_not_three(hanging_server, monkeypatch):
    base_url, hits = hanging_server
    elapsed = _one_turn_against(base_url, monkeypatch, retries=0)
    assert len(hits) == 1
    assert elapsed < 3          # 시간 제한(1초) + 여유 — 재시도했다면 4초 이상


def test_the_retry_setting_really_controls_the_number_of_requests(hanging_server, monkeypatch):
    base_url, hits = hanging_server
    _one_turn_against(base_url, monkeypatch, retries=1)
    assert len(hits) == 2       # 설정을 올리면 그만큼 재시도한다 — 이 테스트가 위 테스트의 전제(설정이 실제로 먹힘)를 보장한다
