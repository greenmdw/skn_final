"""Pure request-profile selection and review-aspect score calculation."""
from __future__ import annotations

from math import fsum
from pathlib import Path
from typing import Any

import yaml

from src.config import CONFIG_DIR
from src.dto import (
    ReviewAspectContribution,
    ReviewEvidenceMember,
    ReviewRequirementAttribute,
    ReviewRequirementProfile,
    ReviewScoreDetail,
)


class ReviewProfileConfigurationError(ValueError):
    pass


class ReviewProductIdentifierError(ValueError):
    pass


def load_review_profile_config(path: Path | None = None) -> dict:
    source = path or (CONFIG_DIR / "review_aspect_profiles.yaml")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("profile_version") or not data.get("analysis_version"):
        raise ReviewProfileConfigurationError("review profile requires explicit profile and analysis versions")
    if data.get("default_base_weight") != 1 or data.get("quiet_base_weight") != 3:
        raise ReviewProfileConfigurationError("review profile base weights must be positive integer policy values")
    part_types = data.get("part_types")
    if not isinstance(part_types, dict) or not part_types:
        raise ReviewProfileConfigurationError("review profile has no part type mappings")
    for part_type, aspects in part_types.items():
        if not isinstance(aspects, dict) or not aspects:
            raise ReviewProfileConfigurationError(f"review profile has no aspect mappings for {part_type}")
        for aspect_code, entry in aspects.items():
            if (not aspect_code or not isinstance(entry, dict) or entry.get("policy") not in {
                "workload", "duration", "installation", "visual", "actual_use",
            } or not isinstance(entry.get("contexts"), list) or not entry.get("contexts")
                    or not all(isinstance(context, str) and context for context in entry["contexts"])):
                raise ReviewProfileConfigurationError(f"invalid mapping for {part_type}.{aspect_code}")
            if len(entry["contexts"]) != len(set(entry["contexts"])):
                raise ReviewProfileConfigurationError(f"duplicate context for {part_type}.{aspect_code}")
    return data


def _requested_context(policy: str, values: dict, assumed_keys: set[str]) -> tuple[str, str]:
    if policy == "actual_use":
        return "actual_use", "주변기기 규칙의 등록 조건 actual_use를 적용"
    if policy == "installation":
        return "installation_or_use", "설치·사용 편의의 등록 조건을 적용"
    if policy == "visual":
        return "visual_or_physical_inspection", "외관·물리 확인의 등록 조건을 적용"
    if policy == "duration":
        return "duration_unknown", "요청에 기간 조건이 없어 duration_unknown 적용"

    purpose = values.get("purpose")
    if purpose == "game" and "purpose" not in assumed_keys:
        return "gaming_load", "사용자가 명시한 game 용도에 gaming_load 적용"
    if purpose == "game":
        return "workload_unknown", "가정된 game 값은 명시 요청으로 보지 않아 workload_unknown 적용"
    if purpose in {"creation", "office", "study", "other"}:
        return "workload_unknown", f"purpose={purpose}에는 세부 부하 추론 없이 workload_unknown 적용"
    return "workload_unknown", "purpose 누락 또는 미지원 값으로 workload_unknown 적용"


def build_review_requirement_profile(
    part_type: str,
    values: dict[str, Any],
    *,
    assumed_keys: list[str] | set[str] | tuple[str, ...] = (),
    registered_rules: list[dict] | None = None,
    config: dict | None = None,
) -> ReviewRequirementProfile:
    """Select the same normalized alpha and context for every candidate of one part type."""
    config = config or load_review_profile_config()
    mappings = config["part_types"].get(part_type)
    if mappings is None:
        raise ReviewProfileConfigurationError(f"unsupported review part_type: {part_type}")
    assumed = set(assumed_keys)
    by_aspect_context: dict[tuple[str, str], dict] = {}
    if isinstance(registered_rules, dict):
        registered_rules = list(registered_rules.values())
    for rule in registered_rules or []:
        if rule.get("analysis_version") != config["analysis_version"]:
            raise ReviewProfileConfigurationError("registered rules contain a mixed analysis version")
        if rule.get("part_type") != part_type:
            raise ReviewProfileConfigurationError("registered rule part_type differs from requested profile")
        aspect = rule.get("aspect_code")
        context = rule.get("context_code")
        if aspect not in mappings or context not in mappings[aspect]["contexts"]:
            raise ReviewProfileConfigurationError(f"registered rule has no profile mapping: {aspect}/{context}")
        key = (aspect, context)
        if key in by_aspect_context:
            raise ReviewProfileConfigurationError(f"duplicate registered rule mapping: {aspect}/{context}")
        by_aspect_context[key] = rule

    quiet = values.get("priority") == "quiet" or values.get("noise_sensitive") is True
    quiet_aspects = set(config.get("quiet_aspects", [])) if quiet else set()
    base_weight = float(config["default_base_weight"])
    quiet_weight = float(config["quiet_base_weight"])
    raw: list[tuple[str, str, float, str, str, str | None]] = []
    diagnostics: list[str] = []
    for aspect, entry in mappings.items():
        context, reason = _requested_context(entry["policy"], values, assumed)
        context_is_registered = context in entry["contexts"]
        # GPU gaming_performance only has gaming_load registered. Other workload requests retain
        # this attribute's alpha and report a missing selected rule without condition fallback.
        matching_rule = by_aspect_context.get((aspect, context)) if context_is_registered else None
        rule_id = str(matching_rule["rule_id"]) if matching_rule else None
        if matching_rule is None:
            diagnostics.append(f"selected_rule_missing:{part_type}.{aspect}:{context}")
        weight = quiet_weight if aspect in quiet_aspects else base_weight
        pref = []
        if aspect in quiet_aspects and weight != base_weight:
            if values.get("priority") == "quiet":
                pref.append("priority=quiet")
            if values.get("noise_sensitive") is True:
                pref.append("noise_sensitive=true")
        raw.append((aspect, context, weight, reason,
                    "+".join(pref) if pref else "default", rule_id))

    total = sum(item[2] for item in raw)
    attributes = [ReviewRequirementAttribute(
        aspect_code=aspect, context_code=context, alpha=weight / total,
        selection_reason=reason, preference_source=preference_source,
        selected_rule_id=rule_id,
    ) for aspect, context, weight, reason, preference_source, rule_id in raw]
    if not attributes:
        diagnostics.append(f"no_profile_attributes:{part_type}")
    return ReviewRequirementProfile(
        profile_version=config["profile_version"], analysis_version=config["analysis_version"],
        part_type=part_type, attributes=attributes, diagnostics=diagnostics,
    )


def calculate_review_score(
    profile: ReviewRequirementProfile,
    snapshot: dict,
    product_id: str | None,
    *,
    allow_missing_product_id: bool = False,
) -> ReviewScoreDetail:
    """Calculate R without database access; repository data is an immutable request snapshot."""
    if snapshot.get("analysis_version") != profile.analysis_version:
        raise ReviewProfileConfigurationError("profile and repository snapshot analysis versions differ")
    if product_id is None:
        if not allow_missing_product_id:
            raise ReviewProductIdentifierError("candidate has no product_id for review scoring")
        return _missing_product_score(profile)
    product_key = str(product_id)
    product = snapshot.get("products", {}).get(product_key)
    if product is None:
        raise ReviewProductIdentifierError(f"product_id is absent from the review snapshot: {product_key}")
    if product.get("part_type") != profile.part_type:
        raise ReviewProfileConfigurationError("profile and candidate product types differ")
    rules = product.get("rules", {})
    contributions: list[ReviewAspectContribution] = []
    weighted_values: list[float] = []
    diagnostics = list(profile.diagnostics)
    for attribute in profile.attributes:
        rule = rules.get(attribute.selected_rule_id) if attribute.selected_rule_id else None
        if attribute.selected_rule_id and rule is None:
            raise ReviewProfileConfigurationError("selected rule is absent from the matching product snapshot")
        if rule is None:
            q = 0.5
            contributions.append(ReviewAspectContribution(
                aspect_code=attribute.aspect_code, context_code=attribute.context_code,
                rule_id=None, alpha=attribute.alpha, q=q, alpha_q=attribute.alpha * q,
                evidence_state="selected_rule_missing", neutral_reason="selected_rule_missing",
            ))
            weighted_values.append(attribute.alpha * q)
            continue
        if rule.get("analysis_version") != profile.analysis_version:
            raise ReviewProfileConfigurationError("rule and profile analysis versions differ")
        if rule.get("part_type") != profile.part_type or rule.get("aspect_code") != attribute.aspect_code \
                or rule.get("context_code") != attribute.context_code:
            raise ReviewProfileConfigurationError("selected rule identity does not match the profile")

        members = [ReviewEvidenceMember.model_validate(member) for member in rule.get("members", [])]
        p, n, mixed = int(rule.get("p", 0)), int(rule.get("n", 0)), int(rule.get("mixed", 0))
        if min(p, n, mixed) < 0 or any(
            isinstance(rule.get(key), bool) or int(rule.get(key, 0)) != rule.get(key, 0)
            for key in ("p", "n", "mixed")
        ):
            raise ReviewProfileConfigurationError("aggregate counts must be nonnegative integers")
        aggregate_id = rule.get("aggregate_id")
        if aggregate_id is None:
            if rule.get("source_observation_count", 0):
                raise ReviewProfileConfigurationError("source observation exists without its aggregate")
            q = 0.5
            evidence_state = "no_observations"
            neutral_reason = "no_observations_for_selected_rule"
            try:
                k = float(rule["k"])
            except (TypeError, ValueError) as exc:
                raise ReviewProfileConfigurationError("registered rule k is invalid") from exc
            if not 0 < k < float("inf"):
                raise ReviewProfileConfigurationError("registered rule k must be positive and finite")
        else:
            q = float(rule["q"])
            if not 0.0 <= q <= 1.0:
                raise ReviewProfileConfigurationError("aggregate q is outside [0,1]")
            evidence_state = "mixed_only" if p == 0 and n == 0 and mixed > 0 else (
                "balanced" if p == n and p + n > 0 else "observed"
            )
            neutral_reason = "balanced_positive_negative" if evidence_state == "balanced" else None
            try:
                k = float(rule["k"])
            except (TypeError, ValueError) as exc:
                raise ReviewProfileConfigurationError("aggregate k is invalid") from exc
            if not 0 < k < float("inf"):
                raise ReviewProfileConfigurationError("aggregate k must be positive and finite")
            expected_q = (p + k * 0.5) / (p + n + k)
            if abs(q - expected_q) > 1e-12:
                raise ReviewProfileConfigurationError("aggregate q does not match counts and k")
        contribution = attribute.alpha * q
        contributions.append(ReviewAspectContribution(
            aspect_code=attribute.aspect_code, context_code=attribute.context_code,
            rule_id=rule["rule_id"], aggregate_id=aggregate_id, alpha=attribute.alpha,
            p=p, n=n, mixed=mixed, k=k, q=q, alpha_q=contribution,
            evidence_state=evidence_state, neutral_reason=neutral_reason, members=members,
        ))
        weighted_values.append(contribution)
    value = fsum(weighted_values) if profile.attributes else 0.5
    if not 0 <= value <= 1:
        raise ReviewProfileConfigurationError("review score is outside [0,1]")
    return ReviewScoreDetail(
        profile=profile, value=value, contributions=contributions, diagnostics=diagnostics,
    )


def _missing_product_score(profile: ReviewRequirementProfile) -> ReviewScoreDetail:
    contributions = [ReviewAspectContribution(
        aspect_code=attribute.aspect_code, context_code=attribute.context_code,
        rule_id=attribute.selected_rule_id, alpha=attribute.alpha, q=0.5,
        alpha_q=attribute.alpha * 0.5, evidence_state="product_id_missing",
        neutral_reason="product_id_missing",
    ) for attribute in profile.attributes]
    return ReviewScoreDetail(
        profile=profile, value=0.5, contributions=contributions,
        diagnostics=[*profile.diagnostics, "product_id_missing:explicit_demo_neutral"],
    )
