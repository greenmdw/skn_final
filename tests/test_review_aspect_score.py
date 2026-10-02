from copy import deepcopy
from uuid import uuid4

import pytest

from src.dto import Candidate
from src.services.review_aspect_score import (
    ReviewProfileConfigurationError,
    ReviewProductIdentifierError,
    build_review_requirement_profile,
    calculate_review_score,
    load_review_profile_config,
)


@pytest.fixture
def gpu_rules():
    version = load_review_profile_config()["analysis_version"]
    contexts = {
        "coil_quietness": "gaming_load",
        "fan_quietness": "gaming_load",
        "gaming_performance": "gaming_load",
        "operational_stability": "duration_unknown",
        "thermal_management": "gaming_load",
    }
    return [
        {"rule_id": str(uuid4()), "analysis_version": version, "part_type": "gpu",
         "aspect_code": aspect, "context_code": context}
        for aspect, context in contexts.items()
    ]


def _profile(rules, values=None, *, assumed_keys=()):
    return build_review_requirement_profile(
        "gpu", values or {"purpose": "game"}, assumed_keys=assumed_keys,
        registered_rules=rules,
    )


def _rule_snapshot(profile, product_id, overrides=None):
    overrides = overrides or {}
    rules = {}
    for attribute in profile.attributes:
        if attribute.selected_rule_id is None:
            continue
        default = {
            "rule_id": attribute.selected_rule_id,
            "analysis_version": profile.analysis_version,
            "part_type": "gpu",
            "aspect_code": attribute.aspect_code,
            "context_code": attribute.context_code,
            "k": 4,
            "aggregate_id": None,
            "p": 0, "n": 0, "mixed": 0,
            "q": None,
            "source_observation_count": 0,
            "members": [],
        }
        default.update(overrides.get(attribute.aspect_code, {}))
        rules[attribute.selected_rule_id] = default
    return {
        "analysis_version": profile.analysis_version,
        "products": {product_id: {"product_id": product_id, "part_type": "gpu", "rules": rules}},
        "readiness": {"status": "version_has_aggregates_scoped_validation_only"},
    }


def test_gpu_game_example_q_0625_and_r_0525_keeps_full_precision(gpu_rules):
    profile = _profile(gpu_rules)
    product_id = str(uuid4())
    members = [
        {"observation_id": str(uuid4()), "document_id": str(uuid4()), "source_code": "test",
         "direction": direction, "observation_text": f"{direction} fan evidence",
         "evidence_sentences": [f"source sentence {i}"]}
        for i, direction in enumerate(["positive"] * 3 + ["negative"])
    ]
    snapshot = _rule_snapshot(profile, product_id, {"fan_quietness": {
        "aggregate_id": str(uuid4()), "p": 3, "n": 1, "mixed": 0,
        "q": 0.625, "source_observation_count": 4, "members": members,
    }})

    score = calculate_review_score(profile, snapshot, product_id)
    assert score.value == pytest.approx(0.525)
    fan = next(item for item in score.contributions if item.aspect_code == "fan_quietness")
    assert fan.q == 0.625
    assert fan.alpha == pytest.approx(0.2)
    assert fan.alpha_q == pytest.approx(0.125)
    assert fan.k == 4
    assert [member.direction for member in fan.members] == ["positive"] * 3 + ["negative"]


def test_balanced_mixed_only_and_missing_evidence_are_distinct(gpu_rules):
    profile = _profile(gpu_rules)
    product_id = str(uuid4())

    def member(direction):
        return {"observation_id": str(uuid4()), "document_id": str(uuid4()), "source_code": "src",
                "direction": direction, "observation_text": "observed", "evidence_sentences": ["quote"]}

    snapshot = _rule_snapshot(profile, product_id, {
        "fan_quietness": {"aggregate_id": str(uuid4()), "p": 1, "n": 1, "mixed": 0,
                           "q": 0.5, "source_observation_count": 2,
                           "members": [member("positive"), member("negative")]},
        "coil_quietness": {"aggregate_id": str(uuid4()), "p": 0, "n": 0, "mixed": 3,
                            "q": 0.5, "source_observation_count": 3,
                            "members": [member("mixed") for _ in range(3)]},
    })
    score = calculate_review_score(profile, snapshot, product_id)
    by_aspect = {item.aspect_code: item for item in score.contributions}
    assert by_aspect["fan_quietness"].evidence_state == "balanced"
    assert by_aspect["fan_quietness"].p == by_aspect["fan_quietness"].n == 1
    assert by_aspect["coil_quietness"].evidence_state == "mixed_only"
    assert by_aspect["coil_quietness"].mixed == 3
    assert by_aspect["gaming_performance"].evidence_state == "no_observations"
    assert by_aspect["gaming_performance"].neutral_reason == "no_observations_for_selected_rule"
    assert score.value == pytest.approx(0.5)


def test_quiet_and_noise_sensitive_share_one_alpha_boost_and_contexts_do_not_fallback(gpu_rules):
    config = load_review_profile_config()
    version = config["analysis_version"]
    low_load = {"rule_id": str(uuid4()), "analysis_version": version, "part_type": "gpu",
                "aspect_code": "fan_quietness", "context_code": "low_load"}
    rules = [*gpu_rules, low_load]
    quiet = _profile(rules, {"purpose": "game", "priority": "quiet", "noise_sensitive": True})
    by_aspect = {item.aspect_code: item for item in quiet.attributes}
    assert by_aspect["fan_quietness"].alpha == pytest.approx(1 / 3)
    assert by_aspect["coil_quietness"].alpha == pytest.approx(1 / 3)
    assert by_aspect["thermal_management"].alpha == pytest.approx(1 / 9)
    assert by_aspect["fan_quietness"].preference_source == "priority=quiet+noise_sensitive=true"

    game = _profile(rules, {"purpose": "game"})
    office = _profile(rules, {"purpose": "office"})
    assert next(a for a in game.attributes if a.aspect_code == "fan_quietness").context_code == "gaming_load"
    assert next(a for a in office.attributes if a.aspect_code == "fan_quietness").context_code == "workload_unknown"
    assert "selected_rule_missing:gpu.gaming_performance:workload_unknown" in office.diagnostics
    assert next(a for a in office.attributes if a.aspect_code == "gaming_performance").alpha == pytest.approx(0.2)

    assumed_game = _profile(rules, {"purpose": "game"}, assumed_keys=["purpose"])
    assert next(a for a in assumed_game.attributes if a.aspect_code == "fan_quietness").context_code == "workload_unknown"

    product_id = str(uuid4())
    profile = game
    alternative = next(rule for rule in rules if rule["aspect_code"] == "fan_quietness"
                      and rule["context_code"] == "low_load")
    # Gaming evidence is absent; a strong low-load aggregate must not fill that gap.
    snapshot = _rule_snapshot(profile, product_id)
    snapshot["products"][product_id]["rules"][alternative["rule_id"]] = {
        **alternative, "aggregate_id": str(uuid4()), "p": 10, "n": 0, "mixed": 0,
        "k": 4, "q": 0.9285714285714286, "source_observation_count": 10,
        "members": [],
    }
    detail = calculate_review_score(profile, snapshot, product_id)
    assert detail.value == pytest.approx(0.5)
    fan = next(item for item in detail.contributions if item.aspect_code == "fan_quietness")
    assert fan.evidence_state == "no_observations"
    assert fan.alpha == pytest.approx(0.2)


def test_missing_product_id_is_only_neutral_when_explicitly_allowed(gpu_rules):
    profile = _profile(gpu_rules)
    snapshot = {"analysis_version": profile.analysis_version, "products": {}}
    candidate = Candidate(product_key="demo", slot="GPU", name="Demo")
    assert candidate.product_id is None
    with pytest.raises(ReviewProductIdentifierError):
        calculate_review_score(profile, snapshot, candidate.product_id)
    detail = calculate_review_score(profile, snapshot, candidate.product_id, allow_missing_product_id=True)
    assert detail.value == 0.5
    assert detail.diagnostics[-1] == "product_id_missing:explicit_demo_neutral"


def test_profile_and_snapshot_version_or_type_mismatch_raise(gpu_rules):
    profile = _profile(gpu_rules)
    product_id = str(uuid4())
    snapshot = _rule_snapshot(profile, product_id)
    wrong_version = deepcopy(snapshot)
    wrong_version["analysis_version"] = "other-version"
    with pytest.raises(ReviewProfileConfigurationError, match="versions differ"):
        calculate_review_score(profile, wrong_version, product_id)
    wrong_type = deepcopy(snapshot)
    wrong_type["products"][product_id]["part_type"] = "cpu"
    with pytest.raises(ReviewProfileConfigurationError, match="types differ"):
        calculate_review_score(profile, wrong_type, product_id)


def test_config_contains_all_documented_49_aspects_and_102_contexts():
    config = load_review_profile_config()
    assert sum(len(aspects) for aspects in config["part_types"].values()) == 49
    assert sum(len(entry["contexts"]) for aspects in config["part_types"].values()
               for entry in aspects.values()) == 102
