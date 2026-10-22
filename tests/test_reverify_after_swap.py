"""교체·담기/빼기·수량 변경 뒤 세트 전체 재검증 — 화면의 검증 쟁점이 지금 구성을 따라간다.

회귀 배경: 검증은 [4] 가 처음 고른 세트를 한 번 점검한 결과로 저장돼서, 소켓이 안 맞는 메인보드로 교체하거나
수량을 늘려 예산을 넘겨도 결과 화면은 "쟁점 없음"인 채였다(교체 뒤 "재실행되지 않았습니다"라는 안내만 있었다).
로컬 PostgreSQL + PC 카탈로그 seed 가 필요하다."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.services import recommendation_service as rs


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


def _recommend(conn, budget=2_000_000):
    from src.repo.plan_repo import PlanRepo
    from src.services import session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = rs.start_recommendation(conn, revision_id, strategy="default")
    rs.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return revision_id, rs.get_stored_result(conn, revision_id)


def _majors(result) -> list[dict]:
    return [i for i in result["verification"]["issues"] if i["severity"] == "major"]


def _board_with_other_socket(conn, result):
    """지금 CPU 와 소켓이 다른 메인보드 변형(교체 API 는 호환 여부를 막지 않는다 — 대안 목록만 걸러 준다)."""
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    from src.engine.stage2_requirement import load_computer_rules

    key = load_computer_rules()["verification"]["socket"]
    pool = load_candidates_by_slot_from_db(conn)
    by_variant = {c.variant_id: c for cands in pool.values() for c in cands}
    cpu = by_variant[next(i["product"]["variant_id"] for i in result["items"] if i["slot"] == "CPU")]
    return next(c for c in pool["메인보드"]
                if c.specs.get(key["mainboard_spec"]) and c.specs[key["mainboard_spec"]] != cpu.specs[key["cpu_spec"]])


def test_swapping_in_an_incompatible_board_shows_a_socket_problem_and_swapping_back_clears_it(conn):
    revision_id, result = _recommend(conn)
    assert not _majors(result), "처음 추천에는 확정된 비호환이 없어야 한다"
    board = next(i for i in result["items"] if i["slot"] == "메인보드")
    bad = _board_with_other_socket(conn, result)

    swapped = rs.swap_item(conn, revision_id, uuid.UUID(board["item_id"]), uuid.UUID(bad.variant_id))
    majors = _majors(swapped)
    assert [m["axis"] for m in majors] == ["socket"]
    # 문제는 그 축에 걸린 부품(CPU·메인보드)의 "구매 전 확인"에도 나오고, 무관한 부품에는 안 나온다.
    checks = {i["slot"]: i["checks"]["text"] for i in swapped["items"]}
    assert "CPU·메인보드 소켓" in checks["메인보드"] and "CPU·메인보드 소켓" in checks["CPU"]
    assert "CPU·메인보드 소켓" not in checks["케이스"]

    back = rs.swap_item(conn, revision_id, uuid.UUID(board["item_id"]), uuid.UUID(board["product"]["variant_id"]))
    assert not _majors(back)


def test_raising_qty_over_budget_adds_a_budget_issue_and_lowering_it_removes_it(conn):
    revision_id, result = _recommend(conn, budget=1_500_000)
    gpu = next(i for i in result["items"] if i["slot"] == "GPU")
    over = rs.patch_item(conn, revision_id, uuid.UUID(gpu["item_id"]), selected=None, qty=4, timing=None)
    assert over["totals"]["over_budget"] is True
    assert any(m["axis"] == "budget" for m in _majors(over))

    ok = rs.patch_item(conn, revision_id, uuid.UUID(gpu["item_id"]), selected=None, qty=1, timing=None)
    assert ok["totals"]["over_budget"] is False
    assert not any(m["axis"] == "budget" for m in _majors(ok))


def test_timing_only_change_keeps_the_stored_validations(conn):
    revision_id, result = _recommend(conn)
    before = [(i["axis"], i["text"]) for i in result["verification"]["issues"]]
    cpu = next(i for i in result["items"] if i["slot"] == "CPU")
    after = rs.patch_item(conn, revision_id, uuid.UUID(cpu["item_id"]), selected=None, qty=None, timing="later")
    assert [(i["axis"], i["text"]) for i in after["verification"]["issues"]] == before
