"""No-network checks for the small Danawa metadata pilot."""

import json

import pytest

from scripts.collect_danawa_review_pilot import (
    DEFAULT_MATCHES, load_model_matches, parse_review_page, pcode_from_url,
    select_pilot_products, write_results,
)


HTML = """
<ul class="rvw_list"><li class="danawa-prodBlog-companyReview-clazz-more">
  <div class="top_info"><span class="star_mask" style="width:80%"></span>
    <span class="mall"><span>판매처</span></span>
    <span class="date">2026.09.21.</span><span class="name">DO NOT STORE</span>
    <a id="danawa-prodBlog-companyReview-button-block-12345"></a></div>
  <div class="rvw_atc"><div class="atc_cont"><p>예시 제목</p><div class="atc">예시 후기입니다.</div></div></div>
</li></ul>
"""
PRODUCT = {"sheet": "CPU", "product_key": "cpu:intel:core-i5-12400f", "pcode": "16101353",
           "product_url": "https://prod.danawa.com/info/?pcode=16101353",
           "match_status": "model_family_matched"}


def test_parser_keeps_metadata_and_drops_original_text_and_author():
    rows, invalid = parse_review_page(HTML, PRODUCT, 1)
    assert invalid == 0 and len(rows) == 1
    row = rows[0]
    assert row["external_review_key"] == "12345"
    assert row["review_posted_date"] == "2026-09-21"
    assert row["rating"] == 4
    assert row["displayed_mall"] == "판매처"
    assert row["body_chars"] > 0 and len(row["body_sha256"]) == 64
    assert "DO NOT STORE" not in json.dumps(row)
    assert "예시 후기" not in json.dumps(row, ensure_ascii=False)
    assert row["model_match_status"] == "model_family_matched"
    assert row["sku_match_status"] == "not_evaluated"
    assert row["usage_status"] == "unreviewed"


def test_opinion_board_is_not_a_product_review():
    html = '<li class="cmt_item" id="danawa-prodBlog-productOpinion-list-self-9">의견</li>'
    assert parse_review_page(html, PRODUCT, 1) == ([], 0)


def test_pcode_accepts_only_expected_product_url():
    assert pcode_from_url(PRODUCT["product_url"]) == "16101353"
    with pytest.raises(ValueError):
        pcode_from_url("https://example.invalid/info/?pcode=16101353")


def test_pilot_selection_requires_single_pcode_and_covers_sheet():
    plan = {"records": [
        {"sheet": "CPU", "manufacturer": "Intel", "model": "Core i5-12400F",
         "source_urls": [PRODUCT["product_url"]], "observed_family_reviews": 10},
        {"sheet": "CPU", "manufacturer": "Intel", "model": "Core i7-12700K",
         "source_urls": [PRODUCT["product_url"], PRODUCT["product_url"]],
         "observed_family_reviews": 100},
    ]}
    selected = select_pilot_products(plan)
    assert len(selected) == 1 and selected[0]["pcode"] == "16101353"
    assert selected[0]["match_status"] == "needs_model_review"
    selected = select_pilot_products(plan, model_matches={(PRODUCT["product_key"], PRODUCT["pcode"])})
    assert selected[0]["match_status"] == "model_family_matched"


def test_curated_pilot_model_matches_cover_eight_categories():
    matches = load_model_matches(DEFAULT_MATCHES)
    assert len(matches) >= 8


def test_written_artifacts_do_not_contain_review_text(tmp_path):
    rows, _ = parse_review_page(HTML, PRODUCT, 1)
    write_results(tmp_path, rows, [{**PRODUCT, "review_rows": 1, "error": None}])
    content = (tmp_path / "review_metadata.jsonl").read_text(encoding="utf-8")
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert "예시 후기" not in content and "DO NOT STORE" not in content
    assert report["usage_approved"] is False
    assert report["sku_matches_approved"] is False
