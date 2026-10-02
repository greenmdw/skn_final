"""[3-B] consumes the injected review fit R without consulting the legacy risk store."""
from src.dto import (
    Candidate,
    ReviewAspectContribution,
    ReviewRequirementAttribute,
    ReviewRequirementProfile,
    ReviewScoreDetail,
)
from src.engine import stage3b_rank


def _detail(value: float) -> ReviewScoreDetail:
    profile = ReviewRequirementProfile(
        profile_version="test-profile", analysis_version="test-analysis", part_type="gpu",
        attributes=[ReviewRequirementAttribute(
            aspect_code="fan_quietness", context_code="gaming_load", alpha=1,
            selection_reason="test", selected_rule_id="rule-1",
        )],
    )
    return ReviewScoreDetail(
        profile=profile, value=value,
        contributions=[ReviewAspectContribution(
            aspect_code="fan_quietness", context_code="gaming_load", rule_id="rule-1",
            alpha=1, p=3, n=1, k=4, q=0.625, alpha_q=0.625,
            evidence_state="observed",
        )],
    )


def test_rank_preserves_full_r_and_candidate_detail(monkeypatch):
    # A callable that would fail if scoring still reached the legacy behavior store.
    from src.repo import review_repo
    monkeypatch.setattr(review_repo, "default_risk_store", lambda: (_ for _ in ()).throw(AssertionError()))
    candidate = Candidate(product_key="gpu", slot="GPU", name="GPU", review_detail=_detail(0.525))
    scored = stage3b_rank._score(candidate, None, 1, "GPU", {})
    assert scored.breakdown["리뷰"] == 0.525
    assert scored.review_detail.value == 0.525


def test_runtime_rank_rejects_missing_injected_review_detail():
    from src.dto import HardFilterResult, RequirementSpec, Slots

    candidate = Candidate(product_key="gpu", slot="GPU", name="GPU")
    spec = RequirementSpec(list_id="r", category="computer", mode="build",
                           targets={"GPU": {}}, budget={"total": 100, "alloc": {"GPU": 1}})
    slots = Slots(category="computer", mode="build", objective_text="", values={})
    try:
        stage3b_rank.run(HardFilterResult(slots={"GPU": [candidate]}), spec, slots,
                         lambda _message: None, require_review_details=True)
    except ValueError as exc:
        assert "review score is missing" in str(exc)
    else:
        raise AssertionError("runtime rank accepted a candidate without review detail")
