import os
from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from src.services.review_aspect_score import build_review_requirement_profile, calculate_review_score, load_review_profile_config
from src.repo.review_aspect_repo import (
    ReviewAggregateNotReadyError,
    ReviewAspectRepositoryError,
    load_review_aspect_snapshot,
)


pytestmark = pytest.mark.db


@pytest.fixture
def review_db():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"review integration fixtures require a test database, got {conn.info.dbname!r}")
        ids = {"rules": [], "docs": [], "observations": [], "aggregates": []}
        yield conn, ids
        with conn.transaction():
            # Aggregate rebuild tests create IDs internally; remove every aggregate for our
            # unique rule IDs before deleting observations, even when it was not explicitly tracked.
            if ids["rules"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate_member m USING "
                    "evidence.review_aspect_aggregate a "
                    "WHERE m.aggregate_id=a.id AND a.rule_id=ANY(%s::uuid[])",
                    (ids["rules"],),
                )
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate WHERE rule_id=ANY(%s::uuid[])",
                    (ids["rules"],),
                )
            if ids["aggregates"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=ANY(%s::uuid[])",
                    (ids["aggregates"],),
                )
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate WHERE id=ANY(%s::uuid[])",
                    (ids["aggregates"],),
                )
            if ids["observations"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_observation WHERE id=ANY(%s::uuid[])",
                    (ids["observations"],),
                )
            if ids["docs"]:
                conn.execute(
                    "DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])",
                    (ids["docs"],),
                )
            if ids["rules"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_rule WHERE id=ANY(%s::uuid[])",
                    (ids["rules"],),
                )


def _add_rule(conn, ids, version, *, part_type="gpu", aspect="fan_quietness", context="gaming_load", k=4):
    rule = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_aspect_rule "
        "(id,analysis_version,part_type,aspect_code,context_code,k,definition) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (rule, version, part_type, aspect, context, k, Jsonb({"positive": "quiet"})),
    )
    ids["rules"].append(rule)
    return rule


def _add_doc_obs(conn, ids, product_id, rule_id, direction, *, body="evidence source sentence",
                 observation_text="quiet fan"):
    doc = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,'fixture-source',false,%s)", (doc, product_id, body),
    )
    ids["docs"].append(doc)
    observation = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_aspect_observation "
        "(id,document_id,rule_id,observation_text,direction,evidence_sentences) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (observation, doc, rule_id, observation_text, direction, Jsonb([body])),
    )
    ids["observations"].append(observation)
    return doc, observation


def _add_aggregate(conn, ids, aggregate_id, product_id, rule_id, p, n, mixed, k, members):
    conn.execute(
        "INSERT INTO evidence.review_aspect_aggregate "
        "(id,product_id,rule_id,p,n,mixed,k) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (aggregate_id, product_id, rule_id, p, n, mixed, k),
    )
    ids["aggregates"].append(aggregate_id)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO evidence.review_aspect_aggregate_member(aggregate_id,observation_id) VALUES (%s,%s)",
            [(aggregate_id, observation_id) for observation_id in members],
        )


def _gpu_products(conn):
    rows = conn.execute("SELECT product_id FROM catalog.gpu_spec ORDER BY product_id LIMIT 2").fetchall()
    assert len(rows) == 2
    return [row[0] for row in rows]


def test_batch_snapshot_separates_products_and_returns_member_evidence(review_db):
    conn, ids = review_db
    first_product, second_product = _gpu_products(conn)
    version = f"snapshot-{uuid4()}"
    rule = _add_rule(conn, ids, version)
    _, first_obs = _add_doc_obs(conn, ids, first_product, rule, "positive")
    _, second_obs = _add_doc_obs(conn, ids, second_product, rule, "negative")
    first_aggregate, second_aggregate = uuid4(), uuid4()
    _add_aggregate(conn, ids, first_aggregate, first_product, rule, 1, 0, 0, 4, [first_obs])
    _add_aggregate(conn, ids, second_aggregate, second_product, rule, 0, 1, 0, 4, [second_obs])

    snapshot = load_review_aspect_snapshot(conn, version, [str(first_product), str(second_product)])
    first = snapshot["products"][str(first_product)]["rules"][str(rule)]
    second = snapshot["products"][str(second_product)]["rules"][str(rule)]
    assert first["aggregate_id"] == str(first_aggregate) and float(first["q"]) == pytest.approx(0.6)
    assert second["aggregate_id"] == str(second_aggregate) and float(second["q"]) == pytest.approx(0.4)
    assert first["members"][0]["observation_id"] == str(first_obs)
    assert first["members"][0]["document_id"]
    assert first["members"][0]["source_code"] == "fixture-source"
    assert first["members"][0]["evidence_sentences"] == ["evidence source sentence"]
    assert snapshot["readiness"]["global_completeness_verified"] is False
    assert "without a manifest" in snapshot["readiness"]["scope"]


def test_partial_aggregate_for_requested_product_is_not_treated_as_no_reviews(review_db):
    conn, ids = review_db
    product, = _gpu_products(conn)[:1]
    version = f"partial-{uuid4()}"
    complete_rule = _add_rule(conn, ids, version)
    incomplete_rule = _add_rule(conn, ids, version, aspect="thermal_management")
    _, complete_obs = _add_doc_obs(conn, ids, product, complete_rule, "positive")
    _add_doc_obs(conn, ids, product, incomplete_rule, "positive")
    _add_aggregate(conn, ids, uuid4(), product, complete_rule, 1, 0, 0, 4, [complete_obs])

    with pytest.raises(ReviewAggregateNotReadyError, match="without aggregates"):
        load_review_aspect_snapshot(conn, version, [str(product)])


def test_repository_rejects_member_from_other_product(review_db):
    conn, ids = review_db
    product, other_product = _gpu_products(conn)
    version = f"bad-member-{uuid4()}"
    rule = _add_rule(conn, ids, version)
    _, wrong_product_obs = _add_doc_obs(conn, ids, other_product, rule, "positive")
    aggregate_id = uuid4()
    _add_aggregate(conn, ids, aggregate_id, product, rule, 1, 0, 0, 4, [wrong_product_obs])
    with pytest.raises(ReviewAspectRepositoryError, match="invalid observation evidence"):
        load_review_aspect_snapshot(conn, version, [str(product)])


def test_repository_rejects_member_from_another_rule(review_db):
    conn, ids = review_db
    product, = _gpu_products(conn)[:1]
    version = f"bad-rule-member-{uuid4()}"
    rule = _add_rule(conn, ids, version)
    other_rule = _add_rule(conn, ids, version, aspect="thermal_management")
    _, wrong_rule_obs = _add_doc_obs(conn, ids, product, other_rule, "positive")
    _add_aggregate(conn, ids, uuid4(), product, rule, 1, 0, 0, 4, [wrong_rule_obs])
    with pytest.raises(ReviewAspectRepositoryError, match="invalid observation evidence"):
        load_review_aspect_snapshot(conn, version, [str(product)])


def test_repository_rejects_stale_k_and_incomplete_member_coverage(review_db):
    conn, ids = review_db
    product, = _gpu_products(conn)[:1]
    version = f"stale-k-{uuid4()}"
    rule = _add_rule(conn, ids, version, k=4)
    _, observation = _add_doc_obs(conn, ids, product, rule, "positive")
    aggregate_id = uuid4()
    _add_aggregate(conn, ids, aggregate_id, product, rule, 1, 0, 0, 3, [observation])
    with pytest.raises(ReviewAspectRepositoryError, match="k differs"):
        load_review_aspect_snapshot(conn, version, [str(product)])

    conn.execute("UPDATE evidence.review_aspect_aggregate SET k=4 WHERE id=%s", (aggregate_id,))
    conn.execute("DELETE FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=%s", (aggregate_id,))
    with pytest.raises(ReviewAspectRepositoryError, match="member observation count mismatch"):
        load_review_aspect_snapshot(conn, version, [str(product)])


def test_db_snapshot_to_profile_score_uses_same_alpha_and_only_matching_product(review_db):
    conn, ids = review_db
    product, other_product = _gpu_products(conn)
    config = deepcopy(load_review_profile_config())
    version = f"joined-flow-{uuid4()}"
    config["analysis_version"] = version
    fan_rule = _add_rule(conn, ids, version)
    docs_and_obs = [_add_doc_obs(conn, ids, product, fan_rule, direction)
                    for direction in ["positive"] * 3 + ["negative"]]
    member_ids = [observation for _doc, observation in docs_and_obs]
    _add_aggregate(conn, ids, uuid4(), product, fan_rule, 3, 1, 0, 4, member_ids)

    snapshot = load_review_aspect_snapshot(conn, version, [str(product), str(other_product)])
    product_rules = snapshot["products"][str(product)]["rules"]
    profile = build_review_requirement_profile(
        "gpu", {"purpose": "game"}, registered_rules=list(product_rules.values()), config=config,
    )
    first = calculate_review_score(profile, snapshot, str(product))
    second = calculate_review_score(profile, snapshot, str(other_product))
    assert first.value == pytest.approx(0.525)
    assert second.value == pytest.approx(0.5)
    first_alpha = {item.aspect_code: item.alpha for item in first.contributions}
    second_alpha = {item.aspect_code: item.alpha for item in second.contributions}
    assert first_alpha == second_alpha
    fan = next(item for item in first.contributions if item.aspect_code == "fan_quietness")
    assert fan.q == pytest.approx(0.625)
    assert len(fan.members) == 4


def test_database_errors_propagate_without_becoming_empty_evidence():
    class BrokenCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            raise psycopg.OperationalError("injected database failure")

    class BrokenConnection:
        def cursor(self, **_kwargs):
            return BrokenCursor()

    with pytest.raises(psycopg.OperationalError, match="injected database failure"):
        load_review_aspect_snapshot(BrokenConnection(), "version", [str(uuid4())])


def test_catalog_pc_and_variant_paths_keep_real_product_ids(review_db):
    conn, _ids = review_db
    from src.repo.catalog_repo import load_candidates_by_slot_from_db, load_candidates_by_variant

    candidates = load_candidates_by_slot_from_db(conn)
    candidate = next(c for slot_candidates in candidates.values() for c in slot_candidates)
    assert candidate.product_id
    product_type = candidate.product_key.split(":", 1)[0]
    reloaded = load_candidates_by_variant(
        conn, [(product_type, candidate.variant_id)],
    )[candidate.variant_id]
    assert reloaded.product_id == candidate.product_id


def test_shared_ranker_persists_profile_for_run_and_passes_r_detail(review_db):
    from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
    from src.services.review_ranking import rank_with_review_aspects

    conn, ids = review_db
    product = _gpu_products(conn)[0]
    config = load_review_profile_config()
    version = config["analysis_version"]
    rule = _add_rule(conn, ids, version)
    observations = [_add_doc_obs(conn, ids, product, rule, direction)[1]
                    for direction in ["positive"] * 3 + ["negative"]]
    aggregate_id = uuid4()
    _add_aggregate(conn, ids, aggregate_id, product, rule, 3, 1, 0, 4, observations)

    domain_version = conn.execute(
        "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
        "WHERE d.code='computer' AND d.status='active' ORDER BY dv.version_no DESC LIMIT 1",
    ).fetchone()[0]
    conversation_id = conn.execute(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        (f"review-profile-{uuid4().hex}",),
    ).fetchone()[0]
    plan_id = conn.execute(
        "INSERT INTO planning.plan(conversation_id,name) VALUES (%s,'review profile test') RETURNING id",
        (conversation_id,),
    ).fetchone()[0]
    revision_id = conn.execute(
        "INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot) "
        "VALUES (%s,1,%s,'review profile test') RETURNING id", (plan_id, domain_version),
    ).fetchone()[0]
    run_id = conn.execute(
        "INSERT INTO engine.recommendation_run(revision_id,domain_version_id,input_snapshot,input_hash,"
        "draft_lock_version,engine_versions,status) VALUES (%s,%s,%s,'review-profile',0,%s,'running') RETURNING id",
        (revision_id, domain_version, Jsonb({}), Jsonb({"pipeline": "test"})),
    ).fetchone()[0]
    try:
        candidate = Candidate(product_key=str(product), product_id=str(product), slot="GPU", name="GPU", price=10,
                              specs={"perf_tier": 5})
        hf = HardFilterResult(slots={"GPU": [candidate]})
        spec = RequirementSpec(list_id=str(revision_id), category="computer", mode="build",
                               targets={"GPU": {}}, budget={"total": 100, "alloc": {"GPU": 1.0}})
        slots = Slots(category="computer", mode="build", objective_text="", values={"purpose": "game"})
        rank, profiles = rank_with_review_aspects(
            hf, spec, slots, lambda _message: None, conn=conn, run_id=run_id, catalog_source="db",
        )
        ranked = rank.slots["GPU"]["pool"][0]
        assert ranked["breakdown"]["리뷰"] == pytest.approx(0.525)
        fan = next(item for item in ranked["review_detail"]["contributions"]
                   if item["aspect_code"] == "fan_quietness")
        assert fan["members"][0]["observation_id"] in {
            str(observation) for observation in observations
        }
        saved = conn.execute(
            "SELECT profile_version,analysis_version,parts FROM engine.review_requirement_profile WHERE run_id=%s",
            (run_id,),
        ).fetchone()
        assert saved[0] == config["profile_version"] and saved[1] == version
        assert "gpu" in saved[2] and "gpu" in profiles
        versions = conn.execute(
            "SELECT engine_versions FROM engine.recommendation_run WHERE id=%s", (run_id,),
        ).fetchone()[0]
        assert versions["review_profile"] == config["profile_version"]
    finally:
        conn.execute("DELETE FROM engine.recommendation_run WHERE id=%s", (run_id,))
        conn.execute("DELETE FROM planning.plan_revision WHERE id=%s", (revision_id,))
        conn.execute("DELETE FROM planning.plan WHERE id=%s", (plan_id,))
        conn.execute("DELETE FROM identity.conversation WHERE id=%s", (conversation_id,))


@pytest.mark.integration
def test_raw_observations_rebuild_to_pc_score_and_stage5_trace(review_db, monkeypatch):
    """Isolated test-source documents traverse the real rebuild, repo, rank and explanation path."""
    from copy import deepcopy

    from src.dto import (
        BuildItem, BuildResult, Candidate, HardFilterResult, RequirementSpec, Slots,
        VerificationResult,
    )
    from src.engine import stage5_explain
    from src.repo.review_aspect_repo import load_review_aspect_snapshot
    from src.services import review_ranking
    from src.services.review_aspect_aggregate import rebuild_review_aspect_aggregates
    from src.services.review_ranking import rank_with_review_aspects
    from src.services.review_service import review_trace_steps

    conn, ids = review_db
    product, other_product = _gpu_products(conn)
    third_product_row = conn.execute(
        "SELECT product_id FROM catalog.gpu_spec WHERE product_id NOT IN (%s,%s) "
        "ORDER BY product_id LIMIT 1", (product, other_product),
    ).fetchone()
    assert third_product_row, "integration test needs a third seeded GPU for a no-observation baseline"
    neutral_product = third_product_row[0]
    config = deepcopy(load_review_profile_config())
    version = f"integration-{uuid4()}"
    config["analysis_version"] = version
    monkeypatch.setattr(review_ranking, "load_review_profile_config", lambda: config)

    selected_rule = _add_rule(conn, ids, version, aspect="fan_quietness")
    balanced_rule = _add_rule(conn, ids, version, aspect="coil_quietness")
    mixed_rule = _add_rule(conn, ids, version, aspect="thermal_management")
    _add_rule(conn, ids, version, aspect="gaming_performance")
    other_context_rule = _add_rule(
        conn, ids, version, aspect="fan_quietness", context="workload_unknown")
    other_version = f"other-{uuid4()}"
    other_version_rule = _add_rule(conn, ids, other_version, aspect="fan_quietness")

    body_texts = [
        "Fixture source: the GPU fan stayed quiet during a sustained gaming session.",
        "Fixture source: the GPU fan stayed quiet during a sustained gaming session.",
        "Fixture source: the GPU fan stayed quiet during a sustained gaming session.",
        "Fixture source: the GPU fan became loud during a sustained gaming session.",
    ]
    original_observations = []
    source_by_observation = {}
    for direction, body in zip(["positive"] * 3 + ["negative"], body_texts):
        document_id, observation = _add_doc_obs(
            conn, ids, product, selected_rule, direction, body=body, observation_text=body,
        )
        original_observations.append(observation)
        source_by_observation[observation] = (document_id, body)
    for direction in ("positive", "negative"):
        _doc, observation = _add_doc_obs(
            conn, ids, product, balanced_rule, direction,
            body=f"Fixture source: balanced coil report {direction}.",
            observation_text=f"Balanced coil report {direction}.",
        )
    _add_doc_obs(
        conn, ids, product, mixed_rule, "mixed",
        body="Fixture source: mixed thermal report.", observation_text="Mixed thermal report.",
    )
    _add_doc_obs(
        conn, ids, product, other_context_rule, "positive",
        body="Fixture source: low-load fan report, outside requested gaming context.",
        observation_text="Low-load fan report.",
    )
    _add_doc_obs(
        conn, ids, product, other_version_rule, "negative",
        body="Fixture source: different analysis version report.",
        observation_text="Different version report.",
    )
    # The same selected rule has a separate product group; it must not enter this product's Q.
    for _ in range(5):
        _add_doc_obs(
            conn, ids, other_product, selected_rule, "positive",
            body="Fixture source: another GPU positive report.",
            observation_text="Another GPU positive report.",
        )

    rebuild_report = rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert rebuild_report["positive"] == 10
    assert rebuild_report["negative"] == 2
    assert rebuild_report["mixed"] == 1
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id WHERE r.analysis_version=%s",
        (other_version,),
    ).fetchone()[0] == 0

    snapshot = load_review_aspect_snapshot(conn, version, [str(product)])
    product_rule = snapshot["products"][str(product)]["rules"][str(selected_rule)]
    assert (product_rule["p"], product_rule["n"], product_rule["mixed"], product_rule["k"]) == (3, 1, 0, 4)
    assert product_rule["q"] == pytest.approx(0.625)
    assert {member["observation_id"] for member in product_rule["members"]} == {
        str(value) for value in original_observations
    }
    assert all(member["document_id"] and member["evidence_sentences"] for member in product_rule["members"])

    candidate = Candidate(
        product_key=str(product), product_id=str(product), slot="GPU", name="Test GPU fixture",
        price=1000, specs={"perf_tier": 10},
    )
    neutral_candidate = Candidate(
        product_key=str(neutral_product), product_id=str(neutral_product), slot="GPU",
        name="Test GPU neutral baseline", price=1000, specs={"perf_tier": 10},
    )
    hard_filter = HardFilterResult(slots={"GPU": [candidate, neutral_candidate]})
    spec = RequirementSpec(
        list_id="review-integration", category="computer", mode="build", targets={"GPU": {}},
        budget={"total": 100_000, "alloc": {"GPU": 1.0}},
    )
    slots = Slots(category="computer", mode="build", objective_text="", values={
        "purpose": "game", "priority": "performance",
    })
    rank_before, profiles = rank_with_review_aspects(
        hard_filter, spec, slots, lambda _message: None, conn=conn, catalog_source="db",
    )
    ranked_before = next(item for item in rank_before.slots["GPU"]["pool"]
                         if item["product_key"] == str(product))
    ranked_neutral = next(item for item in rank_before.slots["GPU"]["pool"]
                          if item["product_key"] == str(neutral_product))
    detail_before = ranked_before["review_detail"]
    assert detail_before["value"] == pytest.approx(0.525)
    assert ranked_neutral["review_detail"]["value"] == pytest.approx(0.5)
    assert detail_before["profile"]["analysis_version"] == version
    assert {attribute["alpha"] for attribute in detail_before["profile"]["attributes"]} == {0.2}
    fan_contribution = next(item for item in detail_before["contributions"]
                            if item["aspect_code"] == "fan_quietness")
    assert fan_contribution["q"] == pytest.approx(0.625)
    assert fan_contribution["p"] == 3 and fan_contribution["n"] == 1
    assert {member["observation_id"] for member in fan_contribution["members"]} == {
        str(value) for value in original_observations
    }
    assert any(item["evidence_state"] == "balanced" for item in detail_before["contributions"])
    assert any(item["evidence_state"] == "mixed_only" for item in detail_before["contributions"])
    assert any(item["evidence_state"] == "no_observations" for item in detail_before["contributions"])

    from src.engine import stage3b_rank
    weights = rank_before.weights_used
    observed_round_inputs = []
    builtin_round = round

    def capture_round(value, digits=None):
        observed_round_inputs.append((value, digits))
        return builtin_round(value, digits) if digits is not None else builtin_round(value)

    monkeypatch.setattr(stage3b_rank, "round", capture_round, raising=False)
    isolated_actual, _ = rank_with_review_aspects(
        HardFilterResult(slots={"GPU": [candidate]}), spec, slots,
        lambda _message: None, conn=conn, catalog_source="db",
    )
    raw_with_review = observed_round_inputs[-1][0]
    isolated_actual_candidate = isolated_actual.slots["GPU"]["pool"][0]
    observed_round_inputs.clear()
    isolated_neutral, _ = rank_with_review_aspects(
        HardFilterResult(slots={"GPU": [neutral_candidate]}), spec, slots,
        lambda _message: None, conn=conn, catalog_source="db",
    )
    raw_without_review_change = observed_round_inputs[-1][0]
    isolated_neutral_candidate = isolated_neutral.slots["GPU"]["pool"][0]
    assert isolated_neutral_candidate["review_detail"]["value"] == pytest.approx(0.5)
    assert raw_with_review - raw_without_review_change == pytest.approx(
        weights["리뷰"] * (detail_before["value"] - 0.5), abs=1e-14,
    )
    assert isolated_actual_candidate["score"] == round(raw_with_review, 3)
    assert isolated_neutral_candidate["score"] == round(raw_without_review_change, 3)
    assert isolated_actual_candidate["score"] == ranked_before["score"]
    assert isolated_neutral_candidate["score"] == ranked_neutral["score"]

    monkeypatch.setattr(stage5_explain, "call_llm", lambda *_args, **_kwargs: {
        "headline": "Fixture recommendation", "summary": "Fixture source evidence was applied.",
        "items": [{"slot": "GPU", "reason": "Fixture review evidence."}], "caveats": [],
    })
    build = BuildResult(
        list_id="review-integration",
        items=[BuildItem(slot="GPU", product_key=str(product), name="Test GPU fixture",
                         price=1000, rank_from_3b=1)],
        totals={"price": 1000}, budget={"max": 100_000},
    )
    verification = VerificationResult(list_id="review-integration", category="computer", mode="set")
    explanation_before = stage5_explain.run(build, verification, lambda _message: None, rank=rank_before)
    fan_evidence = [item for item in explanation_before.items[0].evidence
                    if item["aspect_code"] == "fan_quietness"]
    assert {
        item["observation_id"]: (item["document_id"], item["text"], item["evidence_sentences"])
        for item in fan_evidence
    } == {
        str(observation): (str(document_id), body, [body])
        for observation, (document_id, body) in source_by_observation.items()
    }
    assert all(item["analysis_version"] == version for item in fan_evidence)
    persisted_source = {
        str(row[0]): (str(row[1]), row[2], row[3], row[4])
        for row in conn.execute(
            "SELECT o.id,d.id,d.body,o.observation_text,o.evidence_sentences "
            "FROM evidence.review_aspect_observation o "
            "JOIN evidence.review_document d ON d.id=o.document_id "
            "WHERE o.id=ANY(%s::uuid[])", (original_observations,),
        ).fetchall()
    }
    assert {
        item["observation_id"]: (item["document_id"], item["text"], item["evidence_sentences"])
        for item in fan_evidence
    } == {key: (value[0], value[2], value[3]) for key, value in persisted_source.items()}
    trace_before = review_trace_steps(
        explanation_before.review_line_by_slot,
        {item.slot: item.evidence for item in explanation_before.items},
    )
    assert any("R=0.525" in step["detail"] for step in trace_before)
    assert any(str(original_observations[0]) in step["detail"] for step in trace_before)

    mixed_body = "Fixture source: the GPU fan had mixed reports during sustained gaming."
    mixed_document_id, added_mixed = _add_doc_obs(
        conn, ids, product, selected_rule, "mixed", body=mixed_body, observation_text=mixed_body,
    )
    rebuild_review_aspect_aggregates(conn, version, apply=True)
    rank_after, _profiles_after = rank_with_review_aspects(
        hard_filter, spec, slots, lambda _message: None, conn=conn, catalog_source="db",
    )
    ranked_after = next(item for item in rank_after.slots["GPU"]["pool"]
                        if item["product_key"] == str(product))
    fan_after = next(item for item in ranked_after["review_detail"]["contributions"]
                     if item["aspect_code"] == "fan_quietness")
    assert (fan_after["p"], fan_after["n"], fan_after["mixed"], fan_after["q"]) == (
        3, 1, 1, pytest.approx(0.625),
    )
    assert ranked_after["review_detail"]["value"] == pytest.approx(detail_before["value"])
    assert ranked_after["score"] == ranked_before["score"]
    assert {member["observation_id"] for member in fan_after["members"]} == {
        *(str(value) for value in original_observations), str(added_mixed),
    }
    explanation_after = stage5_explain.run(build, verification, lambda _message: None, rank=rank_after)
    after_evidence = {item["observation_id"]: item for item in explanation_after.items[0].evidence}
    after_ids = set(after_evidence)
    assert str(added_mixed) in after_ids
    assert after_evidence[str(added_mixed)]["document_id"] == str(mixed_document_id)
    assert after_evidence[str(added_mixed)]["text"] == mixed_body
    assert after_evidence[str(added_mixed)]["evidence_sentences"] == [mixed_body]
    assert profiles["gpu"].analysis_version == version


@pytest.mark.integration
def test_peripheral_db_score_reaches_typed_payload_without_affecting_rank(review_db, monkeypatch):
    from copy import deepcopy

    from src.dto import Candidate
    from src.engine.peripheral_payload import peripheral_payload
    from src.engine.peripheral_select import run_peripherals
    from src.repo.catalog_repo import load_peripheral_candidates
    from src.schemas import PeripheralsOut
    from src.services import review_ranking
    from src.services.review_aspect_aggregate import rebuild_review_aspect_aggregates
    from src.services.review_aspect_score import load_review_profile_config
    from src.services.review_ranking import score_peripheral_candidates

    conn, ids = review_db
    candidates = load_peripheral_candidates(conn)["mouse"]
    candidates = sorted(candidates, key=lambda candidate: candidate.product_key)[:2]
    assert len(candidates) == 2 and candidates[0].product_id != candidates[1].product_id
    config = deepcopy(load_review_profile_config())
    version = f"peripheral-integration-{uuid4()}"
    config["analysis_version"] = version
    monkeypatch.setattr(review_ranking, "load_review_profile_config", lambda: config)

    rule = _add_rule(
        conn, ids, version, part_type="mouse", aspect="tracking_input", context="actual_use",
    )
    evidence_bodies = [
        "Fixture source: mouse tracking stayed precise in ordinary use.",
        "Fixture source: mouse tracking stayed precise in ordinary use.",
        "Fixture source: mouse tracking stayed precise in ordinary use.",
        "Fixture source: mouse tracking skipped during ordinary use.",
    ]
    observation_ids = []
    for direction, body in zip(["positive"] * 3 + ["negative"], evidence_bodies):
        _doc, observation = _add_doc_obs(
            conn, ids, candidates[0].product_id, rule, direction,
            body=body, observation_text=body,
        )
        observation_ids.append(observation)
    rebuild_review_aspect_aggregates(conn, version, apply=True)

    baseline_candidates = [candidate.model_copy(deep=True, update={"review_detail": None})
                           for candidate in candidates]
    values = {"peripherals": ["mouse"], "purpose": "game"}
    baseline = run_peripherals(values, {"mouse": baseline_candidates}, lambda _message: None)
    profiles = score_peripheral_candidates(
        conn, {"mouse": candidates}, values, catalog_source="db",
    )
    actual = run_peripherals(
        values, {"mouse": candidates}, lambda _message: None, require_review_details=True,
    )
    candidate_details = {candidate.product_id: candidate.review_detail for candidate in candidates}
    assert candidate_details[str(candidates[0].product_id)].value == pytest.approx(0.525)
    assert candidate_details[str(candidates[1].product_id)].value == pytest.approx(0.5)
    assert {attribute.alpha for attribute in candidate_details[str(candidates[0].product_id)].profile.attributes} == {0.2}
    assert {attribute.alpha for attribute in candidate_details[str(candidates[1].product_id)].profile.attributes} == {0.2}
    tracking_contribution = next(
        contribution for contribution in candidate_details[str(candidates[0].product_id)].contributions
        if contribution.aspect_code == "tracking_input"
    )
    assert tracking_contribution.q == pytest.approx(0.625)
    assert {member.observation_id for member in tracking_contribution.members} == {
        str(value) for value in observation_ids
    }
    baseline_picks = {pick.candidate.product_key: pick for pick in baseline.picks}
    actual_picks = {pick.candidate.product_key: pick for pick in actual.picks}
    assert baseline_picks.keys() == actual_picks.keys()
    for key in actual_picks:
        assert actual_picks[key].score == baseline_picks[key].score
        assert actual_picks[key].candidate.rank == baseline_picks[key].candidate.rank
        assert actual_picks[key].candidate.breakdown["리뷰"] == actual_picks[key].candidate.review_detail.value
    assert actual.counts == baseline.counts
    assert profiles["mouse"].analysis_version == version

    payload = peripheral_payload(actual)
    typed = PeripheralsOut.model_validate(payload).model_dump(mode="json")
    review_members = []
    for item in typed["items"]:
        assert item["review_weight"] == 0
        review_members.extend(member for contribution in item["review"]["contributions"]
                              for member in contribution["members"])
        for alternative in item["alternatives"]:
            assert alternative["review_weight"] == 0
            if alternative["review"]:
                review_members.extend(member for contribution in alternative["review"]["contributions"]
                                      for member in contribution["members"])
    assert {member["observation_id"] for member in review_members} == {
        str(value) for value in observation_ids
    }
