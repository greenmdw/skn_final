import json
from urllib.error import HTTPError

import pytest

from scripts.collect_danawa_review_batch import collect, selected_products, write_results


PRODUCT = {"sheet": "CPU", "product_key": "cpu:intel:core-i5-12400f", "pcode": "1",
           "product_url": "https://prod.danawa.com/info/?pcode=1", "match_status": "model_family_matched"}


def test_only_curated_candidates_selected():
    queue = [{"sheet": "CPU", "product_key": PRODUCT["product_key"], "danawa_candidates": [
        {"pcode": "1", "product_url": PRODUCT["product_url"], "model_match_status": "model_family_matched"},
        {"pcode": "2", "product_url": "https://prod.danawa.com/info/?pcode=2", "model_match_status": "needs_model_review"},
    ]}]
    assert selected_products(queue, 2) == [PRODUCT]
    assert selected_products(queue, 2, exclude_pcodes={"1"}) == []
    assert selected_products(queue, 2, include_pcodes={"2"}) == []
    queue[0]["danawa_candidates"][0]["match_basis"] = "live_page_title"
    assert selected_products(queue, 2, match_basis="live_page_title") == [PRODUCT]
    assert selected_products(queue, 2, match_basis="curated") == []


def test_batch_deduplicates_and_keeps_raw_text_out(monkeypatch, tmp_path):
    html = '<li class="danawa-prodBlog-companyReview-clazz-more"><span class="star_mask" style="width:80%"></span><span class="date">2026.09.21.</span><a id="danawa-prodBlog-companyReview-button-block-123"></a><div class="atc_cont">조립이 편해요</div></li>'
    monkeypatch.setattr("scripts.collect_danawa_review_batch.request_review_page", lambda *args: html)
    monkeypatch.setattr("scripts.collect_danawa_review_batch.time.sleep", lambda *args: None)
    observations, results = collect([PRODUCT], limit=10, max_pages=2, delay=1.0)
    assert len(observations) == 1 and observations[0]["theme_mentions"] == ["조립"]
    report = write_results(tmp_path, observations, results, 1)
    assert report["metadata_rows"] == 1 and report["usage_approved"] is False
    assert "조립이 편해요" not in (tmp_path / "review_metadata.jsonl").read_text(encoding="utf-8")


def test_403_stops_batch(monkeypatch):
    def forbidden(*args):
        raise HTTPError("https://prod.danawa.com", 403, "Forbidden", {}, None)
    monkeypatch.setattr("scripts.collect_danawa_review_batch.request_review_page", forbidden)
    observations, results = collect([PRODUCT, PRODUCT], limit=10, max_pages=1, delay=1.0)
    assert observations == [] and len(results) == 1 and results[0]["error"] == "HTTP 403"


def test_model_family_is_capped_at_100_unique_reviews(monkeypatch):
    monkeypatch.setattr("scripts.collect_danawa_review_batch.request_review_page",
                        lambda pcode, page, limit: str(page))
    monkeypatch.setattr("scripts.collect_danawa_review_batch.parse_review_page",
                        lambda html, product, page: ([{
                            "source": "danawa_company_product_review",
                            "external_review_key": f"{page}-{index}",
                            "product_key": product["product_key"],
                        } for index in range(10)], 0))
    monkeypatch.setattr("scripts.collect_danawa_review_batch.time.sleep", lambda *args: None)
    observations, results = collect([PRODUCT], limit=10, max_pages=15, delay=1.0)
    assert len(observations) == 100
    assert results[0]["pages_read"] == 10


@pytest.mark.parametrize("limit,pages,delay", [(11, 1, 1.0), (10, 16, 1.0), (10, 1, 0.1)])
def test_batch_caps(limit, pages, delay):
    with pytest.raises(ValueError):
        collect([], limit=limit, max_pages=pages, delay=delay)
