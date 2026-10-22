"""원한 미보유 부품이 신규 조립 추천의 호환 조건이 되는지 — 세션 → 추천 → 결과 전체 흐름 (설계 §11). 일회용 DB가 필요하다.

wanted_parts 조건은 conditions_agent 가 쓰는 것과 같은 모양({슬롯: {name, fields, source_url}})으로 직접 넣는다."""
from __future__ import annotations

import os
import uuid

import pytest

from src.auth.deps import Principal

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg

    @pytest.fixture()
    def conn():
        connection = psycopg.connect(DSN, prepare_threshold=None, autocommit=True)
        try:
            yield connection
        finally:
            connection.close()


def _recommend(conn, wanted=None, budget=1_500_000):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service, session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    repo = PlanRepo(conn)
    revision_id = repo.get_current_revision(list_uuid)["id"]
    if wanted:
        repo.upsert_condition(revision_id, "wanted_parts", {"value": wanted}, "extracted")
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return recommendation_service.get_stored_result(conn, revision_id)


def _specs_by_name(conn):
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    return {c.name: c.specs for cands in load_candidates_by_slot_from_db(conn).values() for c in cands}


def _picked(result, specs, slot):
    item = next(i for i in result["items"] if i["slot"] == slot)
    return specs[item["product"]["name"]]


def _wanted(slot, **fields):
    return {slot: {"name": f"원하는 {slot}", "fields": fields, "source_url": "https://example.com/spec"}}


def test_wanted_cpu_socket_makes_the_board_and_cpu_follow_that_platform(conn):
    specs = _specs_by_name(conn)
    result = _recommend(conn, _wanted("CPU", socket="AM4"))

    assert result["status"] == "done"
    assert _picked(result, specs, "메인보드")["socket"] == "AM4"
    assert _picked(result, specs, "CPU")["socket"] == "AM4"        # 보드가 AM4라 CPU도 AM4 로 맞춰진다
    assert {i["slot"] for i in result["items"]} >= {"CPU", "메인보드"}   # 같은 슬롯도 카탈로그에서 추천된다


def test_wanted_ram_type_makes_the_board_and_ram_follow_that_memory(conn):
    specs = _specs_by_name(conn)
    result = _recommend(conn, _wanted("RAM", mem_type="DDR4"))

    assert result["status"] == "done"
    assert _picked(result, specs, "메인보드")["mem_type"] == "DDR4"
    assert _picked(result, specs, "RAM")["mem_type"] == "DDR4"


def test_wants_that_make_no_platform_condition_leave_the_recommendation_unchanged(conn):
    baseline = _recommend(conn)
    with_gpu = _recommend(conn, {**_wanted("GPU", interface="PCIe 5.0"), **_wanted("파워", wattage_w=1000)})

    names = lambda r: sorted(i["product"]["name"] for i in r["items"])      # noqa: E731
    assert names(with_gpu) == names(baseline)


def test_contradicting_wants_do_not_break_the_recommendation(conn):
    baseline = _recommend(conn)
    result = _recommend(conn, {**_wanted("CPU", socket="AM5"), **_wanted("메인보드", socket="LGA1700")})

    assert result["status"] == "done"
    assert sorted(i["product"]["name"] for i in result["items"]) == sorted(i["product"]["name"] for i in baseline["items"])


def test_an_unsatisfiable_want_is_skipped_instead_of_failing_the_recommendation(conn):
    baseline = _recommend(conn)
    result = _recommend(conn, _wanted("CPU", socket="LGA775"))              # 그 소켓의 메인보드는 카탈로그에 없다

    assert result["status"] == "done"
    assert sorted(i["product"]["name"] for i in result["items"]) == sorted(i["product"]["name"] for i in baseline["items"])
