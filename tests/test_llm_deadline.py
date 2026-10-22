"""설명 문장·세트 검증 쟁점 문장(LLM)의 시간 예산 — JSON 재생성·의미 재생성·HTTP 재시도(일시적 오류만)와 동시 호출 자리 대기를
한 예산 안에서 쓰고, 넘기면 규칙 문장으로 내려간다.

실제 API 를 부르지 않는다. 가짜 OpenAI 클라이언트로 요청마다 받은 제한 시간·재시도 설정과 호출 횟수를 본다.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import openai
import pytest

from src.clients import llm_client


class FakeClient:
    """with_options 로 받은 설정을 기록하고, 정해 둔 응답을 차례로 돌려준다."""

    def __init__(self, contents, delay: float = 0.0):
        self.contents = list(contents)
        self.delay = delay
        self.options: list[dict] = []
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **options):
        self.options.append(options)
        return self

    def _create(self, **_kwargs):
        self.calls += 1
        time.sleep(self.delay)
        content = self.contents.pop(0) if self.contents else "{}"
        if isinstance(content, Exception):           # 요청 오류를 차례에 끼워 넣는다
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


_REQUEST = httpx.Request("POST", "https://api.openai.invalid/v1/chat/completions")


def _status_error(cls, status: int, headers: dict | None = None):
    return cls("주입한 오류", response=httpx.Response(status, headers=headers or {}, request=_REQUEST), body=None)


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """재시도 대기를 실제로 자지 않고 기록한다(llm_client 가 보는 time 만 바꾼다)."""
    waited: list[float] = []
    monkeypatch.setattr(llm_client, "time", SimpleNamespace(monotonic=time.monotonic, sleep=waited.append))
    return waited


@pytest.fixture
def fake(monkeypatch):
    def install(contents, delay: float = 0.0) -> FakeClient:
        client = FakeClient(contents, delay)
        monkeypatch.setattr(llm_client, "_get_client", lambda: client)
        return client
    return install


def test_with_a_deadline_each_request_gets_the_remaining_time_and_no_sdk_retries(fake):
    client = fake(['{"ok": 1}'])
    deadline = time.monotonic() + 5
    assert llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m", deadline=deadline) == {"ok": 1}
    assert len(client.options) == 1
    assert client.options[0]["max_retries"] == 0
    assert 0 < client.options[0]["timeout"] <= min(5, llm_client.LLM_REQUEST_TIMEOUT_S)


def test_without_a_deadline_the_client_defaults_are_kept(fake):
    client = fake(['{"ok": 1}'])
    assert llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m") == {"ok": 1}
    assert client.options == []          # 다른 기능(대화·이미지 추출 등)의 호출은 바뀌지 않는다


def test_a_spent_deadline_stops_before_calling_the_api(fake):
    client = fake(['{"ok": 1}'])
    with pytest.raises(TimeoutError):
        llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m", deadline=time.monotonic() - 1)
    assert client.calls == 0


def test_json_retry_does_not_start_after_the_deadline(fake):
    # 첫 응답이 JSON 이 아니고 그 사이 예산을 다 썼으면 두 번째 요청을 보내지 않는다
    client = fake(["not json", '{"ok": 1}'], delay=0.2)
    with pytest.raises(TimeoutError):
        llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m",
                                deadline=time.monotonic() + 0.1)
    assert client.calls == 1


def _schema_call(deadline: float):
    return llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m", deadline=deadline)


def test_transient_errors_are_retried_within_the_deadline(fake, sleeps):
    # SDK 재시도를 껐으므로 일시적 오류(사용량 제한·연결 끊김)는 여기서 다시 보낸다 — 예전엔 한 번에 규칙 문장으로 내려갔다
    client = fake([_status_error(openai.RateLimitError, 429), openai.APIConnectionError(request=_REQUEST), '{"ok": 1}'])
    assert _schema_call(time.monotonic() + 30) == {"ok": 1}
    assert client.calls == 3
    assert sleeps == list(llm_client._RETRY_BACKOFF_S)
    assert all(option["max_retries"] == 0 for option in client.options)


@pytest.mark.parametrize("error", [
    openai.APITimeoutError(request=_REQUEST),
    _status_error(openai.InternalServerError, 500),
    _status_error(openai.APIStatusError, 503),
    _status_error(openai.APIStatusError, 408),
    _status_error(openai.ConflictError, 409),
    _status_error(openai.BadRequestError, 400, {"x-should-retry": "true"}),
])
def test_retryable_errors_match_the_sdk_defaults(fake, sleeps, error):
    client = fake([error, '{"ok": 1}'])
    assert _schema_call(time.monotonic() + 30) == {"ok": 1}
    assert client.calls == 2


@pytest.mark.parametrize("error", [
    _status_error(openai.BadRequestError, 400),
    _status_error(openai.AuthenticationError, 401),
    _status_error(openai.NotFoundError, 404),
    _status_error(openai.InternalServerError, 500, {"x-should-retry": "false"}),
    ValueError("요청 오류가 아닌 예외"),
])
def test_permanent_errors_are_not_retried(fake, sleeps, error):
    client = fake([error, '{"ok": 1}'])
    with pytest.raises(type(error)):
        _schema_call(time.monotonic() + 30)
    assert client.calls == 1 and sleeps == []


def test_retries_stop_after_two_and_raise_the_last_error(fake, sleeps):
    client = fake([_status_error(openai.InternalServerError, 500) for _ in range(4)])
    with pytest.raises(openai.InternalServerError):
        _schema_call(time.monotonic() + 30)
    assert client.calls == 1 + llm_client._HTTP_RETRIES


def test_retry_after_header_is_respected(fake, sleeps):
    client = fake([_status_error(openai.RateLimitError, 429, {"retry-after": "3"}), '{"ok": 1}'])
    assert _schema_call(time.monotonic() + 30) == {"ok": 1}
    assert sleeps == [3.0] and client.calls == 2


def test_no_retry_when_the_wait_would_leave_too_little_time(fake, sleeps):
    # 남은 예산이 대기 + 최소 요청 시간보다 짧으면 다시 보내지 않고 원래 오류를 낸다 → 호출자가 규칙 문장을 쓴다
    client = fake([_status_error(openai.RateLimitError, 429, {"retry-after": "10"}), '{"ok": 1}'])
    with pytest.raises(openai.RateLimitError):
        _schema_call(time.monotonic() + 5)
    assert client.calls == 1 and sleeps == []


def test_a_retry_gets_only_the_remaining_time(fake, sleeps):
    client = fake([openai.APITimeoutError(request=_REQUEST), '{"ok": 1}'])
    deadline = time.monotonic() + 8
    assert _schema_call(deadline) == {"ok": 1}
    assert [round(o["timeout"]) for o in client.options] == [8, 8]
    assert all(o["timeout"] <= 8 for o in client.options)


def test_explanation_records_why_it_fell_back(monkeypatch):
    from src.engine import stage5_explain

    def rate_limited(*_args, **_kwargs):
        raise _status_error(openai.RateLimitError, 429)

    monkeypatch.setattr(stage5_explain, "call_llm", rate_limited)
    build = SimpleNamespace(items=[], budget={"max": 1}, totals={"price": 0}, list_id="x")
    outcome: dict = {}
    assert stage5_explain._llm_draft(build, SimpleNamespace(targets=[]), None, lambda _m: None, outcome=outcome) is None
    assert outcome == {"reason": "RateLimitError"}


def test_explanation_falls_back_to_rule_sentences_when_the_budget_runs_out(monkeypatch):
    from src.engine import stage5_explain

    seen: list = []

    def timed_out(*_args, **kwargs):
        seen.append(kwargs.get("deadline"))
        raise TimeoutError("call_llm: 시간 예산을 다 썼습니다")

    monkeypatch.setattr(stage5_explain, "call_llm", timed_out)
    build = SimpleNamespace(items=[], budget={"max": 1_000_000}, totals={"price": 0}, list_id="x")
    verification = SimpleNamespace(targets=[])
    logs: list[str] = []
    assert stage5_explain._llm_draft(build, verification, None, logs.append) is None     # → 호출자가 규칙 문장을 쓴다
    assert len(seen) == 1 and seen[0] is not None
    assert 0 < seen[0] - time.monotonic() <= stage5_explain.EXPLANATION_DEADLINE_S
    assert any("TimeoutError" in line for line in logs)


def test_explanation_retries_share_one_deadline(monkeypatch):
    from src.engine import stage5_explain

    deadlines: list = []

    def wrong_slots(*_args, **kwargs):          # 의미 검사 불통과 → 한 번 더 부른다
        deadlines.append(kwargs["deadline"])
        return json.loads('{"headline": "h", "summary": "s", "items": []}')

    monkeypatch.setattr(stage5_explain, "call_llm", wrong_slots)
    item = SimpleNamespace(slot="CPU", name="cpu", price=1, rank_from_3b=1, qty=1, product_key="k")
    build = SimpleNamespace(items=[item], budget={"max": 1}, totals={"price": 1}, list_id="x")
    outcome: dict = {}
    assert stage5_explain._llm_draft(build, SimpleNamespace(targets=[]), None, lambda _m: None, outcome=outcome) is None
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]
    assert outcome == {"reason": "check_rejected"}            # 재생성해도 검사 불통과


# ── 세트 검증 쟁점 문장(LLM) 시간 예산 — 부품표 저장 트랜잭션·교체 요청 안에서 DB 연결·행 잠금을 쥔 채 돌므로 짧게 끝낸다 ──

def test_the_call_slot_wait_is_capped_by_max_wait(monkeypatch):
    """동시 호출 자리가 모두 찼을 때, 시간 예산이 있는 호출은 남은 시간보다 오래 줄 서지 않는다(기본 대기 10초·120초 대신)."""
    import threading

    from src.clients import llm_guard
    from src.errors import LLMBusy

    monkeypatch.setattr(llm_guard, "_call_slots", threading.BoundedSemaphore(1))
    llm_guard._call_slots.acquire()                       # 자리를 모두 쓴 상태
    started = time.monotonic()
    with pytest.raises(LLMBusy):
        with llm_guard.llm_call_slot(max_wait=0.05):
            pass
    assert time.monotonic() - started < 1


def test_a_deadline_call_gives_up_on_a_full_slot_queue_within_its_budget(fake, monkeypatch):
    import threading

    from src.clients import llm_guard
    from src.errors import LLMBusy

    client = fake(['{"ok": 1}'])
    monkeypatch.setattr(llm_guard, "_call_slots", threading.BoundedSemaphore(1))
    llm_guard._call_slots.acquire()
    started = time.monotonic()
    with pytest.raises(LLMBusy):
        llm_client._call_openai("p", system=None, output_schema={"type": "object"}, model="m",
                                deadline=time.monotonic() + 0.2)
    assert time.monotonic() - started < 2 and client.calls == 0


def test_an_issue_sentence_past_its_deadline_falls_back_to_the_rule_sentence_without_calling(fake, monkeypatch):
    from src.engine import stage3c_verify

    client = fake([])
    monkeypatch.setattr(llm_client, "MOCK_MODE", False)
    text = stage3c_verify._issue_sentence("socket", "fail", [], deadline=time.monotonic() - 1)
    assert text == stage3c_verify._rule_sentence("socket", "fail")
    assert client.calls == 0


def test_verify_build_shares_one_issue_sentence_deadline_across_its_issues(monkeypatch):
    from src.config import ISSUE_SENTENCE_DEADLINE_S
    from src.dto import BuildResult
    from src.engine import stage3c_verify

    seen: list[float | None] = []

    def record(prompt, **kwargs):
        seen.append(kwargs.get("deadline"))
        return {"text": "관측값을 그대로 옮긴 문장입니다."}

    monkeypatch.setattr(stage3c_verify, "call_llm", record)
    before = time.monotonic()
    build = BuildResult(list_id="t", link_check={"socket": "fail", "power": "fail", "budget": "fail"},
                        budget={"max": 100, "used": 150, "used_pct": 150.0})
    result = stage3c_verify.verify_build(build, "computer")

    issues = result.targets[0].issues
    # 예산 초과 쟁점은 고정 문장이라 LLM 을 부르지 않는다(98783e1a) — 모델 문장은 소켓·전원 두 건이다.
    assert len(issues) == 3 and len(seen) == 2
    assert next(i for i in issues if i.axis == "budget").text == "예산이 초과되었습니다."
    assert len(set(seen)) == 1                                  # 두 쟁점이 같은 예산을 나눠 쓴다
    assert before < seen[0] <= time.monotonic() + ISSUE_SENTENCE_DEADLINE_S
