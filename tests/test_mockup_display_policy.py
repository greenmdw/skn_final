"""Mockup copy must not claim a review verdict or a computed cleaned rating."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_review_copy_uses_observations_and_keeps_baby_domain():
    landing = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    translations = (ROOT / "frontend/js/i18n.js").read_text(encoding="utf-8")
    assert "리뷰에서는 무엇을 보나요?" in landing
    assert "개별 리뷰의 진위는 판정하거나 제외하지 않습니다." in landing
    assert "클렌징 전후 평점" not in landing
    assert "Suspected manipulated or duplicate reviews are removed" not in translations
    assert "유아용품 준비 시작하기" in landing


def test_review_card_is_labeled_as_observation():
    results = (ROOT / "frontend/js/pages/results.js").read_text(encoding="utf-8")
    assert "Review observations" in results
    assert "리뷰 관측 요약" in results
    assert "<h4>Review Cleansing Summary</h4>" not in results


def test_existing_flow_pages_share_scoped_mockup_style_without_bundle():
    for name in ("conditions", "results", "logs", "confirm", "report"):
        page = (ROOT / "frontend" / f"{name}.html").read_text(encoding="utf-8")
        assert 'class="tf-mockup-flow"' in page
        assert './css/mockup-flow.css' in page
        assert 'truefit.html' not in page
    category = (ROOT / "frontend/category.html").read_text(encoding="utf-8")
    assert 'mockup-flow.css' not in category


def test_result_evidence_panel_is_conditional_on_api_explanation():
    results = (ROOT / "frontend/js/pages/results.js").read_text(encoding="utf-8")
    assert "const insights = tfResultInsights(result);" in results
    assert "(insights ? '<aside class=\"result-evidence-pane\">" in results
