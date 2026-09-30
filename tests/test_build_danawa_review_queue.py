import pytest

from scripts.build_danawa_review_queue import build_queue, validate_search_matches


def test_existing_urls_are_only_candidates():
    key = "cpu:intel:core-i5-12400f"
    plan = {"records": [{"sheet": "CPU", "manufacturer": "Intel", "model": "Core i5-12400F",
                         "source_urls": ["https://prod.danawa.com/info/?pcode=16101353&keyword=12400F"]}]}
    queue, report = build_queue(plan, {(key, "16101353")})
    assert report["products"] == 1 and report["model_family_matched_products"] == 1
    assert queue[0]["danawa_candidates"][0]["model_match_status"] == "model_family_matched"
    assert queue[0]["review_use_status"] == "unreviewed"
    assert report["new_network_requests"] == 0 and report["usage_approved"] is False


def test_missing_url_is_not_a_zero_review_count():
    plan = {"records": [{"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F",
                         "source_urls": []}]}
    queue, report = build_queue(plan, set())
    assert queue[0]["candidate_count"] == 0
    assert report["products_without_danawa_url"] == 1
    assert "review_count" not in queue[0]


def test_curated_match_adds_candidate_when_old_plan_has_no_url():
    key = "cpu:intel:core-i3-12100f"
    plan = {"records": [{"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F",
                         "source_urls": []}]}
    queue, report = build_queue(plan, {(key, "12345")})
    assert queue[0]["danawa_candidates"][0]["pcode"] == "12345"
    assert report["products_with_one_danawa_url"] == 1


def test_duplicate_catalog_products_rejected():
    row = {"sheet": "CPU", "manufacturer": "Intel", "model": "Core i5-12400F", "source_urls": []}
    with pytest.raises(ValueError, match="duplicate catalog product"):
        build_queue({"records": [row, row]}, set())


def test_search_match_requires_recorded_title() -> None:
    candidates = [{"key": "cpu:intel:core-i3-12100f", "hits": [{
        "url": "https://prod.danawa.com/info/?pcode=12345",
        "title": "인텔 12100F : 다나와 가격비교",
    }]}]
    assert validate_search_matches([{"product_key": "cpu:intel:core-i3-12100f", "pcode": "12345",
                                     "source_title": "인텔 12100F"}], candidates) == {
                                         ("cpu:intel:core-i3-12100f", "12345")}
    with pytest.raises(ValueError, match="recorded title evidence"):
        validate_search_matches([{"product_key": "cpu:intel:core-i3-12100f", "pcode": "12345",
                                  "source_title": "다른 제품"}], candidates)


def test_same_pcode_cannot_be_claimed_by_two_catalog_products() -> None:
    plan = {"records": [
        {"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F", "source_urls": []},
        {"sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-13100F", "source_urls": []},
    ]}
    with pytest.raises(ValueError, match="pcode assigned to two catalog products"):
        build_queue(plan, {("cpu:intel:core-i3-12100f", "12345"),
                           ("cpu:intel:core-i3-13100f", "12345")})
