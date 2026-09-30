"""Offline checks for real/synthetic slots and truthful missing counts."""

import copy

import pytest

from scripts.build_review_mix_json import build_mix


PLAN = {"records": [{"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F",
                     "planned_synthetic_reviews": 4}]}
KEY = "cpu:intel:core-i3-12100f"
CATALOG = {"catalog": [{"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F",
                        "attributes": {"소켓 규격": "LGA1700", "상품 URL": "https://example.test/spec"}}]}
REAL = {"source": "danawa_company_product_review", "external_review_key": "123", "product_key": KEY,
        "text": "원문 후기", "rating": 4, "review_posted_date": "2026-09-01",
        "source_product_url": "https://prod.danawa.com/info/?pcode=1", "source_pcode": "1",
        "displayed_mall": "판매처", "model_match_status": "model_family_matched",
        "sku_match_status": "not_evaluated", "text_matches_metadata_hash": True}
RAW = {"source": "danawa_company_product_review", "contains_original_review_text": True,
       "status": "unreviewed_local_raw_research_only", "records": [REAL]}


def test_missing_real_slot_stays_null_and_synthetic_is_reduced_to_real_count():
    mix = build_mix(PLAN, RAW, CATALOG)
    product = mix["products"][0]
    assert mix["summary"]["target_real"] == mix["summary"]["target_synthetic"] == 2
    assert mix["summary"]["real_filled"] == 1
    assert product["real_reviews"][1] is None
    assert product["real_missing"] == 1 and product["mix_complete"] is False
    assert product["real_reviews"][0]["text"] == "원문 후기"
    assert len(product["synthetic_reviews"]) == 1
    assert product["filled_mix_balanced"] is True
    assert product["synthetic_excluded_by_ratio"] == 1
    assert len(mix["excluded_synthetic_reviews"]) == 1
    assert all(row["review_posted_date"] is None and row["author_ref"] is None
               and row["kind"] == "synthetic" and row["review_theme"]
               for row in product["synthetic_reviews"])
    assert mix["usage_approved"] is False and mix["db_imported"] is False


def test_mix_is_reproducible_except_creation_time():
    first = build_mix(PLAN, RAW, CATALOG)
    second = build_mix(PLAN, RAW, CATALOG)
    first.pop("created_at_utc")
    second.pop("created_at_utc")
    assert first == second


def test_rejects_duplicate_or_changed_real_reviews():
    raw = copy.deepcopy(RAW)
    raw["records"].append(copy.deepcopy(REAL))
    with pytest.raises(ValueError, match="duplicate real"):
        build_mix(PLAN, raw, CATALOG)
    raw["records"] = [{**REAL, "text_matches_metadata_hash": False}]
    with pytest.raises(ValueError, match="changed real"):
        build_mix(PLAN, raw, CATALOG)


def test_no_real_reviews_keeps_both_target_slots_explicit():
    raw = {**RAW, "records": []}
    mix = build_mix(PLAN, raw, CATALOG)
    product = mix["products"][0]
    assert product["real_reviews"] == [None, None]
    assert len(product["synthetic_reviews"]) == 2
    assert product["synthetic_excluded_by_ratio"] == 0
    assert product["filled_mix_balanced"] is False
    assert mix["summary"]["products_with_no_real"] == 1
