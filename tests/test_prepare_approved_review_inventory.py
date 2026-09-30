from copy import deepcopy

import pytest

from scripts.plan_review_mix import build_plan
from scripts.prepare_approved_review_inventory import prepare_inventory


KEY = "cpu:intel:core-i5-12400f"
POLICY = {"sources": {"consented_first_party": {
    "status": "approved", "permitted_use": "derived_summary_and_count",
    "approval_reference": "consent-policy-v1",
}}}
ROW = {
    "source": "consented_first_party", "external_review_key": "review-1",
    "original_url": "https://reviews.example.com/review/1", "product_key": KEY,
    "model_match_status": "model_family_matched", "usage_status": "approved",
    "summary_status": "approved", "summary": "조립 과정이 무난했다는 의견",
    "rating": 4, "review_posted_date": "2026-09-01", "is_synthetic": False,
    "text_hash": "a" * 64, "body_chars": 80,
}


def test_approved_summary_generates_planner_inventory(tmp_path):
    rows, report = prepare_inventory([ROW], POLICY, {KEY})
    assert rows == [{"product_key": KEY, "available_real_count": 1,
                     "source_ref": "consented_first_party", "review_ids_verified": "yes",
                     "usage_approved": "yes"}]
    assert report["approved_real_reviews"] == 1
    plan = build_plan({"records": [{"sheet": "CPU", "manufacturer": "Intel",
                                    "model": "Core i5-12400F", "planned_synthetic_reviews": 20}]},
                      {KEY: 1})
    assert plan["records"][0]["allocated_real"] == 1
    assert plan["records"][0]["allocated_synthetic"] == 1


@pytest.mark.parametrize("change", [
    {"is_synthetic": True}, {"usage_status": "pending"},
    {"summary_status": "pending"}, {"model_match_status": "needs_model_review"},
    {"original_url": "https://source.invalid/review/1"}, {"rating": 0},
    {"review_posted_date": "bad-date"}, {"summary": ""}, {"text": "original"},
])
def test_invalid_or_unapproved_review_is_rejected(change):
    row = {**ROW, **change}
    with pytest.raises(ValueError):
        prepare_inventory([row], POLICY, {KEY})


def test_source_approval_cannot_be_inferred_from_model_match():
    policy = deepcopy(POLICY)
    policy["sources"]["consented_first_party"]["status"] = "unreviewed"
    with pytest.raises(ValueError, match="source use is not explicitly approved"):
        prepare_inventory([ROW], policy, {KEY})


def test_duplicate_review_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate source/review ID"):
        prepare_inventory([ROW, ROW], POLICY, {KEY})


def test_distinct_ids_with_same_body_signature_are_rejected():
    other = {**ROW, "external_review_key": "review-2",
             "original_url": "https://reviews.example.com/review/2"}
    with pytest.raises(ValueError, match="duplicate body/date/rating signature"):
        prepare_inventory([ROW, other], POLICY, {KEY})


def test_no_approved_input_does_not_mean_zero_real_reviews():
    rows, report = prepare_inventory([], POLICY, {KEY})
    assert rows == [] and report["status"] == "no_approved_real_reviews_submitted"
