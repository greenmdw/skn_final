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
        ids = {"rules": [], "docs": [], "observations": [], "aggregates": []}
        yield conn, ids
        with conn.transaction():
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


def _add_rule(conn, ids, version, *, aspect="fan_quietness", context="gaming_load", k=4):
    rule = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_aspect_rule "
        "(id,analysis_version,part_type,aspect_code,context_code,k,definition) "
        "VALUES (%s,%s,'gpu',%s,%s,%s,%s)",
        (rule, version, aspect, context, k, Jsonb({"positive": "quiet"})),
    )
    ids["rules"].append(rule)
    return rule


def _add_doc_obs(conn, ids, product_id, rule_id, direction):
    doc = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,'fixture-source',false,'evidence source sentence')", (doc, product_id),
    )
    ids["docs"].append(doc)
    observation = uuid4()
    conn.execute(
        "INSERT INTO evidence.review_aspect_observation "
        "(id,document_id,rule_id,observation_text,direction,evidence_sentences) "
        "VALUES (%s,%s,%s,'quiet fan',%s,%s)",
        (observation, doc, rule_id, direction, Jsonb(["evidence source sentence"])),
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
