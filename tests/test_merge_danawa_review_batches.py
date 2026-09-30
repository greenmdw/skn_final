import pytest

from scripts.merge_danawa_review_batches import merge


ROW = {"source": "danawa_company_product_review", "external_review_key": "1",
       "product_key": "cpu:x:y", "review_posted_date": "2026-09-01", "rating": 4,
       "body_sha256": "a" * 64, "theme_mentions": ["조립"]}


def test_repeat_fetch_does_not_double_count():
    rows, report = merge([[ROW], [ROW]])
    assert rows == [ROW]
    assert report["input_rows_with_repeat_fetches"] == 2
    assert report["unique_external_review_ids"] == 1


def test_same_body_signature_with_different_id_is_separated():
    rows, report = merge([[ROW, {**ROW, "external_review_key": "2"}]])
    assert len(rows) == 1
    assert report["possible_body_signature_duplicates_separated"] == 1


def test_conflicting_review_id_is_rejected():
    with pytest.raises(ValueError, match="conflicting metadata"):
        merge([[ROW], [{**ROW, "rating": 5}]])


def test_external_raw_text_is_rejected():
    with pytest.raises(ValueError, match="original text"):
        merge([[{**ROW, "text": "raw"}]])
