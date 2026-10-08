"""추천 실행 전용 작업자 (2026-10-08, 1단계-2).

전에는 추천 실행이 요청과 같은 스레드 풀(40개)에서 `BackgroundTasks` 로 돌았다. 동시에 30건이 돌면 30개 스레드가 엔진 계산(CPU)과
DB 연결(풀 20개)을 한꺼번에 쥐어, 폴링·설명 저장 같은 다른 요청이 연결을 못 얻었다(503, 설명이 pending 으로 멈춤).
여기서는 두 작업자 풀로 나눈다.

  엔진 작업자(RECOMMEND_WORKERS, 기본 4)       — 엔진 [2]~[4] 계산과 저장. DB 연결을 쥔다. 넘치면 줄을 선다.
  설명 작업자(RECOMMEND_EXPLAIN_WORKERS, 기본 8) — [5] 설명 문장(LLM)과 임베딩 검색. DB 연결 없이 돌고, 저장할 때만 짧게 연다.

엔진 작업자는 설명 단계를 넘기고(`defer`) 바로 다음 실행으로 간다. 서버 프로세스마다 따로 센다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from src import config
from src.clients.llm_guard import llm_background
from src.services import recommendation_service

log = logging.getLogger(__name__)

_engine_pool = ThreadPoolExecutor(max_workers=max(1, config.RECOMMEND_WORKERS), thread_name_prefix="recommend")
_explain_pool = ThreadPoolExecutor(max_workers=max(1, config.RECOMMEND_EXPLAIN_WORKERS), thread_name_prefix="explain")


def dispatch(revision_id: UUID, run_id: UUID) -> None:
    """라우터가 응답을 보낸 뒤 부른다 — 작업자에게 넘기고 바로 돌아온다. RECOMMEND_SYNC=1 이면 이 자리에서 끝까지 돌린다(테스트)."""
    if config.RECOMMEND_SYNC:
        recommendation_service.execute_recommendation(revision_id, run_id)
        return
    _engine_pool.submit(_run_engine, revision_id, run_id)


def _run_engine(revision_id: UUID, run_id: UUID) -> None:
    try:
        recommendation_service.execute_recommendation(revision_id, run_id, defer=_defer_explanation)
    except Exception:  # noqa: BLE001 — 실패 표시는 execute_recommendation 이 이미 했다. 작업자는 계속 산다.
        log.exception("recommendation engine failed [run %s]", run_id)


def _defer_explanation(finish) -> None:
    _explain_pool.submit(_run_explanation, finish)


def _run_explanation(finish) -> None:
    with llm_background():
        try:
            finish()
        except Exception:  # noqa: BLE001 — 마무리 쓰기까지 실패했다면 reaper 가 나중에 실패로 정리한다
            log.exception("recommendation explanation failed")


def queue_depth() -> dict[str, int]:
    """줄 서 있는 실행 수 — 부하 관찰용."""
    return {"engine_waiting": _engine_pool._work_queue.qsize(), "explain_waiting": _explain_pool._work_queue.qsize()}
