"""LLM 호출 보호 — 동시 호출 상한과 요청 상한 (2026-10-08, 1단계-3).

모델 API 는 느리고(추천 설명 약 20초, 실시간 검색 약 20초) 분당 한도가 있다. 호출이 몰리면
  · 호출이 줄을 서는 동안 서버 스레드와 DB 연결이 묶이고(풀 고갈),
  · 한도(429)에 걸려 모두가 같이 실패한다.
그래서 두 가지 상한을 둔다. 둘 다 서버 프로세스마다 따로 센다.

`llm_call_slot()`   — 모델 호출 한 번을 감싼다. 동시 LLM_MAX_CONCURRENCY 개까지, 넘으면 LLM_QUEUE_TIMEOUT_SECONDS 까지 기다리고
                      그래도 자리가 없으면 LLMBusy. 호출 쪽은 이미 "실패하면 규칙 경로"로 짜여 있다.
`llm_request_slot`  — LLM 을 기다리며 DB 연결을 쥐는 HTTP 요청의 FastAPI 의존성. DB 연결을 잡기 *전에* 자리를 얻는다
                      (연결을 쥔 채 줄을 서면 의미가 없다). LLM_REQUEST_MAX 는 풀의 절반 아래라 나머지 요청이 막히지 않는다.
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from typing import Iterator

from src import config
from src.errors import LLMBusy

_call_slots = threading.BoundedSemaphore(config.LLM_MAX_CONCURRENCY)
_request_slots = threading.BoundedSemaphore(config.LLM_REQUEST_MAX)
_background = contextvars.ContextVar("llm_background", default=False)


@contextmanager
def llm_background() -> Iterator[None]:
    """사람이 기다리지 않는 백그라운드 작업(추천 설명 문장) — 모델 호출 자리를 LLM_BACKGROUND_QUEUE_TIMEOUT_SECONDS 까지 기다린다."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


@contextmanager
def llm_call_slot() -> Iterator[None]:
    wait = config.LLM_BACKGROUND_QUEUE_TIMEOUT_SECONDS if _background.get() else config.LLM_QUEUE_TIMEOUT_SECONDS
    if not _call_slots.acquire(timeout=wait):
        raise LLMBusy("지금 AI 응답을 기다리는 요청이 많아요. 잠시 뒤 다시 시도해 주세요.")
    try:
        yield
    finally:
        _call_slots.release()


def llm_request_slot() -> Iterator[None]:
    """FastAPI 의존성(`Depends(llm_request_slot)`) — 응답을 보낼 때까지 자리를 쥔다."""
    if not _request_slots.acquire(timeout=config.LLM_QUEUE_TIMEOUT_SECONDS):
        raise LLMBusy("지금 AI 응답을 기다리는 요청이 많아요. 잠시 뒤 다시 시도해 주세요.")
    try:
        yield
    finally:
        _request_slots.release()
