"""Keep external metadata and labeled synthetic previews on separate paths."""

from copy import deepcopy

import pytest

from scripts.audit_review_evidence_readiness import audit


POLICY = {"sources": {
    "danawa_company_product_review": {"status": "unreviewed", "permitted_use": "metadata_pilot_only"},
    "truefit_synthetic_reviews_pilot_v1": {"status": "demo_only", "permitted_use": "labeled_synthetic_preview_only"},
}}
METADATA = [{"source": "danawa_company_product_review", "external_review_key": "1",
             "product_key": "cpu:intel:core-i5-12400f",
             "model_match_status": "model_family_matched"}]
SYNTHETIC = {"corpus": "synthetic", "usage": "demo_only", "cards": [{
    "display_label": "합성 리뷰 예시 1건 (실제 고객 후기 아님)",
    "demo_display_eligible": True, "production_ranking_eligible": False,
    "observed_customer_review_count": None, "observed_customer_rating": None,
    "review_examples": [{"sample_id": "synthetic-1", "text": "생성된 예시"}],
}]}


def test_real_metadata_remains_unapproved_while_synthetic_is_demo_only():
    result = audit(METADATA, SYNTHETIC, POLICY)
    assert result["external_metadata_rows"] == 1
    assert result["external_model_matched_rows"] == 1
    assert result["approved_real_review_evidence_rows"] == 0
    assert result["approved_real_inventory_count"] is None
    assert result["synthetic_demo_examples"] == 1
    assert result["database_import_performed"] is False


@pytest.mark.parametrize("field", ["text", "body", "original_text", "username", "author_ip"])
def test_external_original_text_and_identifiers_are_rejected(field):
    rows = deepcopy(METADATA)
    rows[0][field] = "must not persist"
    with pytest.raises(ValueError, match="external metadata contains"):
        audit(rows, SYNTHETIC, POLICY)


def test_duplicate_review_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate external review key"):
        audit(METADATA * 2, SYNTHETIC, POLICY)


def test_synthetic_cannot_claim_observed_rating():
    demo = deepcopy(SYNTHETIC)
    demo["cards"][0]["observed_customer_rating"] = 4.5
    with pytest.raises(ValueError, match="synthetic cards"):
        audit(METADATA, demo, POLICY)


def test_unknown_source_is_rejected():
    rows = deepcopy(METADATA)
    rows[0]["source"] = "unreviewed_other_source"
    with pytest.raises(ValueError, match="unknown external review source"):
        audit(rows, SYNTHETIC, POLICY)


def test_changing_source_status_does_not_silently_approve_real_reviews():
    policy = deepcopy(POLICY)
    policy["sources"]["danawa_company_product_review"]["status"] = "approved"
    with pytest.raises(ValueError, match="approved summaries need a separate pipeline"):
        audit(METADATA, SYNTHETIC, policy)
