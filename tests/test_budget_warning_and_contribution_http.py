"""추천 전 예산 사전 경고(ConditionState.budget_warning)와 결과의 기여도(explanation.contribution) — HTTP 통합.

일회용 DB(이름에 test 포함)와 PC 카탈로그 시드가 필요하다(tests/conftest.py 가 자동으로 만든다)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

if DSN:
    from src.api import app

    @pytest.fixture()
    def client():
        with TestClient(app) as c:
            yield c


def _start(client: TestClient, **conditions) -> tuple[str, dict]:
    lid = client.post("/session").json()["list_id"]
    assert client.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    state: dict = {}
    for key, value in conditions.items():
        r = client.patch(f"/session/{lid}/slot", json={"field": key, "value": value})
        assert r.status_code == 200, r.text
        state = r.json()
    return lid, state


def test_impossible_budget_is_warned_before_recommending(client):
    _lid, state = _start(client, purpose="game", budget_max=400_000, priority="value")
    warning = state["budget_warning"]
    assert warning is not None and warning["level"] == "infeasible"
    assert warning["estimated_min"] > warning["budget"] == 400_000
    assert "예산" in warning["message"]
    assert state["can_recommend"] is True      # 경고일 뿐 추천을 막지 않는다 — 결과는 예산 초과로 표시된다


def test_comfortable_budget_has_no_warning(client):
    _lid, state = _start(client, purpose="game", budget_max=5_000_000, priority="value")
    assert state["budget_warning"] is None


def test_no_budget_yet_means_no_warning(client):
    _lid, state = _start(client, purpose="game")
    assert state["budget_warning"] is None


def test_result_carries_the_real_contribution_not_the_old_mockup_numbers(client):
    lid, _ = _start(client, purpose="game", budget_max=1_800_000, priority="value")
    assert client.post(f"/session/{lid}/recommend", json={}).status_code == 202
    result = client.get(f"/session/{lid}/result").json()
    assert result["status"] == "done"
    contribution = result["explanation"]["contribution"]
    assert contribution, "기여도가 비어 있다"
    assert sum(contribution.values()) == 100
    assert {"가격", "성능", "밸런스", "리뷰", "호환여유"} <= set(contribution)
    assert contribution != {"가격": 41, "성능": 33, "호환성": 26}
    # 추적 기록에도 같은 값이 사람이 읽는 문장으로 남는다
    assert any(step.get("step") == "기여도" for step in result["reasoning_log"])


def test_value_priority_result_explains_the_unspent_budget_but_performance_does_not(client):
    lid, _ = _start(client, purpose="game", budget_max=2_000_000, priority="value")
    assert client.post(f"/session/{lid}/recommend", json={}).status_code == 202
    result = client.get(f"/session/{lid}/result").json()
    notice = result["budget_notice"]
    assert notice is not None and notice["suggest_priority"] == "performance"
    assert notice["remaining"] == 2_000_000 - result["totals"]["selected_price"] > 0
    assert "가성비 우선" in notice["message"]

    # 안내가 말한 대로 성능 우선으로 바꿔 다시 추천받으면 예산을 더 쓰고, 안내는 사라진다.
    assert client.patch(f"/session/{lid}/slot", json={"field": "priority", "value": "performance"}).status_code == 200
    assert client.post(f"/session/{lid}/recommend", json={}).status_code == 202
    again = client.get(f"/session/{lid}/result").json()
    assert again["totals"]["selected_price"] > result["totals"]["selected_price"]
    assert again["budget_notice"] is None
