"""추천 실행 전용 작업자·멈춘 실행 정리 (2026-10-08, 1단계-2).

동시 추천 30건에서 구성이 22초 늘어지고, 설명이 pending 으로 영영 멈추고, 일부 요청이 503 이던 문제를 막는다.
  · 엔진 작업자는 정해진 수만 동시에 돌고 나머지는 줄을 선다(요청 스레드 풀을 쓰지 않는다)
  · 설명(LLM) 단계는 엔진 작업자를 붙잡지 않는다
  · 백그라운드 마무리 쓰기는 풀이 잠깐 막혀도 다시 시도한다
  · 재시작·유실로 끝나지 못한 실행은 reaper 가 실패로 정리한다
LLM 은 부르지 않는다(모의 모드).
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from psycopg_pool import PoolTimeout

from src import config
from src.clients import llm_guard
from src.errors import LLMBusy
from src.services import recommendation_runner as runner
from src.services import recommendation_service as service


@pytest.fixture()
def async_mode(monkeypatch):
    monkeypatch.setattr(config, "RECOMMEND_SYNC", False)


def _pools(monkeypatch, engine: int, explain: int = 4):
    monkeypatch.setattr(runner, "_engine_pool", ThreadPoolExecutor(max_workers=engine))
    monkeypatch.setattr(runner, "_explain_pool", ThreadPoolExecutor(max_workers=explain))


def test_engine_runs_are_limited_to_the_worker_count_and_the_rest_wait(monkeypatch, async_mode):
    _pools(monkeypatch, engine=2)
    running, peak, done, lock = 0, 0, [], threading.Lock()

    def fake(revision_id, run_id, *, defer=None):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
            done.append(run_id)

    monkeypatch.setattr(service, "execute_recommendation", fake)
    for i in range(8):
        runner.dispatch(uuid4(), i)
    deadline = time.time() + 5
    while len(done) < 8 and time.time() < deadline:
        time.sleep(0.02)
    assert sorted(done) == list(range(8)) and peak == 2


def test_a_slow_explanation_does_not_hold_the_engine_worker(monkeypatch, async_mode):
    """엔진 작업자가 1명뿐이어도, 앞 실행의 설명(LLM)이 끝나기 전에 다음 실행의 엔진 단계가 돈다."""
    _pools(monkeypatch, engine=1)
    release, engine_done, explained = threading.Event(), [], []

    def fake(revision_id, run_id, *, defer=None):
        engine_done.append(run_id)
        defer(lambda: (release.wait(5), explained.append(run_id)))

    monkeypatch.setattr(service, "execute_recommendation", fake)
    runner.dispatch(uuid4(), "a")
    runner.dispatch(uuid4(), "b")
    deadline = time.time() + 3
    while len(engine_done) < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert engine_done == ["a", "b"] and explained == []          # 설명은 아직 안 끝났는데 두 엔진 단계가 다 돌았다
    release.set()
    deadline = time.time() + 3
    while len(explained) < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert sorted(explained) == ["a", "b"]


def test_one_failed_run_does_not_kill_the_worker(monkeypatch, async_mode):
    _pools(monkeypatch, engine=1)
    done = []

    def fake(revision_id, run_id, *, defer=None):
        if run_id == "boom":
            raise RuntimeError("engine failure")
        done.append(run_id)

    monkeypatch.setattr(service, "execute_recommendation", fake)
    runner.dispatch(uuid4(), "boom")
    runner.dispatch(uuid4(), "ok")
    deadline = time.time() + 3
    while not done and time.time() < deadline:
        time.sleep(0.02)
    assert done == ["ok"]


def test_background_explanations_wait_longer_for_a_model_slot_than_people_do(monkeypatch):
    monkeypatch.setattr(config, "LLM_QUEUE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(config, "LLM_BACKGROUND_QUEUE_TIMEOUT_SECONDS", 0.4)
    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(llm_guard, "_call_slots", full)

    started = time.perf_counter()
    with pytest.raises(LLMBusy):
        with llm_guard.llm_call_slot():
            pass
    assert time.perf_counter() - started < 0.3

    threading.Timer(0.15, full.release).start()          # 0.15초 뒤 자리가 난다
    with llm_guard.llm_background():
        with llm_guard.llm_call_slot():                  # 사람보다 오래 기다려 자리를 얻는다
            pass


def test_retry_on_pool_timeout_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(service.time, "sleep", lambda _s: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise PoolTimeout("busy")
        return "saved"

    assert service._retry_on_pool_timeout(flaky) == "saved" and len(calls) == 3

    always = []

    def never():
        always.append(1)
        raise PoolTimeout("busy")

    with pytest.raises(PoolTimeout):
        service._retry_on_pool_timeout(never, attempts=4)
    assert len(always) == 4


DSN = os.getenv("DATABASE_URL")

if DSN:
    from tests.test_list_history_http import _recommended_list, _signed_up


@pytest.mark.db
@pytest.mark.skipif(not DSN, reason="일회용 DB 필요")
class TestWithDatabase:
    def test_a_pool_timeout_while_saving_the_explanation_is_retried_not_lost(self, monkeypatch):
        """설명 저장 순간 풀이 막혀도(PoolTimeout) 다시 시도해서 설명이 ready 로 끝난다 — 전에는 pending 으로 영영 남았다."""
        import src.db as db

        monkeypatch.setattr(service.time, "sleep", lambda _s: None)
        real, count = db.get_background_conn, {"n": 0}

        def flaky_get_conn():
            count["n"] += 1
            if count["n"] == 2:            # 1: 엔진 단계 저장, 2: 설명 저장 — 한 번 막힌다
                raise PoolTimeout("busy")
            return real()

        monkeypatch.setattr(db, "get_background_conn", flaky_get_conn)
        client = _signed_up()
        _lid, _rev, data = _recommended_list(client)
        assert data["explanation"]["status"] == "ready", data["explanation"]
        assert count["n"] >= 3

    def test_the_reaper_fails_runs_that_never_finished_and_leaves_recent_ones(self, monkeypatch):
        import psycopg

        client = _signed_up()
        lid, _rev, data = _recommended_list(client)
        run_id = data["run_id"]
        with psycopg.connect(DSN, autocommit=True) as raw:
            # 설명이 오래 pending 으로 남은 완료 실행을 만든다
            raw.execute("UPDATE engine.recommendation_candidate SET reason=NULL, reason_status='pending', checks=NULL, checks_status='pending' WHERE run_id=%s", (run_id,))
            raw.execute("UPDATE engine.recommendation_run SET explanation_status='pending', explanation_headline=NULL, explanation_text=NULL, "
                        "completed_at=now() - interval '2 hours' WHERE id=%s", (run_id,))
            # 엔진 단계가 끝나지 못하고 running 으로 남은 실행(오래된 것 / 방금 시작한 것)
            old_lid, _r, _d = _recommended_list(client)
            young_lid, _r2, _d2 = _recommended_list(client)
            old_run = client.get(f"/session/{old_lid}/result").json()["run_id"]
            young_run = client.get(f"/session/{young_lid}/result").json()["run_id"]
            raw.execute("UPDATE engine.recommendation_candidate SET reason=NULL, reason_status='pending', checks=NULL, checks_status='pending' WHERE run_id IN (%s,%s)", (old_run, young_run))
            raw.execute("UPDATE engine.recommendation_run SET status='running', completed_at=NULL, explanation_status='pending', explanation_headline=NULL, "
                        "explanation_text=NULL, created_at=now() - interval '2 hours' WHERE id=%s", (old_run,))
            raw.execute("UPDATE engine.recommendation_run SET status='running', completed_at=NULL, explanation_status='pending', explanation_headline=NULL, "
                        "explanation_text=NULL WHERE id=%s", (young_run,))

        result = service.reap_stale_runs(600)
        assert result["running_failed"] >= 1 and result["explanation_failed"] >= 1

        with psycopg.connect(DSN, autocommit=True) as raw:
            def row(rid):
                return raw.execute("SELECT status, explanation_status FROM engine.recommendation_run WHERE id=%s", (rid,)).fetchone()
            assert row(run_id) == ("completed", "failed")                  # 부품표(completed)는 두고 설명만 실패로
            assert row(old_run)[0] == "failed"                             # 오래된 running 은 실패로
            assert row(young_run) == ("running", "pending")                # 방금 시작한 것은 그대로
            stuck = raw.execute("SELECT count(*) FROM engine.recommendation_candidate WHERE run_id=%s AND (reason_status='pending' OR checks_status='pending')",
                                (run_id,)).fetchone()[0]
            assert stuck == 0
        assert client.get(f"/session/{lid}/result").json()["explanation"]["status"] == "failed"
