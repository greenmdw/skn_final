"""개발요청 8번 — "견적 수정하기": 확정본의 부품 구성을 새 견적서(draft revision)로 복사한다.

POST /lists/{id}/revisions 가 조건뿐 아니라 추천 결과(부품 구성)까지 복사해서, 새 초안이
재추천 없이 바로 그 구성을 갖고 시작하는지 확인한다(PlanRepo.clone_revision).
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set DATABASE_URL to a disposable migrated database",
)

if DSN:
    os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local-test")
    from fastapi.testclient import TestClient

    from src.api import app

    @pytest.fixture()
    def client():
        with TestClient(app) as c:
            yield c

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()

    @pytest.fixture()
    def signed_up_client():
        c = TestClient(app)
        r = c.post("/auth/signup", json={
            "email": f"revise-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
            "display_name": "ReviseTester",
            "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
        })
        assert r.status_code == 201, r.text
        return c


def _create(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _choose_computer(c, list_id: str) -> None:
    r = c.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "build"})
    assert r.status_code == 200, r.text


def _fill_computer_conditions(c, list_id: str, *, budget: int = 2_000_000) -> dict:
    for qid, selected in (("q_purpose", ["게임"]), ("q_budget_max", [budget]), ("q_priority", ["성능 우선"])):
        r = c.post(f"/session/{list_id}/answer", json={"question_id": qid, "selected": selected})
        assert r.status_code == 200, r.text
    return r.json()


def _recommend_and_wait(c, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/recommend")
    assert r.status_code == 202, r.text
    r = c.get(f"/session/{list_id}/result")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done", data
    return data


def test_new_revision_copies_confirmed_build_instead_of_starting_empty(signed_up_client, raw_conn):
    c = signed_up_client
    list_id = _create(c)
    _choose_computer(c, list_id)
    state = _fill_computer_conditions(c, list_id)
    original_revision_id = state["revision_id"]
    original = _recommend_and_wait(c, list_id)

    # 부품 하나를 직접 바꿔서, 복사본이 "재추천 결과"가 아니라 "이 사용자가 손댄 구성 그대로"인지도 같이 검증한다.
    item = next(it for it in original["items"] if it["alternatives_count"] > 0)
    alt = c.get(f"/session/{list_id}/items/{item['item_id']}/alternatives").json()["items"][0]
    swapped = c.post(f"/session/{list_id}/items/{item['item_id']}/swap",
                     json={"candidate_id": alt["candidate_id"]}).json()

    r = c.post(f"/lists/{list_id}/confirm", json={"name": "수정 전 견적"})
    assert r.status_code == 200, r.text

    r = c.post(f"/lists/{list_id}/revisions")
    assert r.status_code == 200, r.text
    new_state = r.json()
    new_revision_id = new_state["revision_id"]
    assert new_revision_id != original_revision_id

    result = c.get(f"/session/{list_id}/result")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "done", "재추천 없이 바로 결과가 있어야 한다(복사됐으므로)"
    assert data["revision_id"] == new_revision_id

    swapped_item = next(it for it in data["items"] if it["slot"] == item["slot"])
    assert swapped_item["product"]["name"] == alt["product"]["name"], \
        "확정 전에 사용자가 직접 바꾼 부품이 새 초안에도 그대로 있어야 한다"

    # 새 초안에서 실제로 추가 조작(교체)이 가능한지 — 단순 조회 전용 스냅샷이 아니라 진짜 draft여야 한다.
    other_item = next(it for it in data["items"] if it["item_id"] != swapped_item["item_id"]
                      and it["alternatives_count"] > 0)
    other_alt = c.get(f"/session/{list_id}/items/{other_item['item_id']}/alternatives").json()["items"][0]
    r2 = c.post(f"/session/{list_id}/items/{other_item['item_id']}/swap",
               json={"candidate_id": other_alt["candidate_id"]})
    assert r2.status_code == 200, r2.text

    row = raw_conn.execute(
        "SELECT state FROM planning.plan_revision WHERE id=%s", (new_revision_id,)
    ).fetchone()
    assert row[0] == "draft"


def test_new_revision_on_a_draft_without_prior_confirm_is_a_noop(signed_up_client):
    """이미 초안이 현재 revision이면(한 번도 확정 안 한 목록) 그대로 둔다 — clone하지 않는다."""
    c = signed_up_client
    list_id = _create(c)
    _choose_computer(c, list_id)
    state_before = c.get(f"/session/{list_id}")
    assert state_before.status_code == 200

    r = c.post(f"/lists/{list_id}/revisions")
    assert r.status_code == 200, r.text
    assert r.json()["revision_id"] == state_before.json()["revision_id"]
