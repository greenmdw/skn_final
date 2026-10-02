"""Recommendation execute contract: a stored request profile or an explicitly failed run."""
import os
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api import app
from review_ranking_seed import neutral_review_prerequisite


pytestmark = pytest.mark.db
DSN = os.environ["DATABASE_URL"]


def _start_recommendation(client):
    list_id = client.post("/session").json()["list_id"]
    response = client.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "build"})
    assert response.status_code == 200, response.text
    response = client.post(f"/session/{list_id}/message", json={"text": "게임용 PC 맞추고 싶어요"})
    assert response.status_code == 200, response.text
    for question, answer in (("q_purpose", "게임"), ("q_budget_max", 5_000_000), ("q_priority", "성능 우선")):
        response = client.post(f"/session/{list_id}/answer", json={"question_id": question, "selected": [answer]})
        assert response.status_code == 200, response.text
    accepted = client.post(f"/session/{list_id}/recommend")
    assert accepted.status_code == 202, accepted.text
    return list_id, UUID(accepted.json()["run_id"])


def test_execute_stores_profile_versions_and_completes_review_rank():
    with neutral_review_prerequisite(DSN):
        with TestClient(app) as client:
            _list_id, run_id = _start_recommendation(client)
        with psycopg.connect(DSN) as conn:
            run = conn.execute("SELECT status,engine_versions FROM engine.recommendation_run WHERE id=%s", (run_id,)).fetchone()
            profile = conn.execute(
                "SELECT profile_version,analysis_version,parts FROM engine.review_requirement_profile WHERE run_id=%s",
                (run_id,),
            ).fetchone()
        assert run[0] == "completed"
        assert run[1]["review_profile"] == profile[0]
        assert run[1]["review_analysis"] == profile[1]
        assert profile[2]


def test_execute_marks_review_readiness_failure_as_failed_run():
    with TestClient(app, raise_server_exceptions=False) as client:
        _list_id, run_id = _start_recommendation(client)
    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT status FROM engine.recommendation_run WHERE id=%s", (run_id,),
        ).fetchone()
    assert row[0] == "failed"
