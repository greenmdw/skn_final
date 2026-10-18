"""Re-derive the review-score snapshot cited by docs/추천점수_시뮬레이션_검증계획_20261006.md.

Reads the private review seed bundle as files (no DB, no LLM), checks the manifest hashes, and writes
only derived counts and score distributions — never review text, reviewer data or observation text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median

from src.services.review_aspect_score import (
    build_review_requirement_profile,
    calculate_review_score,
    load_review_profile_config,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "data/review_seed"
DEFAULT_OUTPUT = ROOT / "docs/validation/score_snapshot_20261006.json"
BUNDLE_FILES = ("documents.json", "rules.json", "canonical_results.json", "consolidated_observation_drafts.json")
PC_PART_TYPES = ("cpu", "gpu", "mainboard", "ram", "ssd", "psu", "case", "cooler")
SCORING_FILES = ("src/services/review_aspect_score.py", "config/review_aspect_profiles.yaml")
# purpose is a required input on the main recommendation path, so game is always explicit there
# (assumed_keys stays empty). creation/office/study/other all select the same contexts; "other" stands in.
PROFILES = {
    "game_value": {"purpose": "game", "priority": "value"},
    "game_quiet": {"purpose": "game", "priority": "quiet"},
    "non_game_value": {"purpose": "other", "priority": "value"},
}
Q_LEVELS = (0, 0.025, 0.25, 0.5, 0.75, 0.975, 1)
_DIRECTION = {"positive": "p", "negative": "n", "mixed": "mixed"}


def _quantile(values: list[float], level: float) -> float:
    """Linear interpolation between order statistics (numpy's default method)."""
    xs = sorted(values)
    pos = (len(xs) - 1) * level
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _pn_buckets(totals: list[int]) -> dict:
    return {
        "groups": len(totals),
        "pn_0": sum(t == 0 for t in totals),
        "pn_1": sum(t == 1 for t in totals),
        "pn_1_to_5": sum(1 <= t <= 5 for t in totals),
        "pn_6_to_20": sum(6 <= t <= 20 for t in totals),
        "pn_over_20": sum(t > 20 for t in totals),
        "pn_max": max(totals, default=0),
    }


def load_bundle(bundle: Path) -> tuple[str, dict[str, list]]:
    manifest_bytes = (bundle / "bundle_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    for name in BUNDLE_FILES:
        if hashlib.sha256((bundle / name).read_bytes()).hexdigest() != manifest["sha256"][name]:
            raise ValueError(f"review bundle file differs from its manifest: {name}")
    data = {name: json.loads((bundle / name).read_text(encoding="utf-8"))
            for name in ("documents.json", "rules.json", "consolidated_observation_drafts.json")}
    return hashlib.sha256(manifest_bytes).hexdigest(), data


def summarize(documents: list[dict], rules: list[dict], observations: list[dict], config: dict) -> dict:
    """Bundle counts, P+N buckets, label review status, context usage and R per part type/profile."""
    rule_by_key = {(r["part_type"], r["aspect_code"], r["context_code"]): r for r in rules}
    if len(rule_by_key) != len(rules):
        raise ValueError("duplicate rule identity in the bundle")
    part_of_product: dict[str, str] = {}
    for doc in documents:
        if part_of_product.setdefault(doc["product_id"], doc["part_type"]) != doc["part_type"]:
            raise ValueError(f"product linked to two part types: {doc['product_id']}")

    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"p": 0, "n": 0, "mixed": 0})
    seen: set[tuple[str, str]] = set()
    group_of: list[tuple[str, str]] = []
    for obs in observations:
        rule = rule_by_key[(obs["part_type"], obs["aspect_code"], obs["context_code"])]
        if part_of_product.get(obs["product_id"]) != obs["part_type"]:
            raise ValueError(f"observation product/part mismatch: {obs['document_id']}")
        if (obs["document_id"], rule["id"]) in seen:
            raise ValueError(f"duplicate document/rule observation: {obs['document_id']}")
        seen.add((obs["document_id"], rule["id"]))
        key = (obs["product_id"], rule["id"])
        groups[key][_DIRECTION[obs["direction"]]] += 1
        group_of.append(key)

    k_of = {r["id"]: r["k"] for r in rules}
    q_values = [(g["p"] + k_of[rule_id] * 0.5) / (g["p"] + g["n"] + k_of[rule_id])
                for (_product, rule_id), g in groups.items()]
    pc_groups = [g for (product, _rule), g in groups.items() if part_of_product[product] in PC_PART_TYPES]
    rules_per_part = Counter(r["part_type"] for r in rules)
    per_doc = Counter(obs["document_id"] for obs in observations)

    # Label review status. The semantic decision is per document, inherited by each of its observations.
    status = Counter((obs["result_status"], obs["semantic_decision"]) for obs in observations)
    flagged = [obs["result_status"] == "unresolved" or obs["semantic_decision"] == "correction_needed"
               for obs in observations]

    rules_of_part = {part: [{"rule_id": r["id"], **r} for r in rules if r["part_type"] == part]
                     for part in PC_PART_TYPES}
    selected_context = {
        (name, part): {a.aspect_code: a.context_code for a in build_review_requirement_profile(
            part, values, registered_rules=rules_of_part[part], config=config).attributes}
        for name, values in PROFILES.items() for part in PC_PART_TYPES
    }
    pc_obs = [obs for obs in observations if obs["part_type"] in PC_PART_TYPES]
    usable = {name: sum(selected_context[(name, o["part_type"])].get(o["aspect_code"]) == o["context_code"]
                        for o in pc_obs) for name in ("game_value", "non_game_value")}
    never = Counter(o["context_code"] for o in pc_obs
                    if all(selected_context[(name, o["part_type"])].get(o["aspect_code"]) != o["context_code"]
                           for name in PROFILES))

    return {
        "scope": "descriptive_offline_review_snapshot_not_empirical_recommendation_validation",
        "analysis_version": config["analysis_version"],
        "profile_version": config["profile_version"],
        "documents": len(documents),
        "products_in_bundle": len(part_of_product),
        "observations": len(observations),
        "observed_groups": len(groups),
        "positive_negative_groups_1_to_5": _pn_buckets([g["p"] + g["n"] for g in groups.values()])["pn_1_to_5"],
        "q_quantiles": {format(level, "g"): round(_quantile(q_values, level), 6) for level in Q_LEVELS},
        "review_scores": _review_scores(rules_of_part, groups, part_of_product, config),
        "generator": "scripts/review_score_snapshot.py",
        "request_profiles": {name: {"values": values, "assumed_keys": []} for name, values in PROFILES.items()},
        "documents_with_observations": len(per_doc),
        "documents_with_multiple_observations": sum(count >= 2 for count in per_doc.values()),
        "rules": len(rules),
        "rule_k_values": sorted({r["k"] for r in rules}),
        "direction_counts": dict(Counter(obs["direction"] for obs in observations)),
        "posted_at_non_null_documents": sum(doc["posted_at"] is not None for doc in documents),
        "pn_buckets": {
            "all": _pn_buckets([g["p"] + g["n"] for g in groups.values()]),
            "pc": _pn_buckets([g["p"] + g["n"] for g in pc_groups]),
        },
        "pc_groups_with_pn_6_or_more_by_part": dict(sorted(Counter(
            part_of_product[product] for (product, _rule), g in groups.items()
            if part_of_product[product] in PC_PART_TYPES and g["p"] + g["n"] >= 6).items())),
        "possible_product_rule_cells": {
            "all": sum(rules_per_part[part] for part in part_of_product.values()),
            "pc": sum(rules_per_part[part] for part in part_of_product.values() if part in PC_PART_TYPES),
        },
        "label_status": {
            "result_status_by_semantic_decision": {
                result: {decision: count for (r, decision), count in sorted(status.items()) if r == result}
                for result in sorted({r for r, _decision in status})
            },
            "unresolved_or_correction_needed": sum(flagged),
            "groups_with_unresolved_or_correction_needed": len({key for key, bad in zip(group_of, flagged) if bad}),
            "import_gate_counts": dict(Counter(obs["import_gate"] for obs in observations)),
        },
        "pc_observation_context_usage": {
            "pc_observations": len(pc_obs),
            "usable_game_explicit": usable["game_value"],
            "usable_non_game": usable["non_game_value"],
            "never_usable": sum(never.values()),
            "never_usable_by_context": dict(never.most_common()),
        },
    }


def _review_scores(rules_of_part: dict, groups: dict, part_of_product: dict, config: dict) -> list[dict]:
    out = []
    for part in PC_PART_TYPES:
        products = sorted(p for p, t in part_of_product.items() if t == part)
        if not products:
            continue
        snapshot = {"analysis_version": config["analysis_version"], "products": {
            product: {"part_type": part, "rules": {rule["id"]: _snapshot_rule(rule, groups.get((product, rule["id"])))
                                                   for rule in rules_of_part[part]}}
            for product in products}}
        for name, values in PROFILES.items():
            profile = build_review_requirement_profile(part, values, registered_rules=rules_of_part[part], config=config)
            scores, coverage, no_evidence = [], [], 0
            for product in products:
                detail = calculate_review_score(profile, snapshot, product)
                has_pn = [(c.p or 0) + (c.n or 0) > 0 for c in detail.contributions]
                scores.append(detail.value)
                coverage.append(sum(c.alpha for c, hit in zip(detail.contributions, has_pn) if hit))
                no_evidence += not any(has_pn)
            out.append({
                "part_type": part, "profile": name, "purpose": values["purpose"], "priority": values["priority"],
                "n_products": len(products),
                "r_min": round(min(scores), 6), "r_p25": round(_quantile(scores, 0.25), 6),
                "r_median": round(median(scores), 6), "r_p75": round(_quantile(scores, 0.75), 6),
                "r_max": round(max(scores), 6),
                "no_selected_pn_evidence_products": no_evidence,
                "mean_alpha_coverage": round(fmean(coverage), 6),
            })
    return out


def _snapshot_rule(rule: dict, group: dict | None) -> dict:
    base = {"rule_id": rule["id"], "analysis_version": rule["analysis_version"], "part_type": rule["part_type"],
            "aspect_code": rule["aspect_code"], "context_code": rule["context_code"], "k": rule["k"], "members": []}
    if group is None:
        return {**base, "aggregate_id": None, "p": 0, "n": 0, "mixed": 0, "q": None, "source_observation_count": 0}
    k = rule["k"]
    return {**base, "aggregate_id": f"file:{rule['id']}", **group,
            "q": (group["p"] + k * 0.5) / (group["p"] + group["n"] + k),
            "source_observation_count": group["p"] + group["n"] + group["mixed"]}


def _code_state() -> dict:
    """Commit that produced the snapshot and whether the scoring files had local edits."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *SCORING_FILES], cwd=ROOT, check=True,
                               capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"code_commit": None, "scoring_files_modified": None}
    return {"code_commit": commit, "scoring_files_modified": bool(dirty)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest_sha256, data = load_bundle(args.bundle)
    result = summarize(data["documents.json"], data["rules.json"], data["consolidated_observation_drafts.json"],
                       load_review_profile_config())
    result.update(_code_state())
    result["manifest_sha256"] = manifest_sha256
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"observed_groups": result["observed_groups"], "pc_groups": result["pn_buckets"]["pc"]["groups"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
