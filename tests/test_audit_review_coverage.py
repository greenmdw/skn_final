"""Research review coverage must never become an approved allocation."""

import pytest

from scripts.audit_review_coverage import audit_coverage


def _inputs():
    plan = {"records": [
        {"product_key": "cpu:brand:a", "sheet": "CPU", "manufacturer": "Brand",
         "model": "A", "target_total_even": 10, "real_reviews_needed_for_target": 5,
         "verified_real_available": None, "allocated_real": None},
        {"product_key": "cpu:brand:b", "sheet": "CPU", "manufacturer": "Brand",
         "model": "B", "target_total_even": 6, "real_reviews_needed_for_target": 3,
         "verified_real_available": None, "allocated_real": None},
    ]}
    queue = [
        {"product_key": "cpu:brand:a", "danawa_candidates": [
            {"model_match_status": "model_family_matched"}]},
        {"product_key": "cpu:brand:b", "danawa_candidates": []},
    ]
    metadata = [{"product_key": "cpu:brand:a", "source": "danawa_company_product_review",
                 "external_review_key": str(i), "usage_status": "unreviewed",
                 "model_match_status": "model_family_matched"} for i in range(7)]
    return plan, queue, metadata


def test_research_counts_capped_at_target_without_allocation():
    rows, report = audit_coverage(*_inputs())
    assert report["research_metadata_rows"] == 7
    assert report["research_count_within_product_targets"] == 5
    assert report["research_count_shortfall_if_approved"] == 3
    assert report["approved_real_review_count"] is None
    assert report["allocated_reviews"] is None
    assert rows[0]["approved_real_available"] == "unknown"
    assert rows[1]["model_match_status"] == "unmatched"
    assert rows[1]["research_metadata_count"] == 0


def test_rejects_approved_input_as_wrong_pipeline():
    plan, queue, metadata = _inputs()
    metadata[0]["usage_status"] = "approved"
    with pytest.raises(ValueError, match="separate inventory pipeline"):
        audit_coverage(plan, queue, metadata)


def test_rejects_metadata_on_unmatched_product():
    plan, queue, metadata = _inputs()
    metadata[0]["product_key"] = "cpu:brand:b"
    with pytest.raises(ValueError, match="unmatched product"):
        audit_coverage(plan, queue, metadata)


def test_rejects_duplicate_external_review_ids():
    plan, queue, metadata = _inputs()
    metadata[1]["external_review_key"] = metadata[0]["external_review_key"]
    with pytest.raises(ValueError, match="duplicate external review ID"):
        audit_coverage(plan, queue, metadata)
