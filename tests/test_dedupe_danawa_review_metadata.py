import pytest

from scripts.dedupe_danawa_review_metadata import dedupe


ROW = {"source": "danawa_company_product_review", "product_key": "cpu:x:y",
       "external_review_key": "1", "review_posted_date": "2026-09-01", "rating": 5,
       "body_sha256": "a" * 64}


def test_same_body_date_rating_is_separated_without_raw_text():
    kept, duplicates = dedupe([ROW, {**ROW, "external_review_key": "2"}])
    assert kept == [ROW]
    assert duplicates == [{"product_key": "cpu:x:y", "kept_review_id": "1",
                           "possible_duplicate_review_id": "2",
                           "reason": "same_product_posted_date_rating_body_hash"}]


def test_distinct_rating_is_kept():
    kept, duplicates = dedupe([ROW, {**ROW, "external_review_key": "2", "rating": 4}])
    assert len(kept) == 2 and duplicates == []


def test_duplicate_review_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate review ID"):
        dedupe([ROW, ROW])
