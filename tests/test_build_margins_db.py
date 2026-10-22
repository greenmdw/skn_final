"""조합 여유 기록(4b단계)의 저장·재계산 — 추천 실행 뒤 reasoning_log 의 "조합 여유" 단계, 교체 뒤 재계산, 설명 단계가 지우지 않음."""
from __future__ import annotations

import json
import uuid

import pytest

from src.auth.deps import Principal
from src.engine.build_margins import MARGINS_STEP
from src.repo.engine_repo import EngineRepo
from src.services import recommendation_service as rs

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    import psycopg

    from src.config import DATABASE_URL

    connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    try:
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
    run_id = uuid.UUID(accepted["run_id"])
    rs.execute_recommendation(revision_id, run_id)
    return revision_id, run_id


def _steps(conn, run_id):
    return [s for s in EngineRepo(conn).get_run_trace(run_id) if s.get("step") == MARGINS_STEP]


def test_recommendation_stores_exactly_one_margins_step_and_the_explanation_keeps_it(conn):
    revision_id, run_id = _recommend(conn)
    run = EngineRepo(conn).get_run(run_id)
    assert run["explanation_status"] == "ready"                               # set_explanation 이 끝난 뒤에도
    steps = _steps(conn, run_id)
    assert len(steps) == 1
    step = steps[0]
    assert step["title"] == "조합 여유" and "참고용" in step["detail"]
    margins = step["margins"]
    assert margins["version"] == 1 and set(margins) == {"version", "power", "size", "cooling"}
    assert margins["cooling"]["status"] == "unavailable" and margins["power"]["total"]["reason"] == "other_load_basis_missing"
    assert margins["power"]["compat_check"]["status"] == "available"
    assert json.loads(json.dumps(margins)) == margins
    # 적격성 단계는 그대로 옆에 하나
    assert [s["step"] for s in EngineRepo(conn).get_run_trace(run_id)].count("추천 적격성") == 1


def test_swap_item_reverify_replaces_the_step_with_the_new_parts_values(conn):
    from src.engine.stage2_requirement import load_computer_rules
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    revision_id, run_id = _recommend(conn)
    before = _steps(conn, run_id)[0]["margins"]
    result = rs.get_stored_result(conn, revision_id)
    gpu_item = next(i for i in result["items"] if i["slot"] == "GPU")
    key = load_computer_rules()["verification"]["gpu_length"]["gpu_spec"]
    pool = load_candidates_by_slot_from_db(conn)["GPU"]
    current = next(c for c in pool if c.variant_id == gpu_item["product"]["variant_id"])
    other = next(c for c in pool if c.variant_id != current.variant_id and c.specs.get(key) is not None
                 and c.specs.get(key) != current.specs.get(key))
    rs.swap_item(conn, revision_id, uuid.UUID(gpu_item["item_id"]), uuid.UUID(other.variant_id))

    steps = _steps(conn, run_id)
    assert len(steps) == 1                                                    # 쌓이지 않고 교체된다
    after = steps[0]["margins"]
    gpu_len = after["size"]["gpu_length"]
    if gpu_len["status"] == "available":
        used = next(i for i in gpu_len["inputs"] if i["slot"] == "GPU")
        assert used["value"] == other.specs[key] and used["name"] == other.name
    power = after["power"]["compat_check"]
    if power["status"] == "available":
        assert next(i for i in power["inputs"] if i["slot"] == "GPU")["name"] == other.name
    # 처음 추천이 남긴 요구 산정 기록은 재계산이 이어 둔다
    assert after["power"]["requirement_sizing"] == before["power"]["requirement_sizing"]
    assert [s["step"] for s in EngineRepo(conn).get_run_trace(run_id)].count("추천 적격성") == 1
