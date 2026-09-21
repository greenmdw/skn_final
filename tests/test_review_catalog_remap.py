"""새 PC 카탈로그 키는 확인된 동일 상품의 기존 리뷰에만 연결한다."""
import csv
import json

import pytest

from src.config import PARTS_ASIN_MAP, REVIEW_RISK_JSON, REVIEW_SUMMARIES_DEMO, REVIEW_SUSPECT_COUNTS
from src.repo.review_repo import (
    REVIEW_CATALOG_MAP, ProductRiskStore, ReviewSummaryDemoFile,
    SuspectCountFile, load_review_catalog_map,
)

# data/amazon23/pcparts_product_risk.json 은 .gitignore 라 새 체크아웃에는 없다(따로 전달). 없으면 이 파일을 읽는 테스트만 skip.
needs_risk_file = pytest.mark.skipif(
    not REVIEW_RISK_JSON.exists(),
    reason=f"{REVIEW_RISK_JSON} 없음 — 별도 전달 파일(docs/pc_pipeline_quickstart.md 참고)",
)


def test_crosswalk_covers_legacy_data_without_guessing_missing_skus():
    summaries = json.loads(REVIEW_SUMMARIES_DEMO.read_text(encoding="utf-8"))
    with REVIEW_CATALOG_MAP.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(summaries) == 51
    assert {r["legacy_key"] for r in rows} == {r["product_key"] for r in summaries}
    mapping = load_review_catalog_map()
    assert len(mapping) == 23
    assert len(set(mapping.values())) == len(mapping)
    mapped = set(mapping.values())
    assert sum(r["total_reviews"] for r in summaries if r["product_key"] in mapped) == 17270
    assert sum(len(r["top_summaries"]) for r in summaries if r["product_key"] in mapped) == 69
    assert mapping["case:프랙탈-디자인:north"] == "fractal-design-north"
    # 용량·접미사가 달라서 모델 단위로 뭉칠 수 없는 예.
    assert "samsung-990-pro-1tb" not in mapped
    assert "amd-ryzen-7-7700" not in mapped
    assert "noctua-nh-d15" not in mapped


@needs_risk_file
def test_new_key_reads_existing_observation_demo_and_suspect_counts():
    key = "motherboard:asus:tuf-gaming-b650-plus-wifi"
    legacy = "asus-tuf-gaming-b650-plus-wifi"
    risk = ProductRiskStore(REVIEW_RISK_JSON, PARTS_ASIN_MAP)
    demo = ReviewSummaryDemoFile(REVIEW_SUMMARIES_DEMO)
    suspects = SuspectCountFile(REVIEW_SUSPECT_COUNTS)
    assert risk.resolve(key) == risk.resolve(legacy)
    assert risk.get(key) == risk.get(legacy)
    assert demo.get(key) == demo.get(legacy)
    assert suspects.get(key) == suspects.get(legacy)


@needs_risk_file
def test_unmatched_new_sku_does_not_inherit_related_reviews():
    key = "cpu:amd:ryzen-7-7700x"
    risk = ProductRiskStore(REVIEW_RISK_JSON, PARTS_ASIN_MAP)
    demo = ReviewSummaryDemoFile(REVIEW_SUMMARIES_DEMO)
    assert risk.get(key) is None
    assert demo.get(key) is None
