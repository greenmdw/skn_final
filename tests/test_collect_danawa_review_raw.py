"""Offline checks for local raw-review collection and safe resume."""

import hashlib
import json

import pytest

from scripts.collect_danawa_review_raw import collect_batch, extract_page, load_targets, write_results


HTML = '''<li class="danawa-prodBlog-companyReview-clazz-more"><span class="star_mask" style="width:80%"></span><span class="date">2026.09.21.</span><span class="name">PRIVATE AUTHOR</span><a id="danawa-prodBlog-companyReview-button-block-123"></a><div class="atc_cont">팬 소음이 적습니다.</div></li>'''
BODY = "팬 소음이 적습니다."
ROW = {
    "source": "danawa_company_product_review", "source_pcode": "1", "page": 1,
    "external_review_key": "123", "product_key": "cpu:test", "body_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
    "model_match_status": "model_family_matched", "usage_status": "unreviewed",
}


def test_extract_original_text_without_author():
    rows, missing = extract_page(HTML, [ROW], "2026-09-28T00:00:00+00:00")
    assert missing == [] and rows[0]["text"] == BODY
    assert rows[0]["text_matches_metadata_hash"] is True
    assert "PRIVATE AUTHOR" not in json.dumps(rows, ensure_ascii=False)
    assert rows[0]["usage_status"] == "unreviewed_local_raw_research_only"


def test_load_targets_rejects_unmatched(tmp_path):
    path = tmp_path / "metadata.jsonl"
    path.write_text(json.dumps({**ROW, "model_match_status": "needs_model_review"}) + "\n")
    with pytest.raises(ValueError):
        load_targets(path)


def test_batch_resumes_without_refetching_or_duplication(tmp_path):
    calls = []

    def fetch(pcode, page, limit):
        calls.append((pcode, page, limit))
        return HTML

    targets = {("1", 1): [ROW]}
    first = collect_batch(targets, {}, 1, 1.0, fetch=fetch, sleep=lambda _: None)
    second = collect_batch(targets, first, 1, 1.0, fetch=fetch, sleep=lambda _: None)
    assert calls == [("1", 1, 10)]
    assert len(second["records"]) == 1
    report = write_results(tmp_path, second)
    assert report["raw_review_rows"] == 1 and report["db_imported"] is False
    assert json.loads((tmp_path / "reviews.json").read_text(encoding="utf-8"))["records"][0]["text"] == BODY
