"""Review API contract, immutable provenance, and frozen report regressions."""
import copy
import os
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.services.recommendation_review_snapshot import (
    original_review, review_for_candidate, snapshot_from_run, snapshot_step,
)
from tests.test_list_history_http import _recommended_list, _signed_up


def _snapshot(state="observed", p=1, n=0, mixed=0):
    product, variant, run = (str(uuid4()) for _ in range(3))
    q = (p + 2) / (p + n + 4)
    detail = {
        "profile": {"profile_version": "profile-test", "analysis_version": "analysis-test",
                    "part_type": "gpu", "attributes": []},
        "value": q, "readiness": {"global_completeness_verified": False},
        "contributions": [{
            "aspect_code": "fan_quietness", "context_code": "gaming_load", "alpha": 1,
            "p": p, "n": n, "mixed": mixed, "k": 4, "q": q, "alpha_q": q,
            "evidence_state": state,
            "members": [{"observation_id": str(uuid4()), "document_id": str(uuid4()),
                         "source_code": "real-source", "direction": "positive",
                         "observation_text": "Quiet during gaming", "evidence_sentences": ["팬이 조용해요."]}]
                       if p else [],
        }],
    }
    candidate = {"variant_id": variant, "product_id": product, "score": .7,
                 "breakdown": {"리뷰": q}, "review_detail": detail}
    rank = SimpleNamespace(weights_used={"리뷰": .2}, slots={"GPU": {"pool": [candidate]}})
    build = SimpleNamespace(items=[SimpleNamespace(slot="GPU", variant_id=variant)])
    step = snapshot_step(rank, build, run, {"purpose": "game", "noise_sensitive": True})
    return snapshot_from_run({"reasoning_log": [step]}), product, variant, run


@pytest.mark.parametrize("state,p,n,mixed", [
    ("observed", 1, 0, 0), ("balanced", 1, 1, 0),
    ("mixed_only", 0, 0, 1), ("no_observations", 0, 0, 0),
    ("selected_rule_missing", 0, 0, 0),
])
def test_states_and_exact_evidence_survive_snapshot(state, p, n, mixed):
    snapshot, product, variant, run = _snapshot(state, p, n, mixed)
    result = review_for_candidate(snapshot, product_id=product, variant_id=variant, slot="GPU")
    assert result["status"] == "ready"
    assert result["source_run_id"] == run
    assert result["detail"]["contributions"][0]["evidence_state"] == state
    assert result["detail"]["readiness"]["global_completeness_verified"] is False
    assert result["rank_contribution"] == pytest.approx(.2 * result["detail"]["value"])
    assert result["detail"] == snapshot["candidates"][variant]["detail"]


def test_unknown_or_wrong_product_never_receives_old_review():
    snapshot, product, variant, _run = _snapshot()
    assert review_for_candidate(None, product_id=product, variant_id=variant, slot="GPU")["reason"] == "snapshot_missing"
    unknown = str(uuid4())
    assert review_for_candidate(snapshot, product_id=product, variant_id=unknown, slot="GPU")["reason"] == "candidate_not_in_snapshot"
    assert original_review(snapshot, slot="GPU", current_variant_id=unknown)["variant_id"] == variant
    wrong = review_for_candidate(snapshot, product_id=str(uuid4()), variant_id=variant, slot="GPU")
    assert wrong["status"] == "failed" and wrong["detail"] is None


@pytest.mark.db
def test_result_alternative_swap_and_report_keep_same_run_snapshot():
    with TestClient(app) as client:
        # Sign in before creating the list, so confirmation uses the same owner.
        signed = _signed_up()
        client.cookies.update(signed.cookies)
        list_id, revision_id, result = _recommended_list(client)
        assert "리뷰 요약은 합성 데이터입니다" not in result["data_notice"]
        assert all(item["review_detail"]["status"] == "ready" for item in result["items"])
        assert all(item["review"]["rating_refined"] is None for item in result["items"])
        item = next(item for item in result["items"] if item["alternatives_count"])
        initial = copy.deepcopy(item["review_detail"])
        assert initial["detail"]["profile"]["analysis_version"]

        # A current aggregate read would now fail. Saved result/alternatives/report
        # must continue to use the original scoring snapshot instead.
        from unittest.mock import patch
        with patch("src.services.review_ranking.load_review_aspect_snapshot", side_effect=AssertionError("no live review reload")):
            again = client.get(f"/session/{list_id}/result").json()
            assert next(i for i in again["items"] if i["item_id"] == item["item_id"])["review_detail"] == initial
            response = client.get(f"/session/{list_id}/items/{item['item_id']}/alternatives")
            assert response.status_code == 200, response.text
            choices = response.json()["items"]
            alternative = next(a for a in choices if not a["current"])
            response = client.post(f"/session/{list_id}/items/{item['item_id']}/swap",
                                   json={"candidate_id": alternative["candidate_id"]})
            assert response.status_code == 200, response.text
            swapped = next(i for i in response.json()["items"] if i["item_id"] == item["item_id"])
            assert swapped["original_review_detail"] == initial
            assert swapped["review_detail"]["variant_id"] == alternative["candidate_id"]
            assert swapped["review_detail"]["selection_source"] == "user_swap"
            assert swapped["review_detail"]["detail"] == alternative["review_detail"]["detail"]
            confirmed = client.post(f"/lists/{list_id}/confirm", json={"name": "리뷰 근거 저장"})
            assert confirmed.status_code == 200, confirmed.text
            report = next(i for i in confirmed.json()["items"] if i["slot"] == item["slot"])
            assert report["review_detail"] == swapped["review_detail"]
            assert report["original_review_detail"] == initial
            reread = client.get(f"/lists/{list_id}/report").json()
            assert next(i for i in reread["items"] if i["slot"] == item["slot"])["review_detail"] == report["review_detail"]
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            stored = conn.execute("SELECT reasoning_log FROM engine.recommendation_run WHERE revision_id=%s", (revision_id,)).fetchone()[0]
            snapshot = snapshot_from_run({"reasoning_log": stored})
            assert snapshot["source_run_id"] == result["run_id"]
            observed = 0
            for candidate in snapshot["candidates"].values():
                detail = candidate["detail"]
                for contribution in detail["contributions"]:
                    if not contribution["aggregate_id"]:
                        continue
                    aggregate = conn.execute(
                        "SELECT a.product_id,a.rule_id,a.p,a.n,a.mixed,a.q,r.analysis_version "
                        "FROM evidence.review_aspect_aggregate a JOIN evidence.review_aspect_rule r ON r.id=a.rule_id "
                        "WHERE a.id=%s", (contribution["aggregate_id"],),
                    ).fetchone()
                    assert str(aggregate[0]) == candidate["product_id"]
                    assert str(aggregate[1]) == contribution["rule_id"]
                    assert aggregate[2:5] == (contribution["p"], contribution["n"], contribution["mixed"])
                    assert float(aggregate[5]) == pytest.approx(contribution["q"])
                    assert aggregate[6] == detail["profile"]["analysis_version"]
                    for member in contribution["members"]:
                        observation = conn.execute(
                            "SELECT o.document_id,o.direction,o.observation_text,o.evidence_sentences,"
                            "d.product_id,d.source_code,d.is_synthetic FROM evidence.review_aspect_observation o "
                            "JOIN evidence.review_document d ON d.id=o.document_id "
                            "JOIN evidence.review_aspect_aggregate_member m ON m.observation_id=o.id "
                            "WHERE o.id=%s AND m.aggregate_id=%s",
                            (member["observation_id"], contribution["aggregate_id"]),
                        ).fetchone()
                        assert str(observation[0]) == member["document_id"]
                        assert observation[1:4] == (member["direction"], member["observation_text"], member["evidence_sentences"])
                        assert str(observation[4]) == candidate["product_id"]
                        assert observation[5] == member["source_code"] and observation[6] is False
                        observed += 1
            assert observed > 0


@pytest.mark.db
@pytest.mark.parametrize("explanation_status", ["failed", "pending"])
def test_explanation_status_does_not_lose_calculated_review(monkeypatch, explanation_status):
    from src.engine import stage5_explain
    from tests.test_review_recommendation_api import _start_recommendation

    def fail(*args, **kwargs):
        raise RuntimeError("test explanation failure")

    if explanation_status == "failed":
        monkeypatch.setattr(stage5_explain, "run", fail)
    else:
        from src.repo.engine_repo import EngineRepo
        monkeypatch.setattr(EngineRepo, "set_explanation", lambda *args, **kwargs: None)
    with TestClient(app) as client:
        list_id, _run = _start_recommendation(client)
        response = client.get(f"/session/{list_id}/result")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "done" and result["explanation"]["status"] == explanation_status
    assert all(item["review_detail"]["status"] == "ready" for item in result["items"])


@pytest.mark.db
def test_cloned_revision_keeps_source_run_and_legacy_detail_is_unavailable():
    from uuid import UUID
    from psycopg.rows import dict_row
    from src.repo.plan_repo import PlanRepo
    from src.services.recommendation_service import get_stored_result

    with TestClient(app) as client:
        list_id, revision_id, result = _recommended_list(client)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        cloned_id = PlanRepo(conn).clone_revision(UUID(list_id), UUID(revision_id))
        cloned = get_stored_result(conn, cloned_id)
        assert cloned["run_id"] != result["run_id"]
        assert [i["review_detail"] for i in cloned["items"]] == [i["review_detail"] for i in result["items"]]
        assert all(i["review_detail"]["source_run_id"] == result["run_id"] for i in cloned["items"])
        # An older run lacking the snapshot must not be backfilled from live data.
        conn.execute("UPDATE engine.recommendation_run SET reasoning_log='[]'::jsonb WHERE id=%s", (cloned["run_id"],))
        legacy = get_stored_result(conn, cloned_id)
        assert all(i["review_detail"]["status"] == "unavailable" and
                   i["review_detail"]["reason"] == "snapshot_missing" for i in legacy["items"])
        conn.rollback()
