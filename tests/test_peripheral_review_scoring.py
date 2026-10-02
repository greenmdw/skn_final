"""Shared peripheral scorer keeps explicit mock neutral and propagates DB failures."""
import pytest

from src.dto import Candidate
from src.services import review_ranking


def test_explicit_mock_scoring_requires_missing_product_id_and_attaches_detail():
    candidate = Candidate(product_key="demo-mouse", slot="mouse", name="Demo mouse", price=10)
    profiles = review_ranking.score_peripheral_candidates(
        None, {"mouse": [candidate]}, {"peripherals": "mouse", "purpose": "game"},
        catalog_source="mock",
    )
    assert list(profiles) == ["mouse"]
    assert candidate.review_detail is not None
    assert candidate.review_detail.value == 0.5
    assert all(c.evidence_state == "product_id_missing" for c in candidate.review_detail.contributions)


def test_db_peripheral_scoring_rejects_missing_product_id():
    candidate = Candidate(product_key="x", slot="mouse", name="Mouse")
    with pytest.raises(review_ranking.ReviewProductIdentifierError):
        review_ranking.score_peripheral_candidates(
            object(), {"mouse": [candidate]}, {"peripherals": ["mouse"]}, catalog_source="db",
        )


def test_db_peripheral_snapshot_errors_are_not_converted_to_neutral(monkeypatch):
    candidate = Candidate(product_key="x", slot="mouse", name="Mouse", product_id="product-id")

    def fail_snapshot(*_args, **_kwargs):
        raise RuntimeError("review snapshot unavailable")

    monkeypatch.setattr(review_ranking, "load_review_aspect_snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="review snapshot unavailable"):
        review_ranking.score_peripheral_candidates(
            object(), {"mouse": [candidate]}, {"peripherals": ["mouse"]}, catalog_source="db",
        )
