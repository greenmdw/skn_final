"""Shared review orchestration: explicit mock, strict DB failures, and profile retention."""
import pytest

from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.services import review_ranking


def _inputs(candidate):
    spec = RequirementSpec(
        list_id="demo", category="computer", mode="build", targets={candidate.slot: {}},
        budget={"total": 100_000, "alloc": {candidate.slot: 1.0}},
    )
    slots = Slots(category="computer", mode="build", objective_text="", values={})
    return HardFilterResult(slots={candidate.slot: [candidate]}), spec, slots


def test_explicit_mock_returns_neutral_detail_and_same_profile_without_run():
    candidate = Candidate(product_key="mock-cpu", slot="CPU", name="demo CPU")
    hf, spec, slots = _inputs(candidate)
    rank, profiles = review_ranking.rank_with_review_aspects(
        hf, spec, slots, lambda _message: None, catalog_source="mock",
    )
    ranked = rank.slots["CPU"]["pool"][0]
    assert ranked["breakdown"]["리뷰"] == 0.5
    assert ranked["review_detail"]["contributions"][0]["evidence_state"] == "product_id_missing"
    assert set(profiles) == {"cpu"}


def test_mock_mode_rejects_database_identity_and_persisted_run():
    candidate = Candidate(product_key="db-cpu", slot="CPU", name="CPU", product_id="00000000-0000-0000-0000-000000000001")
    hf, spec, slots = _inputs(candidate)
    with pytest.raises(review_ranking.ReviewRankingError, match="DB product_id"):
        review_ranking.rank_with_review_aspects(hf, spec, slots, lambda _: None, catalog_source="mock")
    candidate.product_id = None
    with pytest.raises(review_ranking.ReviewRankingError, match="persisted recommendation"):
        review_ranking.rank_with_review_aspects(
            hf, spec, slots, lambda _: None, catalog_source="mock", run_id="test-run",
        )


def test_database_readiness_error_propagates_without_neutral_fallback(monkeypatch):
    candidate = Candidate(product_key="db-cpu", slot="CPU", name="CPU", product_id="00000000-0000-0000-0000-000000000001")
    hf, spec, slots = _inputs(candidate)

    def fail(*_args):
        raise RuntimeError("aggregate readiness unavailable")

    monkeypatch.setattr(review_ranking, "load_review_aspect_snapshot", fail)
    with pytest.raises(RuntimeError, match="aggregate readiness unavailable"):
        review_ranking.rank_with_review_aspects(
            hf, spec, slots, lambda _: None, conn=object(), catalog_source="db",
        )
    assert candidate.review_detail is None


def test_db_catalog_connection_error_does_not_fall_back_to_mock(monkeypatch):
    from src import db
    from src.engine import stage3_0_candidates

    monkeypatch.setenv("CATALOG_SOURCE", "db")

    def fail_connection():
        raise RuntimeError("catalog database unavailable")

    monkeypatch.setattr(db, "get_conn", fail_connection)
    monkeypatch.setattr(
        stage3_0_candidates, "load_candidates_by_slot",
        lambda: (_ for _ in ()).throw(AssertionError("mock fallback was called")),
    )
    with pytest.raises(RuntimeError, match="catalog database unavailable"):
        stage3_0_candidates.load_pc_catalog(lambda _message: None)
