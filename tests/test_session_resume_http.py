"""지난 세션 조건 이어가기(A1) — GET /session/previous · POST /session/{id}/resume HTTP 통합.

TestClient 는 쿠키(truefit_guest)를 유지하므로 같은 client 는 같은 게스트, 새 client 는 다른 게스트다.
일회용 DB 가 필요하다(tests/conftest.py 가 자동으로 만든다)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app

    @pytest.fixture()
    def client():
        with TestClient(app) as c:
            yield c

    @pytest.fixture()
    def other_client():
        with TestClient(app) as c:
            yield c


def _start(client: TestClient, mode: str = "build", **conditions) -> str:
    lid = client.post("/session").json()["list_id"]
    assert client.post(f"/session/{lid}/category", json={"category": "computer", "mode": mode}).status_code == 200
    for key, value in conditions.items():
        r = client.patch(f"/session/{lid}/slot", json={"field": key, "value": value})
        assert r.status_code == 200, r.text
    return lid


def _previous(client: TestClient, **params) -> dict | None:
    r = client.get("/session/previous", params={"category": "computer", "mode": "build", **params})
    assert r.status_code == 200, r.text
    return r.json()["previous"]


def _field(state: dict, key: str) -> dict:
    return next(f for f in state["fields"] if f["key"] == key)


def test_first_visit_has_nothing_to_resume(client):
    assert _previous(client) is None
    _start(client)                         # 카테고리만 고르고 떠난 목록은 이어갈 게 없다
    assert _previous(client) is None


def test_previous_conditions_are_summarised_but_not_applied_until_resumed(client):
    old = _start(client, purpose="game", budget_max=1_500_000, priority="value", resolution="QHD_165")
    new = _start(client)

    prev = _previous(client, exclude=new)
    assert prev is not None and prev["list_id"] == old
    for text in ("게임", "1,500,000원", "가성비", "QHD 165Hz", "이어서 할까요"):
        assert text in prev["summary"]
    assert {f["key"] for f in prev["fields"]} == {"purpose", "budget_max", "priority", "resolution"}

    # 묻기만 했을 뿐 새 목록에는 아직 아무 값도 들어가지 않았다
    state = client.get(f"/session/{new}").json()
    assert _field(state, "budget_max")["status"] == "missing"

    r = client.post(f"/session/{new}/resume", json={"from_list_id": old})
    assert r.status_code == 200, r.text
    state = r.json()
    assert _field(state, "budget_max")["value"] == 1_500_000
    assert _field(state, "purpose")["value"] == "game"
    assert _field(state, "resolution")["status"] == "confirmed"
    assert [m["role"] for m in state["messages"][-2:]] == ["user", "assistant"]
    assert "지난 조건을 가져왔어요" in state["messages"][-1]["text"]


def test_resume_keeps_values_already_chosen_in_the_new_list(client):
    old = _start(client, purpose="game", budget_max=1_500_000)
    new = _start(client, budget_max=2_000_000)
    state = client.post(f"/session/{new}/resume", json={"from_list_id": old}).json()
    assert _field(state, "budget_max")["value"] == 2_000_000
    assert _field(state, "purpose")["value"] == "game"


def test_most_recent_list_of_the_same_mode_is_offered(client):
    _start(client, purpose="office", budget_max=800_000)
    latest = _start(client, purpose="game", budget_max=1_500_000)
    _start(client, mode="upgrade", upgrade_parts=["GPU"])      # 모드가 다르면 새 PC 조립에 권하지 않는다
    prev = _previous(client)
    assert prev["list_id"] == latest


def test_other_guests_cannot_see_or_resume_my_list(client, other_client):
    mine = _start(client, purpose="game", budget_max=1_500_000)
    assert _previous(other_client) is None
    theirs = _start(other_client)
    r = other_client.post(f"/session/{theirs}/resume", json={"from_list_id": mine})
    assert r.status_code == 404
