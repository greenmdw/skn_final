"""후처리(설명 문장·사용 가이드) 도중 부품을 교체해도 이전 상품의 이유·가이드가 새 상품에 붙지 않는다.

부품표는 첫 트랜잭션에서 먼저 커밋돼 done 이 되고, 설명 문장(LLM)과 사용 가이드는 트랜잭션 밖에서 동시에 만든 뒤 각자 짧은
트랜잭션으로 뒤따라 채워진다. 화면이 done 에서 표를 보여 주면(프론트 요청 1, 지금 화면도 20초 유예 뒤에는) 그 사이 사용자가
부품을 교체할 수 있다. 이 테스트는 설명 단계(stage5_explain.run)가 끝나는 순간 — 이유 저장 트랜잭션이 아직 후보 행을 쓰기 전이라
잠금 충돌이 없다 — 별도 DB 연결로 교체를 끼워 넣어 그 경쟁을 재현한다. 모의 LLM(MOCK_MODE=1)이라 설명은 규칙 문장, 임베딩은
해시로 돈다.

후처리는 이유·요약을 저장하는 짧은 트랜잭션 동안(이유 UPDATE 부터 커밋까지) 후보 행의 잠금을 쥔다 — 외부 호출(LLM·가이드 검색)을
기다리는 동안은 쥐지 않는다. 그 동안 들어온 교체는 잠금이 풀릴 때까지 기다리고, 반대로 교체가 먼저 행을 잠그면 후처리가 기다린다.
두 순서 모두 요약에 "교체 전 구성 기준" 안내가 한 번만 남아야 한다 —
스레드·Event 로 순서를 만들고, 막혔는지는 sleep 이 아니라 pg_stat_activity 의 잠금 대기로 확인한다.

tests/test_result_interaction.py 와 같은 전제(일회용 PostgreSQL, db/setup_all.py 로 카탈로그 seed).
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.db import get_conn
from src.engine import stage5_explain
from src.rag import care_guides
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service as rs, session_service
from src.services.recommendation_review_snapshot import SNAPSHOT_STEP

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


def _in_thread(fn) -> tuple[threading.Thread, dict]:
    """fn 을 스레드로 시작한다. 스레드 안의 예외는 삼켜지므로 box["error"] 에 담아 테스트가 확인한다(결과는 box["value"])."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — 테스트 스레드의 어떤 실패도 메인 스레드가 보게 한다
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def _wait_until_blocked(conn, statement_prefix: str) -> None:
    """statement_prefix 로 시작하는 문장을 실행 중인 DB 세션이 다른 세션의 잠금에 막혀 기다리는 것이 보일 때까지 기다린다.
    고정 sleep 으로 "막혔을 것"이라 짐작하지 않는다 — 막혔는지를 DB 에 직접 묻는다."""
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        blocked = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND cardinality(pg_blocking_pids(pid)) > 0 AND starts_with(query, %s)", (statement_prefix,),
        ).fetchone()[0]
        if blocked:
            return
        time.sleep(0.05)
    raise AssertionError(f"{statement_prefix!r} 문장이 {STEP_TIMEOUT_S}초 안에 잠금 대기 상태가 되지 않았다")


def _swap_when_explained(monkeypatch, revision_id, run_id, *, then_raise: bool = False) -> dict:
    """stage5_explain.run 을 감싼다 — 설명을 다 만든 직후(반환 직전)에 별도 DB 연결로 한 부품을 다른 후보로 교체한다.
    then_raise 면 교체한 뒤 예외를 던져 후처리 실패를 만든다. 끼워 넣은 교체의 내용을 담은 dict 를 돌려준다(실행 뒤에 채워진다)."""
    real_run = stage5_explain.run
    info: dict = {}

    def run_then_swap(*args, **kwargs):
        explanation = real_run(*args, **kwargs)
        with get_conn() as other:     # 풀의 다른 연결 — 후처리 트랜잭션과 별개다
            row, target = _first_swappable(other, revision_id, run_id)
            rs.swap_item(other, revision_id, row["id"], uuid.UUID(target["candidate_id"]))
        info.update(
            slot=row["slot"], item_id=row["id"], old_variant=row["variant_id"], old_name=row["product_name"],
            new_variant=uuid.UUID(target["candidate_id"]), new_name=target["product"]["name"],
            explained={item.slot: item.reason for item in explanation.items},
        )
        if then_raise:
            raise RuntimeError("후처리 실패 주입")
        return explanation

    monkeypatch.setattr(stage5_explain, "run", run_then_swap)
    return info


def test_swap_during_postprocess_keeps_the_swap_sentence_and_does_not_take_the_old_guide(conn, monkeypatch):
    revision_id, run_id = _accepted_run(conn)
    info = _swap_when_explained(monkeypatch, revision_id, run_id)

    rs.execute_recommendation(revision_id, run_id)

    rows = _rows(conn, run_id)
    swapped = rows[info["slot"]]
    # 교체된 부품: 교체한 상품 그대로, 이유는 교체 문장 그대로(설명 단계의 문장이 덮어쓰지 않았다)
    assert swapped["variant_id"] == info["new_variant"] and swapped["variant_id"] != info["old_variant"]
    assert swapped["reason_status"] == "ready" and swapped["reason"].startswith(rs._SWAP_REASON_PREFIX)
    assert swapped["reason"] != info["explained"][info["slot"]]
    # 교체된 부품의 사용 가이드: 이전 상품의 것이 아니다(교체가 비웠고, 늦게 온 후처리도 채우지 않았다)
    assert swapped["checks"] is None and swapped["checks_status"] == "pending"
    # 나머지 부품: 설명 단계의 이유와 사용 가이드가 채워졌다
    others = [row for slot, row in rows.items() if slot != info["slot"]]
    assert len(others) == len(rows) - 1 and others
    for row in others:
        assert row["reason_status"] == "ready" and row["reason"] == info["explained"][row["slot"]]
        assert row["checks_status"] == "ready" and row["checks"]

    result = rs.get_stored_result(conn, revision_id)
    by_slot = {item["slot"]: item for item in result["items"]}
    assert "사용 가이드:" not in by_slot[info["slot"]]["checks"]["text"]
    assert all("사용 가이드:" in by_slot[row["slot"]]["checks"]["text"] for row in others)
    # 요약: 교체 전 구성 기준이라는 안내가 붙었다
    assert result["explanation"]["status"] == "ready"
    assert SWAP_NOTE in result["explanation"]["text"] and info["new_name"] in result["explanation"]["text"]


def test_without_a_swap_the_summary_has_no_swap_note(conn):
    revision_id, run_id = _accepted_run(conn)
    rs.execute_recommendation(revision_id, run_id)

    result = rs.get_stored_result(conn, revision_id)
    assert result["explanation"]["status"] == "ready" and SWAP_NOTE not in result["explanation"]["text"]
    assert all(row["reason_status"] == "ready" and row["checks_status"] == "ready" for row in _rows(conn, run_id).values())


def test_swap_blocked_by_the_postprocess_row_lock_still_adds_the_summary_note(conn, monkeypatch):
    """후처리는 이유·요약을 저장하는 짧은 트랜잭션 동안 후보 행의 잠금을 쥔다. 그 동안 들어온 교체는 잠금이 풀릴 때까지 기다리고,
    기다리는 사이 요약이 만들어진다(설명 pending → ready). 교체 안내는 기다리기 전에 읽은 run 이 아니라 잠금을 얻은 뒤 다시 읽은 run 으로
    정해야 한다 — 안 그러면 요약에 안내가 빠지고, 후처리가 방금 저장한 추적 기록(reasoning_log)이 옛 값으로 덮일 수 있다.
    (이 짧은 구간을 테스트에서 늘리려고, 이유 UPDATE 뒤 교체 확인 단계에서 멈춘다.)"""
    revision_id, run_id = _accepted_run(conn)
    in_save, release = threading.Event(), threading.Event()
    real_replaced = rs._replaced_since_build

    def paused_replaced(*args, **kwargs):
        in_save.set()                         # 이유 UPDATE 로 후보 행을 이미 잠갔고, 아직 커밋 전이다
        release.wait(STEP_TIMEOUT_S)
        return real_replaced(*args, **kwargs)

    monkeypatch.setattr(rs, "_replaced_since_build", paused_replaced)
    post, post_box = _in_thread(lambda: rs.execute_recommendation(revision_id, run_id))
    swapper = None
    try:
        assert in_save.wait(STEP_TIMEOUT_S), "후처리가 이유 저장까지 가지 못했다"
        with get_conn() as other:
            row, target = _first_swappable(other, revision_id, run_id)

        def swap():
            with get_conn() as other:
                return rs.swap_item(other, revision_id, row["id"], uuid.UUID(target["candidate_id"]))

        swapper, swap_box = _in_thread(swap)
        _wait_until_blocked(conn, "UPDATE engine.recommendation_candidate SET variant_id=")    # 교체가 후처리의 행 잠금에 막혀 있다
    finally:
        release.set()
        post.join(STEP_TIMEOUT_S)
        if swapper is not None:
            swapper.join(STEP_TIMEOUT_S)
    assert not post.is_alive() and not swapper.is_alive(), "스레드가 끝나지 않았다"
    assert "error" not in post_box and "error" not in swap_box, (post_box, swap_box)

    rows = _rows(conn, run_id)
    swapped = rows[row["slot"]]
    assert swapped["variant_id"] == uuid.UUID(target["candidate_id"])
    assert swapped["reason_status"] == "ready" and swapped["reason"].startswith(rs._SWAP_REASON_PREFIX)
    assert swapped["checks"] is None
    assert all(r["reason_status"] == "ready" and r["checks_status"] == "ready" for slot, r in rows.items() if slot != row["slot"])
    run = EngineRepo(conn).get_run(run_id)
    assert run["explanation_status"] == "ready"
    assert run["explanation_text"].count(SWAP_NOTE) == 1 and target["product"]["name"] in run["explanation_text"]
    # 안내를 붙이며 요약 본문·추적 기록을 다시 쓰는데, 후처리가 방금 저장한 것이 그대로 남아야 한다
    assert run["explanation_headline"]
    steps = [entry.get("step") for entry in run["reasoning_log"]]
    assert "설명 생성" in steps and SNAPSHOT_STEP in steps


def test_postprocess_waiting_for_an_uncommitted_swap_adds_the_summary_note_once(conn, monkeypatch):
    """반대 순서 — 교체가 먼저 후보 행을 잠갔고(커밋 전) 후처리가 그 행의 이유 UPDATE 에서 기다린다. 교체가 커밋되면 그 행은 더는
    원래 상품이 아니라서 후처리가 건너뛰고(조건부 UPDATE), 요약에는 후처리가 안내를 붙인다. 교체 쪽은 그때 요약이 아직 pending 이라
    붙이지 않으므로 안내는 한 번만 있다."""
    revision_id, run_id = _accepted_run(conn)
    explained, go_on, swap_holding, commit_swap = (threading.Event() for _ in range(4))
    real_run = stage5_explain.run
    chosen: dict = {}

    def paused_run(*args, **kwargs):
        explanation = real_run(*args, **kwargs)
        explained.set()                      # 설명은 만들었고 아직 후보 행을 쓰기 전 — 여기서 교체가 먼저 행을 잠그게 한다
        go_on.wait(STEP_TIMEOUT_S)
        return explanation

    def swap_and_hold():
        with get_conn() as other:
            row, target = _first_swappable(other, revision_id, run_id)
            chosen.update(row=row, target=target)
            rs.swap_item(other, revision_id, row["id"], uuid.UUID(target["candidate_id"]))
            swap_holding.set()
            commit_swap.wait(STEP_TIMEOUT_S)         # with 블록이 끝나야 커밋된다 — 그때까지 이 행의 잠금을 쥔다

    monkeypatch.setattr(stage5_explain, "run", paused_run)
    post, post_box = _in_thread(lambda: rs.execute_recommendation(revision_id, run_id))
    swapper = None
    try:
        assert explained.wait(STEP_TIMEOUT_S), "후처리가 설명 단계를 끝내지 못했다"
        swapper, swap_box = _in_thread(swap_and_hold)
        assert swap_holding.wait(STEP_TIMEOUT_S), "교체가 끝나지 않았다"
        go_on.set()
        _wait_until_blocked(conn, "UPDATE engine.recommendation_candidate SET reason=")        # 후처리가 교체가 쥔 행 잠금에 막혀 있다
    finally:
        go_on.set()
        commit_swap.set()
        post.join(STEP_TIMEOUT_S)
        if swapper is not None:
            swapper.join(STEP_TIMEOUT_S)
    assert not post.is_alive() and not swapper.is_alive(), "스레드가 끝나지 않았다"
    assert "error" not in post_box and "error" not in swap_box, (post_box, swap_box)

    row, target = chosen["row"], chosen["target"]
    rows = _rows(conn, run_id)
    swapped = rows[row["slot"]]
    assert swapped["variant_id"] == uuid.UUID(target["candidate_id"])
    assert swapped["reason_status"] == "ready" and swapped["reason"].startswith(rs._SWAP_REASON_PREFIX)
    assert swapped["checks"] is None and swapped["checks_status"] == "pending"
    assert all(r["reason_status"] == "ready" and r["checks_status"] == "ready" for slot, r in rows.items() if slot != row["slot"])
    run = EngineRepo(conn).get_run(run_id)
    assert run["explanation_status"] == "ready"
    assert run["explanation_text"].count(SWAP_NOTE) == 1 and target["product"]["name"] in run["explanation_text"]


def test_postprocess_failure_after_a_swap_fails_only_the_pending_rows(conn, monkeypatch, caplog):
    revision_id, run_id = _accepted_run(conn)
    info = _swap_when_explained(monkeypatch, revision_id, run_id, then_raise=True)
    caplog.set_level(logging.INFO, logger=SERVICE_LOGGER)

    # 교체가 이유를 ready 로 채운 행을 failed 로 바꾸려 하면 reason_content_check 제약 위반이라 실패 처리 자체가 예외를 냈다.
    rs.execute_recommendation(revision_id, run_id)

    rows = _rows(conn, run_id)
    swapped = rows[info["slot"]]
    assert swapped["variant_id"] == info["new_variant"]
    assert swapped["reason_status"] == "ready" and swapped["reason"].startswith(rs._SWAP_REASON_PREFIX)
    assert swapped["checks"] is None and swapped["checks_status"] == "pending"      # 그대로 — 교체 때 비워진 채
    for slot, row in rows.items():
        if slot != info["slot"]:
            assert row["reason_status"] == "failed" and row["reason"] is None
            # 사용 가이드는 설명과 따로 찾아 저장한다 — 설명이 실패해도 가이드는 채워진다
            assert row["checks_status"] == "ready" and row["checks"]
    run = EngineRepo(conn).get_run(run_id)
    assert run["status"] == "completed" and run["explanation_status"] == "failed"      # 부품표는 done 인 채
    assert run["explanation_text"] is None
    failures = [r for r in caplog.records
                if r.name == SERVICE_LOGGER and r.levelno == logging.WARNING and r.getMessage().startswith("recommendation post_failed")]
    assert len(failures) == 1 and f"run_id={run_id}" in failures[0].getMessage() and "error=RuntimeError" in failures[0].getMessage()


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
    done = [m for m in messages if m.startswith("recommendation post_done")]
    assert len(core) == 1 and len(done) == 1
    assert re.fullmatch(rf"recommendation core_ready run_id={run_id} core_ms=\d+", core[0])
    assert re.fullmatch(
        rf"recommendation post_done run_id={run_id} explain_source=(llm|rule) explain_ms=\d+ guide_ms=\d+ post_ms=\d+ total_ms=\d+",
        done[0])
    assert not [m for m in messages if m.startswith("recommendation ") and "failed" in m]


def _explained(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == SERVICE_LOGGER and r.getMessage().startswith("recommendation explained")]


def test_a_rule_fallback_with_a_real_llm_is_logged_as_a_warning_with_its_reason(conn, monkeypatch, caplog):
    """[5] 의 진행 로그는 버려지므로(noop) 설명이 규칙 문장으로 내려간 까닭(시간 초과·요청 오류 등)이 운영 로그에 남아야 한다."""
    revision_id, run_id = _accepted_run(conn)
    caplog.set_level(logging.INFO, logger=SERVICE_LOGGER)
    monkeypatch.setattr("src.config.MOCK_MODE", False)

    def timed_out(*_args, **_kwargs):
        raise TimeoutError("call_llm: 시간 예산을 다 썼습니다")

    monkeypatch.setattr(stage5_explain, "call_llm", timed_out)
    rs.execute_recommendation(revision_id, run_id)

    [record] = _explained(caplog)
    n = len(_rows(conn, run_id))
    assert record.levelno == logging.WARNING
    assert re.fullmatch(rf"recommendation explained run_id={run_id} source=rule fallback=TimeoutError "
                        rf"rule_slots={n}/{n} explain_ms=\d+", record.getMessage())
    assert EngineRepo(conn).get_run(run_id)["explanation_status"] == "ready"      # 규칙 문장으로 공개는 된다


def test_an_llm_explanation_is_logged_as_info_with_the_rule_slots(conn, monkeypatch, caplog):
    revision_id, run_id = _accepted_run(conn)
    caplog.set_level(logging.INFO, logger=SERVICE_LOGGER)
    monkeypatch.setattr("src.config.MOCK_MODE", False)

    def drafted(prompt, **_kwargs):
        # 입력의 "- 슬롯 | 상품명 | ..." 줄로 슬롯마다 다른 이유를 만든다. 첫 슬롯 이유에는 금지어를 넣어 그 슬롯만 규칙 문장이 되게 한다.
        slots = [line[2:].split(" | ")[0] for line in prompt.splitlines() if line.startswith("- ") and " | " in line]
        items = [{"slot": slot, "reason": f"{i}번째 부품 설명" + (" 최고" if i == 0 else "")} for i, slot in enumerate(slots)]
        return {"headline": "요약 제목", "summary": "요약 본문", "items": items}

    monkeypatch.setattr(stage5_explain, "call_llm", drafted)
    rs.execute_recommendation(revision_id, run_id)

    [record] = _explained(caplog)
    n = len(_rows(conn, run_id))
    assert record.levelno == logging.INFO
    assert re.fullmatch(rf"recommendation explained run_id={run_id} source=llm fallback=- rule_slots=1/{n} explain_ms=\d+",
                        record.getMessage())


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


def test_guide_failure_does_not_fail_the_reasons_or_the_summary(conn, monkeypatch, caplog):
    """가이드와 설명은 따로 끝난다 — 가이드 검색이 실패해도 이유·요약은 ready 로 공개되고, 가이드만 failed 로 끝난다."""
    revision_id, run_id = _accepted_run(conn)
    caplog.set_level(logging.INFO, logger=SERVICE_LOGGER)

    def broken_search(*_args, **_kwargs):
        raise RuntimeError("임베딩 실패 주입")

    monkeypatch.setattr(care_guides, "search_care_guides", broken_search)
    rs.execute_recommendation(revision_id, run_id)

    rows = _rows(conn, run_id)
    assert all(r["reason_status"] == "ready" and r["checks_status"] == "failed" and r["checks"] is None for r in rows.values())
    result = rs.get_stored_result(conn, revision_id)
    assert result["explanation"]["status"] == "ready"
    assert all(item["guide_status"] == "failed" and item["reason"]["status"] == "ready" for item in result["items"])
    messages = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert any(m.startswith("recommendation post_failed") and "stage=guide" in m and "error=RuntimeError" in m for m in messages)
    assert not any(m.startswith("recommendation post_done") for m in messages)


def test_guides_are_published_even_when_the_explanation_is_slow(conn, monkeypatch):
    """가이드는 설명을 기다리지 않는다 — 설명 LLM 이 아직 도는 동안 가이드가 먼저 저장돼 보인다."""
    revision_id, run_id = _accepted_run(conn)
    seen: dict = {}
    real_run = stage5_explain.run

    def slow_run(*args, **kwargs):
        deadline = time.monotonic() + STEP_TIMEOUT_S
        while time.monotonic() < deadline:     # 가이드 스레드가 저장할 때까지(설명은 아직 안 끝났다)
            rows = _rows(conn, run_id)
            if all(r["checks_status"] == "ready" for r in rows.values()):
                break
            time.sleep(0.05)
        seen["rows"] = rows
        seen["explanation"] = EngineRepo(conn).get_run(run_id)["explanation_status"]
        return real_run(*args, **kwargs)

    monkeypatch.setattr(stage5_explain, "run", slow_run)
    rs.execute_recommendation(revision_id, run_id)

    assert seen["explanation"] == "pending"
    assert all(r["checks_status"] == "ready" and r["reason_status"] == "pending" for r in seen["rows"].values())
    assert all(r["reason_status"] == "ready" for r in _rows(conn, run_id).values())

