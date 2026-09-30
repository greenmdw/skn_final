"""Unapproved Danawa observations stay separate from a real 50:50 allocation."""

import pytest

from scripts.plan_research_review_mix import build_research_scenario


def _row(key: str, target: int, observed: int, match: str = "matched") -> dict:
    return {
        "product_key": key, "sheet": "CPU", "model": key,
        "target_real_reviews": str(target), "research_metadata_count": str(observed),
        "target_total_even": str(target * 2), "model_match_status": match,
        "approved_real_available": "unknown", "review_mix_status": "not_allocated",
    }


def test_research_scenario_pairs_counts_without_creating_reviews():
    result = build_research_scenario([
        _row("a", 4, 9), _row("b", 3, 1), _row("c", 2, 0),
        _row("d", 5, 0, "unmatched"),
    ])
    assert result["summary"]["research_scenario_real_count"] == 5
    assert result["summary"]["research_scenario_synthetic_count"] == 5
    assert result["summary"]["matched_without_observed_review"] == 1
    assert result["summary"]["unmatched_products"] == 1
    assert result["summary"]["approved_real_count"] is None
    assert result["summary"]["actual_synthetic_reviews_generated"] == 0
    assert result["records"][3]["research_state"] == "unmatched_model"
    assert all(row["production_allocation"] is None for row in result["records"])


def test_rejects_approved_or_allocated_input():
    row = _row("a", 2, 1)
    row["approved_real_available"] = "1"
    with pytest.raises(ValueError, match="unapproved"):
        build_research_scenario([row])


def test_rejects_unmatched_product_with_research_reviews():
    with pytest.raises(ValueError, match="lacks confirmed model"):
        build_research_scenario([_row("a", 2, 1, "unmatched")])


def test_rejects_duplicate_product():
    with pytest.raises(ValueError, match="duplicate product"):
        build_research_scenario([_row("a", 2, 1), _row("a", 2, 1)])
