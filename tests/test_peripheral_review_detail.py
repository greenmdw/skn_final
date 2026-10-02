"""Peripheral review fit is exposed, but its external ranking weight remains zero."""
import pytest

from src.dto import (
    Candidate, PeripheralRequirement, ReviewRequirementProfile, ReviewScoreDetail,
)
from src.engine.peripheral_select import rank_candidates


def _review(value: float) -> ReviewScoreDetail:
    return ReviewScoreDetail(
        profile=ReviewRequirementProfile(
            profile_version="profile-test", analysis_version="analysis-test", part_type="mouse"),
        value=value,
    )


def test_different_review_fit_is_visible_but_does_not_change_peripheral_rank_or_score():
    requirement = PeripheralRequirement(kind="mouse", hard={}, soft={})
    candidates = [
        Candidate(product_key="a", slot="mouse", name="A", price=100, review_detail=_review(0.1)),
        Candidate(product_key="b", slot="mouse", name="B", price=100, review_detail=_review(0.9)),
    ]
    weights = {"가격": 0.0, "선호적합": 0.5, "데이터충실": 0.5, "리뷰": 0.0}

    baseline = rank_candidates("mouse", requirement,
                               [candidate.model_copy(update={"review_detail": None}) for candidate in candidates],
                               weights)
    ranked = rank_candidates("mouse", requirement, candidates, weights, require_review_details=True)

    assert [candidate.product_key for candidate in ranked] == ["a", "b"]
    assert [candidate.score for candidate in ranked] == [0.75, 0.75]
    assert [candidate.score for candidate in ranked] == [candidate.score for candidate in baseline]
    assert [candidate.breakdown["리뷰"] for candidate in ranked] == [0.1, 0.9]
    assert [candidate.review_detail.value for candidate in ranked] == [0.1, 0.9]


def test_runtime_peripheral_ranking_rejects_missing_review_detail():
    requirement = PeripheralRequirement(kind="speaker", hard={}, soft={})
    candidate = Candidate(product_key="s", slot="speaker", name="S", price=100)
    with pytest.raises(ValueError, match="review score missing"):
        rank_candidates("speaker", requirement, [candidate], {"리뷰": 0.0}, require_review_details=True)


def test_response_schema_preserves_selected_and_alternative_review_evidence():
    from src.dto import PeripheralPick, PeripheralResult, ReviewAspectContribution, ReviewEvidenceMember
    from src.engine.peripheral_payload import peripheral_payload
    from src.schemas import PeripheralsOut

    detail = _review(0.6).model_copy(update={"contributions": [ReviewAspectContribution(
        aspect_code="tracking_input", context_code="actual_use", rule_id="rule-1",
        aggregate_id="aggregate-1", alpha=1.0, p=1, n=0, mixed=0, k=4,
        q=0.6, alpha_q=0.6, evidence_state="observed", members=[ReviewEvidenceMember(
            observation_id="observation-1", document_id="document-1", source_code="test",
            direction="positive", observation_text="Tracking worked during use",
            evidence_sentences=["Tracking worked during use"],
        )],
    )]})
    selected = Candidate(product_key="selected", slot="mouse", name="Selected", price=100,
                         review_detail=_review(0.5))
    alternative = Candidate(product_key="alternative", slot="mouse", name="Alternative", price=110,
                            review_detail=detail)
    result = PeripheralResult(status="ready", picks=[PeripheralPick(
        kind="mouse", candidate=selected, alternatives=[alternative],
    )])

    response = PeripheralsOut.model_validate(peripheral_payload(result)).model_dump(mode="json")

    item = response["items"][0]
    assert item["review"] == selected.review_detail.model_dump(mode="json")
    assert item["alternatives"][0]["review"] == detail.model_dump(mode="json")
    assert item["review_weight"] == item["alternatives"][0]["review_weight"] == 0.0
