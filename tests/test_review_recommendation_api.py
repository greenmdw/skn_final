"""Recommendation execute contract: a stored request profile or an explicitly failed run."""
import os
from uuid import UUID, uuid4
from unittest.mock import patch
from src.services.review_aspect_score import load_review_profile_config

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
            run = conn.execute(
                "SELECT status,engine_versions,reasoning_log FROM engine.recommendation_run WHERE id=%s",
                (run_id,),
            ).fetchone()
            profile = conn.execute(
                "SELECT profile_version,analysis_version,parts FROM engine.review_requirement_profile WHERE run_id=%s",
                (run_id,),
            ).fetchone()
        assert run[0] == "completed"
        assert run[1]["review_profile"] == profile[0]
        assert run[1]["review_analysis"] == profile[1]
        assert profile[2]
        review_steps = [step for step in run[2] if step.get("step") == "리뷰 관측"]
        assert review_steps
        assert any("R=0.500" in step["detail"] and any(
            state in step["detail"] for state in (
                "혼합 방향 관측만 있음", "선택 조건에 관측 없음"))
                   for step in review_steps)
        assert not any("순위만 내렸습니다" in step["detail"] or "7일 몰림" in step["detail"]
                       for step in review_steps)


def test_execute_marks_review_readiness_failure_as_failed_run():
    config = load_review_profile_config()
    config["analysis_version"] = "test-missing-" + uuid4().hex
    with patch("src.services.review_ranking.load_review_profile_config", return_value=config):
        with TestClient(app, raise_server_exceptions=False) as client:
            _list_id, run_id = _start_recommendation(client)
    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT status FROM engine.recommendation_run WHERE id=%s", (run_id,),
        ).fetchone()
    assert row[0] == "failed"
