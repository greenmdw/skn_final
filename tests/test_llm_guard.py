"""LLM 호출 보호 (2026-10-08, 1단계-3): 동시 호출 상한, LLM 대기 요청 상한, 호출 시간 제한.

모델이 느리거나 몰려도 서버가 같이 무너지지 않아야 한다 — 상한을 넘으면 규칙 경로로 넘어가거나 503(+재시도 안내)으로 답한다.
실제 모델은 부르지 않는다.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from src import config
from src.clients import llm_guard
from src.errors import LLMBusy


@pytest.fixture()
def tight(monkeypatch):
    """상한을 작게·대기를 짧게 — 자리가 없을 때의 동작을 빨리 본다."""
    monkeypatch.setattr(config, "LLM_QUEUE_TIMEOUT_SECONDS", 0.1)

    def make(call=1, request=1):
        monkeypatch.setattr(llm_guard, "_call_slots", threading.BoundedSemaphore(call))
        monkeypatch.setattr(llm_guard, "_request_slots", threading.BoundedSemaphore(request))

    return make


def test_a_call_over_the_limit_gives_up_with_llm_busy_and_frees_the_slot_afterwards(tight):
    tight(call=1)
    with llm_guard.llm_call_slot():
        with pytest.raises(LLMBusy) as busy:
            with llm_guard.llm_call_slot():
                pass
        assert busy.value.http_status == 503 and busy.value.headers == {"Retry-After": "3"}
    with llm_guard.llm_call_slot():          # 앞의 자리가 풀렸으니 다시 들어간다
        pass


def test_the_slot_is_released_when_the_call_fails(tight):
    tight(call=1)
    with pytest.raises(RuntimeError):
        with llm_guard.llm_call_slot():
            raise RuntimeError("model error")
    with llm_guard.llm_call_slot():
        pass


def test_concurrent_calls_never_exceed_the_limit(monkeypatch):
    monkeypatch.setattr(config, "LLM_QUEUE_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(llm_guard, "_call_slots", threading.BoundedSemaphore(3))
    running, peak, lock = 0, 0, threading.Lock()

    def call():
        nonlocal running, peak
        with llm_guard.llm_call_slot():
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1

    threads = [threading.Thread(target=call) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak == 3


def test_request_slot_is_a_dependency_that_holds_until_the_response_is_done(tight):
    tight(request=1)
    first = llm_guard.llm_request_slot()
    next(first)                                   # 자리를 쥔다
    with pytest.raises(LLMBusy):
        next(llm_guard.llm_request_slot())
    with pytest.raises(StopIteration):
        next(first)                               # 응답이 끝나면 풀린다
    second = llm_guard.llm_request_slot()
    next(second)


def test_the_request_limit_stays_below_the_pool_so_other_requests_keep_headroom():
    assert 1 <= config.LLM_REQUEST_MAX <= max(1, config.DB_POOL_MAX // 2)


def test_every_model_client_has_a_timeout_instead_of_the_600_second_default(monkeypatch):
    from src.agent import conditions_agent
    from src.clients import llm_client

    monkeypatch.setattr(llm_client, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_client, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_client, "_client", None)
    client = llm_client._get_client()
    assert client.timeout == config.LLM_TIMEOUT_SECONDS
    assert client.with_options(timeout=config.LLM_VISION_TIMEOUT_SECONDS).timeout == config.LLM_VISION_TIMEOUT_SECONDS

    monkeypatch.setattr(conditions_agent, "OPENAI_API_KEY", "sk-test")
    assert conditions_agent._model().client_args["timeout"] == config.LLM_TIMEOUT_SECONDS


DSN = os.getenv("DATABASE_URL")


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
class TestHttp:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient

        from src.api import app
        from src.auth import ratelimit

        ratelimit.reset_all()
        yield TestClient(app)
        ratelimit.reset_all()

    def _session(self, client) -> str:
        sid = client.post("/session").json()["list_id"]
        client.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
        return sid

    def test_a_full_request_limit_answers_503_before_taking_a_db_connection(self, client, tight):
        tight(request=1)
        sid = self._session(client)
        gate = llm_guard.llm_request_slot()
        next(gate)                                # 자리를 하나뿐인 상한까지 채운다
        try:
            response = client.post(f"/session/{sid}/message", json={"text": "게임용 PC 예산 200만원"})
        finally:
            gate.close()
        assert response.status_code == 503, response.text
        assert response.headers["retry-after"] == "3"
        assert response.json()["error"]["code"] == "llm_busy"
        assert client.post(f"/session/{sid}/message", json={"text": "게임용 PC 예산 200만원"}).status_code == 200

    def test_the_conditions_chat_falls_back_to_rules_when_the_model_is_busy(self, client, monkeypatch):
        from src.agent import conditions_agent

        def busy(*_a, **_k):
            raise LLMBusy("busy")

        monkeypatch.setattr(conditions_agent, "available", lambda: True)
        monkeypatch.setattr(conditions_agent, "run_turn", busy)
        sid = self._session(client)
        state = client.post(f"/session/{sid}/message", json={"text": "게임용 PC 예산 200만원"}).json()
        fields = {f["key"]: f.get("value") for f in state["fields"]}
        assert fields.get("budget_max") == 2_000_000, state

    def test_polling_and_lists_do_not_take_a_request_slot(self, client, tight):
        tight(request=1)
        sid = self._session(client)
        gate = llm_guard.llm_request_slot()
        next(gate)
        try:
            assert client.get("/lists").status_code == 200
            assert client.get(f"/session/{sid}").status_code == 200
        finally:
            gate.close()
