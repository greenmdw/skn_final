"""후처리(설명 문장·사용 가이드)와 부품 교체가 서로의 저장을 망가뜨리지 않는다 — 교체·조건부 갱신·트랜잭션·계측 로그.

부품표는 첫 트랜잭션에서 먼저 커밋돼 done 이 되고, 설명 문장(LLM)과 사용 가이드는 그 뒤 설명 단계(finish_explanation)에서
채워진다. 이 파일은 그 경계에서 지켜야 할 것만 본다.
- 교체하면 이전 상품의 사용 가이드를 비운다(guide_status 는 unavailable).
- 후보 행의 이유·가이드 갱신은 variant_id 를 주면 그 상품을 가리키는 행에만 쓴다(EngineRepo 의 조건부 갱신).
- 설명 LLM 을 기다리는 동안 DB 트랜잭션을 열어 두지 않는다.
- 부품표 확정 시 core_ready 계측 로그를 run_id 와 함께 남긴다.

(develop 병합 때 설명 단계는 develop 의 방식 — 설명 작업자에 넘기는 finish_explanation — 을 따랐다. 그래서 설명·가이드 동시 실행,
후처리 중 교체 경쟁 안내, explained·post_done 로그를 검사하던 테스트는 이 파일에서 뺐다.)

tests/test_result_interaction.py 와 같은 전제(일회용 PostgreSQL, db/setup_all.py 로 카탈로그 seed).
"""
from __future__ import annotations

import logging
import re
import time
import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.db import get_conn
from src.engine import stage5_explain
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service as rs, session_service

pytestmark = pytest.mark.db

SERVICE_LOGGER = "src.services.recommendation_service"
SWAP_NOTE = "이 요약은 교체 전 구성 기준입니다"
STEP_TIMEOUT_S = 60      # Event 대기·잠금 대기·join 의 상한 — 넘으면 멈춘 채 매달리지 않고 실패한다


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        ok = connection.execute("SELECT to_regclass('config.domain_version') IS NOT NULL").fetchone()[0]
        if not (ok and connection.execute("SELECT count(*) FROM catalog.cpu_spec").fetchone()[0] > 0):
            pytest.skip("PC 카탈로그가 seed 되지 않았습니다 — db/setup_all.py로 준비하세요.")
        yield connection
    finally:
        connection.close()


def _accepted_run(conn) -> tuple[uuid.UUID, uuid.UUID]:
    """조건을 채우고 추천을 접수까지만 한다(run 이 running). 엔진 실행은 호출한 쪽이 한다."""
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 1_500_000), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = rs.start_recommendation(conn, revision_id, strategy="default")
    return revision_id, uuid.UUID(accepted["run_id"])


def _rows(conn, run_id) -> dict[str, dict]:
    return {row["slot"]: row for row in EngineRepo(conn).get_candidates(run_id)}


def _first_swappable(other, revision_id, run_id) -> tuple[dict, dict]:
    """교체할 대안이 있는 첫 부품(후보 행)과 그 대안 하나."""
    for row in EngineRepo(other).get_candidates(run_id):
        target = next((a for a in rs.list_alternatives(other, revision_id, row["id"])["items"] if not a["current"]), None)
        if target is not None:
            return row, target
    raise AssertionError("교체할 대안이 있는 부품이 하나는 있어야 한다")


def test_without_a_swap_the_summary_has_no_swap_note(conn):
    revision_id, run_id = _accepted_run(conn)
    rs.execute_recommendation(revision_id, run_id)

    result = rs.get_stored_result(conn, revision_id)
    assert result["explanation"]["status"] == "ready" and SWAP_NOTE not in result["explanation"]["text"]
    assert all(row["reason_status"] == "ready" and row["checks_status"] == "ready" for row in _rows(conn, run_id).values())


def test_swap_clears_the_usage_guide_of_the_previous_product(conn):
    revision_id, run_id = _accepted_run(conn)
    rs.execute_recommendation(revision_id, run_id)
    row = next(r for r in EngineRepo(conn).get_candidates(run_id) if r["slot"] == "GPU")
    assert row["checks_status"] == "ready" and row["checks"], "교체 전에는 사용 가이드가 있어야 이 검사가 의미가 있다"
    target = next(a for a in rs.list_alternatives(conn, revision_id, row["id"])["items"] if not a["current"])

    swapped = rs.swap_item(conn, revision_id, row["id"], uuid.UUID(target["candidate_id"]))

    after = _rows(conn, run_id)["GPU"]
    assert after["variant_id"] == uuid.UUID(target["candidate_id"])
    assert after["checks"] is None and after["checks_status"] == "pending"
    item = next(i for i in swapped["items"] if i["slot"] == "GPU")
    assert "사용 가이드:" not in item["checks"]["text"]                  # 코드가 아는 사실(검증 쟁점·교체 안내)만 남는다
    assert "교체한 부품" in item["checks"]["text"]
    other = next(i for i in swapped["items"] if i["slot"] == "CPU")
    assert "사용 가이드:" in other["checks"]["text"]                     # 교체하지 않은 부품은 그대로
    # 가이드 진행 상태: 바꾼 부품은 후처리가 채우지 않으므로 기다릴 것이 없는 unavailable, 나머지는 ready
    assert item["guide_status"] == "unavailable" and other["guide_status"] == "ready"


def test_conditional_candidate_updates_only_touch_rows_still_pointing_at_the_product(conn):
    revision_id, run_id = _accepted_run(conn)
    rs.execute_recommendation(revision_id, run_id)
    repo = EngineRepo(conn)
    row = next(r for r in repo.get_candidates(run_id) if r["slot"] == "GPU")
    target = next(a for a in rs.list_alternatives(conn, revision_id, row["id"])["items"] if not a["current"])
    repo.update_candidate_variant(row["id"], variant_id=uuid.UUID(target["candidate_id"]), offer_observation_id=None)
    pending_swap = next(r for r in repo.get_candidates(run_id) if r["slot"] == "GPU")
    assert pending_swap["reason_status"] == "pending" and pending_swap["checks_status"] == "pending"

    # 원래 상품(old)을 기준으로 쓰려는 후처리 — 이미 다른 상품을 가리키는 행이라 아무것도 쓰지 않는다
    assert repo.update_candidate_reason(row["id"], "이전 상품의 이유", variant_id=row["variant_id"]) is False
    assert repo.update_candidate_checks(row["id"], "이전 상품의 가이드", variant_id=row["variant_id"]) is False
    assert repo.fail_candidate_reason(row["id"], variant_id=row["variant_id"]) is False
    assert repo.fail_candidate_checks(row["id"], variant_id=row["variant_id"]) is False
    after = next(r for r in repo.get_candidates(run_id) if r["slot"] == "GPU")
    assert (after["reason"], after["reason_status"], after["checks"], after["checks_status"]) == (None, "pending", None, "pending")

    # 지금 상품 기준이면 쓴다. variant_id 를 안 주는 기존 호출(swap_item 의 교체 문장 저장)도 그대로 쓴다.
    now_variant = uuid.UUID(target["candidate_id"])
    assert repo.update_candidate_reason(row["id"], "지금 상품의 이유", variant_id=now_variant) is True
    assert repo.update_candidate_checks(row["id"], "지금 상품의 가이드", variant_id=now_variant) is True
    assert repo.update_candidate_reason(row["id"], "variant 를 안 준 갱신") is True
    after = next(r for r in repo.get_candidates(run_id) if r["slot"] == "GPU")
    assert (after["reason"], after["reason_status"]) == ("variant 를 안 준 갱신", "ready")
    assert (after["checks"], after["checks_status"]) == ("지금 상품의 가이드", "ready")

    # ready 가 된 행은 failed 로 바꾸지 않는다(제약 위반 없이 False)
    assert repo.fail_candidate_reason(row["id"]) is False and repo.fail_candidate_checks(row["id"]) is False
    after = next(r for r in repo.get_candidates(run_id) if r["slot"] == "GPU")
    assert after["reason_status"] == "ready" and after["checks_status"] == "ready"


def test_execute_recommendation_logs_stage_timings_with_the_run_id(conn, caplog):
    revision_id, run_id = _accepted_run(conn)
    caplog.set_level(logging.INFO, logger=SERVICE_LOGGER)

    rs.execute_recommendation(revision_id, run_id)

    messages = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    core = [m for m in messages if m.startswith("recommendation core_ready")]
    assert len(core) == 1
    assert re.fullmatch(rf"recommendation core_ready run_id={run_id} core_ms=\d+", core[0])
    assert not [m for m in messages if m.startswith("recommendation ") and "failed" in m]


def _transactions_in_progress(conn, since) -> int:
    """since 이후에 시작해 지금 트랜잭션을 연 채 쉬고 있는(외부 호출을 기다리는) 다른 연결 수. 다른 테스트가 남긴 연결은 세지 않는다."""
    return conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() "
        "AND state LIKE 'idle in transaction%%' AND xact_start >= %s", (since,)).fetchone()[0]


def test_no_transaction_or_row_lock_is_held_while_the_explanation_llm_runs(conn, monkeypatch):
    """설명 LLM 을 기다리는 동안 후처리는 DB 트랜잭션을 열어 두지 않는다(예전엔 BEGIN 한 채로 LLM·임베딩을 기다려 커넥션을 쥐었다).
    그래서 그 사이의 교체는 잠금에 막히지 않고 바로 끝난다."""
    revision_id, run_id = _accepted_run(conn)
    since = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    observed: dict = {}
    real_run = stage5_explain.run

    def observing_run(*args, **kwargs):
        # 동시에 도는 가이드 스레드의 짧은 저장 트랜잭션은 세지 않도록 가이드가 저장될 때까지 기다린 뒤 센다.
        deadline = time.monotonic() + STEP_TIMEOUT_S
        while time.monotonic() < deadline and not all(r["checks_status"] == "ready" for r in _rows(conn, run_id).values()):
            time.sleep(0.05)
        observed["open_transactions"] = _transactions_in_progress(conn, since)
        started = time.perf_counter()
        with get_conn() as other:
            row, target = _first_swappable(other, revision_id, run_id)
            rs.swap_item(other, revision_id, row["id"], uuid.UUID(target["candidate_id"]))
        observed["swap_s"] = time.perf_counter() - started
        return real_run(*args, **kwargs)

    monkeypatch.setattr(stage5_explain, "run", observing_run)
    rs.execute_recommendation(revision_id, run_id)

    assert observed["open_transactions"] == 0
    assert observed["swap_s"] < 10        # 잠금 대기가 없다(같은 프로세스·로컬 DB 기준 넉넉한 상한)
    assert EngineRepo(conn).get_run(run_id)["explanation_status"] == "ready"


