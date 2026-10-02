"""결과 화면의 "묻는 말" 계산(src/services/result_advice.py)과 규칙 경로 연결 — 실제 카탈로그 DB 로.

남은 예산으로 올릴 후보, 바꾸면 어떻게 되나(저장 안 함), 줄일 수 있는 것, 게임 요구 사양 비교.
공통 확인: 어떤 함수도 구성표를 바꾸지 않는다.
"""
from __future__ import annotations

import re
import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service, result_advice, session_service

_ID = re.compile(r"candidate_id=([0-9a-f-]{36})")


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        yield connection
    finally:
        connection.close()


def _build(conn, budget: int = 1_500_000) -> uuid.UUID:
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return revision_id


def _snapshot(conn, revision_id) -> list[tuple]:
    run = recommendation_service._require_done_run(conn, revision_id)[1]
    return [(r["slot"], str(r["variant_id"]), r["qty"], r["selected"]) for r in EngineRepo(conn).get_candidates(run["id"])]


def test_upgrade_options_lists_only_better_compatible_parts_within_budget(conn):
    revision_id = _build(conn, budget=3_000_000)
    before = _snapshot(conn, revision_id)
    out = result_advice.upgrade_options(conn, revision_id)
    ctx = result_advice._context(conn, revision_id)
    budget = ctx.budget_max - ctx.total()
    ids = _ID.findall(out)
    assert ids, out
    for cid in ids:
        cand = ctx.by_variant[cid]
        row = ctx.row(cand.slot)
        current = ctx.by_variant[str(row["variant_id"])]
        assert cand.slot in ("CPU", "GPU", "RAM")
        assert result_advice._metric(cand.slot, cand.specs) > result_advice._metric(cand.slot, current.specs)
        assert 0 < (cand.price - row["price"]) * (row["qty"] or 1) <= budget
        assert not result_advice._new_failures(ctx, cand.slot, cand)
        assert result_advice._requirement_verdict(ctx, cand.slot, cand)[0] != "Fail"
    assert _snapshot(conn, revision_id) == before


def test_upgrade_options_with_tiny_amount_says_nothing_fits(conn):
    revision_id = _build(conn)
    out = result_advice.upgrade_options(conn, revision_id, 1)
    assert "추가 금액 1원" in out and "올릴 수 있는 후보가 없습니다" in out and not _ID.findall(out)


def test_preview_swap_reports_socket_mismatch_without_saving(conn):
    revision_id = _build(conn)
    before = _snapshot(conn, revision_id)
    ctx = result_advice._context(conn, revision_id)
    board_socket = ctx.chosen()["메인보드"].specs["socket"]
    other = next(c for c in ctx.pool["CPU"] if c.specs.get("socket") and c.specs["socket"] != board_socket)
    out = result_advice.preview_swap(conn, revision_id, "CPU", other.variant_id)
    assert out.startswith("(가정 계산 — 구성표는 그대로)")
    assert "⚠ 호환 점검 문제" in out and "소켓" in out
    assert _snapshot(conn, revision_id) == before


def test_preview_swap_up_picks_the_next_tier_and_reports_budget(conn):
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    out = result_advice.preview_swap(conn, revision_id, "GPU", direction="up")
    cand = ctx.by_variant[_ID.findall(out)[0]]
    now = result_advice._metric("GPU", ctx.chosen()["GPU"].specs)
    higher = [result_advice._metric("GPU", c.specs) for c in ctx.pool["GPU"]
              if (result_advice._metric("GPU", c.specs) or 0) > now and not result_advice._new_failures(ctx, "GPU", c)]
    assert result_advice._metric("GPU", cand.specs) == min(higher)
    assert "바꾼 뒤 총액" in out and ("잔여" in out or "예산 초과" in out)
    assert "전력:" in out or "⚠ 호환 점검 문제" in out


def test_savings_options_target_beyond_reach_says_so(conn):
    revision_id = _build(conn)
    out = result_advice.savings_options(conn, revision_id, 10_000_000)
    assert "못 미칩니다" in out or "더 싸게 바꿀 수 있는 부품이 없습니다" in out
    assert "아직 아무것도 바꾸지 않았습니다" in out or "없습니다" in out


def test_game_check_compares_table_tiers(conn):
    revision_id = _build(conn)
    out = result_advice.game_check(conn, revision_id, "사이버펑크")
    assert out.startswith("사이버펑크") and "GPU 성능 등급 요구" in out and "fps" in out
    assert "표에 없어" in result_advice.game_check(conn, revision_id, "없는게임123")


def test_rule_path_answers_questions_without_changing_the_build(conn):
    """에이전트가 없을 때(MOCK_MODE) — 묻는 말은 계산 결과로 답하고 구성표는 그대로다(P5)."""
    revision_id = _build(conn)
    before = _snapshot(conn, revision_id)

    up = recommendation_service.handle_result_message(conn, revision_id, "돈 남았는데 바꿀 거 추천해 줄 수 있나?")
    assert "올릴 수 있는 부품" in up["reply"] and "candidate_id" not in up["reply"]

    whatif = recommendation_service.handle_result_message(conn, revision_id, "그래픽카드 더 좋은 걸로 바꿔도 돼?")
    assert whatif["reply"].startswith("(가정 계산 — 구성표는 그대로)") and "바꿔줘" in whatif["reply"]

    power = recommendation_service.handle_result_message(conn, revision_id, "파워 용량 충분해?")
    assert "파워 용량" in power["reply"]

    game = recommendation_service.handle_result_message(conn, revision_id, "배그 돌아가?")
    assert "배틀그라운드" in game["reply"]
    assert _snapshot(conn, revision_id) == before

    # 바꾸라는 말은 예전처럼 바꾼다
    done = recommendation_service.handle_result_message(conn, revision_id, "그래픽카드를 더 저렴한 걸로 바꿔줘")
    assert "바꿨어요" in done["reply"] and _snapshot(conn, revision_id) != before
