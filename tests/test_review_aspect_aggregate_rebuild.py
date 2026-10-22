import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from src.services import review_aspect_aggregate as aggregate_service
from src.services.review_aspect_aggregate import rebuild_review_aspect_aggregates


pytestmark = pytest.mark.db


@pytest.fixture
def data():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        created = {"conn": conn, "rules": [], "documents": [], "observations": [], "aggregates": []}
        yield created
        with conn.transaction():
            if created["rules"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate_member m USING "
                    "evidence.review_aspect_aggregate a "
                    "WHERE m.aggregate_id=a.id AND a.rule_id=ANY(%s::uuid[])",
                    (created["rules"],),
                )
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate WHERE rule_id=ANY(%s::uuid[])",
                    (created["rules"],),
                )
            if created["aggregates"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=ANY(%s::uuid[])",
                    (created["aggregates"],),
                )
                conn.execute(
                    "DELETE FROM evidence.review_aspect_aggregate WHERE id=ANY(%s::uuid[])",
                    (created["aggregates"],),
                )
            if created["observations"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_observation WHERE id=ANY(%s::uuid[])",
                    (created["observations"],),
                )
            if created["documents"]:
                conn.execute(
                    "DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])",
                    (created["documents"],),
                )
            if created["rules"]:
                conn.execute(
                    "DELETE FROM evidence.review_aspect_rule WHERE id=ANY(%s::uuid[])",
                    (created["rules"],),
                )


def _gpu_products(data):
    rows = data["conn"].execute(
        "SELECT product_id FROM catalog.gpu_spec ORDER BY product_id LIMIT 2"
    ).fetchall()
    assert len(rows) == 2, "isolated DB setup must seed at least two GPUs"
    return [row[0] for row in rows]


def _add_rule(data, version, *, part="gpu", aspect="fan_quietness", k=4):
    rule_id = uuid4()
    data["conn"].execute(
        "INSERT INTO evidence.review_aspect_rule "
        "(id,analysis_version,part_type,aspect_code,context_code,k,definition) "
        "VALUES (%s,%s,%s,%s,'gaming_load',%s,%s)",
        (rule_id, version, part, aspect, k, Jsonb({"positive": "quiet"})),
    )
    data["rules"].append(rule_id)
    return rule_id


def _add_document(data, product_id, *, synthetic=False):
    document_id = uuid4()
    data["conn"].execute(
        "INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) "
        "VALUES (%s,%s,'test-fixture',%s,'fixture review body')",
        (document_id, product_id, synthetic),
    )
    data["documents"].append(document_id)
    return document_id


def _add_observation(data, document_id, rule_id, direction):
    observation_id = uuid4()
    data["conn"].execute(
        "INSERT INTO evidence.review_aspect_observation "
        "(id,document_id,rule_id,observation_text,direction,evidence_sentences) "
        "VALUES (%s,%s,%s,'fixture observation',%s,%s)",
        (observation_id, document_id, rule_id, direction, Jsonb(["fixture review body"])),
    )
    data["observations"].append(observation_id)
    return observation_id


def test_apply_rebuilds_counts_members_and_only_selected_version(data):
    conn = data["conn"]
    product, stale_product = _gpu_products(data)
    version, other_version = f"test-{uuid4()}", f"other-{uuid4()}"
    rule = _add_rule(data, version)
    second_rule = _add_rule(data, version, aspect="thermal_management")
    other_rule = _add_rule(data, other_version)
    docs = [_add_document(data, product) for _ in range(3)]
    positive = _add_observation(data, docs[0], rule, "positive")
    negative = _add_observation(data, docs[1], rule, "negative")
    mixed = _add_observation(data, docs[2], rule, "mixed")
    _add_observation(data, docs[2], second_rule, "mixed")
    other_obs = _add_observation(data, docs[0], other_rule, "positive")

    target_id, second_id, stale_id, other_id = [uuid4() for _ in range(4)]
    data["aggregates"].extend([target_id, second_id, stale_id, other_id])
    conn.execute(
        "INSERT INTO evidence.review_aspect_aggregate "
        "(id,product_id,rule_id,p,n,mixed,k) VALUES "
        "(%s,%s,%s,8,0,0,4),(%s,%s,%s,0,0,0,4),(%s,%s,%s,0,0,0,4),"
        "(%s,%s,%s,0,0,0,4)",
        (target_id, product, rule, second_id, product, second_rule,
         stale_id, stale_product, rule, other_id, product, other_rule),
    )
    conn.execute(
        "INSERT INTO evidence.review_aspect_aggregate_member(aggregate_id,observation_id) "
        "VALUES (%s,%s),(%s,%s)", (target_id, positive, other_id, other_obs),
    )

    report = rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert report == {
        "analysis_version": version, "rules": 2, "observations": 4, "groups": 2,
        "positive": 1, "negative": 1, "mixed": 2, "existing_aggregates": 3,
        "would_insert": 0, "would_update": 2, "unchanged": 0, "would_delete": 1,
    }
    rows = conn.execute(
        "SELECT id, product_id, rule_id, p, n, mixed, q FROM evidence.review_aspect_aggregate "
        "WHERE rule_id = ANY(%s::uuid[]) ORDER BY rule_id", ([rule, second_rule],),
    ).fetchall()
    by_rule = {row[2]: row for row in rows}
    assert by_rule[rule][:6] == (target_id, product, rule, 1, 1, 1)
    assert by_rule[rule][6] == pytest.approx(0.5)
    assert by_rule[second_rule][:6] == (second_id, product, second_rule, 0, 0, 1)
    assert by_rule[second_rule][6] == pytest.approx(0.5)
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate WHERE id=%s", (stale_id,),
    ).fetchone()[0] == 0
    assert set(conn.execute(
        "SELECT observation_id FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=%s",
        (target_id,),
    ).fetchall()) == {(positive,), (negative,), (mixed,)}
    assert conn.execute(
        "SELECT p,n,mixed,k FROM evidence.review_aspect_aggregate WHERE id=%s", (other_id,),
    ).fetchone() == (0, 0, 0, 4)
    assert conn.execute(
        "SELECT observation_id FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=%s",
        (other_id,),
    ).fetchall() == [(other_obs,)]

    repeated = rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert repeated["unchanged"] == 2
    assert repeated["would_insert"] == repeated["would_update"] == repeated["would_delete"] == 0
    assert conn.execute(
        "SELECT id FROM evidence.review_aspect_aggregate WHERE product_id=%s AND rule_id=%s",
        (product, rule),
    ).fetchone() == (target_id,)


def test_q_uses_registered_k_and_mixed_addition_only_changes_membership(data):
    conn = data["conn"]
    product, = _gpu_products(data)[:1]
    version = f"q-formula-{uuid4()}"
    rule = _add_rule(data, version, k=4)
    docs = [_add_document(data, product) for _ in range(5)]
    for doc in docs[:3]:
        _add_observation(data, doc, rule, "positive")
    _add_observation(data, docs[3], rule, "negative")

    rebuild_review_aspect_aggregates(conn, version, apply=True)
    first = conn.execute(
        "SELECT a.id,a.p,a.n,a.mixed,a.k,a.q,"
        "(a.p::numeric+a.k*0.5)/(a.p::numeric+a.n::numeric+a.k) "
        "FROM evidence.review_aspect_aggregate a WHERE a.rule_id=%s", (rule,),
    ).fetchone()
    assert first[1:5] == (3, 1, 0, 4)
    assert first[5] == first[6]
    assert first[5] == pytest.approx(0.625)

    conn.execute("UPDATE evidence.review_aspect_rule SET k=2 WHERE id=%s", (rule,))
    rebuild_review_aspect_aggregates(conn, version, apply=True)
    changed_k = conn.execute(
        "SELECT k,q,(p::numeric+k*0.5)/(p::numeric+n::numeric+k) "
        "FROM evidence.review_aspect_aggregate WHERE rule_id=%s", (rule,),
    ).fetchone()
    assert changed_k[0] == 2
    assert changed_k[1] == changed_k[2]
    assert float(changed_k[1]) == pytest.approx(2 / 3)

    mixed_id = _add_observation(data, docs[4], rule, "mixed")
    rebuild_review_aspect_aggregates(conn, version, apply=True)
    second = conn.execute(
        "SELECT id,p,n,mixed,k,q FROM evidence.review_aspect_aggregate WHERE rule_id=%s", (rule,),
    ).fetchone()
    assert second == (first[0], 3, 1, 1, 2, changed_k[1])
    assert conn.execute(
        "SELECT observation_id FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=%s "
        "AND observation_id=%s", (first[0], mixed_id),
    ).fetchone() == (mixed_id,)


def test_dry_run_is_read_only_and_invalid_synthetic_or_type_mismatch_fails(data):
    conn = data["conn"]
    product, = _gpu_products(data)[:1]
    version = f"dry-{uuid4()}"
    rule = _add_rule(data, version)
    synthetic_doc = _add_document(data, product, synthetic=True)
    _add_observation(data, synthetic_doc, rule, "positive")
    with pytest.raises(ValueError, match="synthetic"):
        rebuild_review_aspect_aggregates(conn, version)

    conn.execute("DELETE FROM evidence.review_aspect_observation WHERE document_id=%s", (synthetic_doc,))
    data["observations"].clear()
    conn.execute("UPDATE evidence.review_document SET is_synthetic=false WHERE id=%s", (synthetic_doc,))
    _add_observation(data, synthetic_doc, rule, "positive")
    report = rebuild_review_aspect_aggregates(conn, version)
    assert report["groups"] == report["would_insert"] == 1
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id WHERE r.analysis_version=%s",
        (version,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate_member m "
        "JOIN evidence.review_aspect_aggregate a ON a.id=m.aggregate_id "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id WHERE r.analysis_version=%s",
        (version,),
    ).fetchone()[0] == 0

    mismatch_version = f"type-mismatch-{uuid4()}"
    cpu_rule = _add_rule(data, mismatch_version, part="cpu")
    cpu_mismatch_doc = _add_document(data, product)
    _add_observation(data, cpu_mismatch_doc, cpu_rule, "positive")
    with pytest.raises(ValueError, match="part_type mismatch"):
        rebuild_review_aspect_aggregates(conn, mismatch_version, apply=True)
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id WHERE r.analysis_version=%s",
        (mismatch_version,),
    ).fetchone()[0] == 0


def test_apply_verification_failure_rolls_back_all_writes(data, monkeypatch):
    conn = data["conn"]
    product, = _gpu_products(data)[:1]
    version = f"rollback-{uuid4()}"
    rule = _add_rule(data, version)
    doc = _add_document(data, product)
    _add_observation(data, doc, rule, "positive")

    def fail_verification(*_args):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(aggregate_service, "_verify", fail_verification)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert conn.execute(
        "SELECT count(*) FROM evidence.review_aspect_aggregate a "
        "JOIN evidence.review_aspect_rule r ON r.id=a.rule_id WHERE r.analysis_version=%s",
        (version,),
    ).fetchone()[0] == 0


def test_rebuild_requires_idle_connection(data):
    conn = data["conn"]
    version = f"idle-{uuid4()}"
    _add_rule(data, version)
    with conn.transaction():
        with pytest.raises(ValueError, match="idle connection"):
            rebuild_review_aspect_aggregates(conn, version)


def test_apply_locks_out_concurrent_observation_writer(data, monkeypatch):
    conn = data["conn"]
    product, = _gpu_products(data)[:1]
    version = f"lock-{uuid4()}"
    rule = _add_rule(data, version)
    _add_observation(data, _add_document(data, product), rule, "positive")
    writer_doc = _add_document(data, product)
    lock_acquired = Event()
    release_rebuild = Event()
    original_apply = aggregate_service._apply

    # The event is set once the rebuild has acquired all source-table locks and reached its write phase.
    def gated_apply(cur, selected_version, rules, groups):
        lock_acquired.set()
        assert release_rebuild.wait(5)
        return original_apply(cur, selected_version, rules, groups)

    monkeypatch.setattr(aggregate_service, "_apply", gated_apply)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(rebuild_review_aspect_aggregates, conn, version, apply=True)
            assert lock_acquired.wait(5)
            with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as writer:
                writer.execute("SET lock_timeout = '150ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable) as exc:
                    writer.execute(
                        "INSERT INTO evidence.review_aspect_observation "
                        "(document_id,rule_id,observation_text,direction,evidence_sentences) "
                        "VALUES (%s,%s,'concurrent','positive',%s)",
                        (writer_doc, rule, Jsonb(["fixture review body"])),
                    )
                assert exc.value.sqlstate == "55P03"
            release_rebuild.set()
            future.result(timeout=10)
    finally:
        release_rebuild.set()


def test_post_commit_audit_failure_reports_committed_state(data, monkeypatch):
    conn = data['conn']
    product = _gpu_products(data)[0]
    version = f'post-commit-{uuid4()}'
    rule = _add_rule(data, version)
    _add_observation(data, _add_document(data, product), rule, 'positive')
    original_verify = aggregate_service._verify
    audits = 0

    def fail_second_audit(*args):
        nonlocal audits
        audits += 1
        if audits == 2:
            raise RuntimeError('injected post-commit failure')
        return original_verify(*args)

    monkeypatch.setattr(aggregate_service, '_verify', fail_second_audit)
    with pytest.raises(RuntimeError, match='committed, but the post-commit audit failed'):
        rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert conn.execute(
        'SELECT p,n,mixed FROM evidence.review_aspect_aggregate WHERE rule_id=%s',
        (rule,),
    ).fetchone() == (1, 0, 0)
    assert conn.execute(
        'SELECT count(*) FROM evidence.review_aspect_aggregate_member m '
        'JOIN evidence.review_aspect_aggregate a ON a.id=m.aggregate_id WHERE a.rule_id=%s',
        (rule,),
    ).fetchone()[0] == 1


def test_rebuild_removes_group_after_last_observation_is_removed(data):
    conn = data['conn']
    product = _gpu_products(data)[0]
    version = f'deleted-observation-{uuid4()}'
    rule = _add_rule(data, version)
    obs = _add_observation(data, _add_document(data, product), rule, 'positive')
    rebuild_review_aspect_aggregates(conn, version, apply=True)
    # Explicit maintenance edit: the FK requires unlinking the old member before deletion.
    with conn.transaction():
        conn.execute('DELETE FROM evidence.review_aspect_aggregate_member WHERE observation_id=%s', (obs,))
        conn.execute('DELETE FROM evidence.review_aspect_observation WHERE id=%s', (obs,))
    report = rebuild_review_aspect_aggregates(conn, version, apply=True)
    assert report['observations'] == report['groups'] == 0
    assert report['would_delete'] == 1
    assert conn.execute(
        'SELECT count(*) FROM evidence.review_aspect_aggregate WHERE rule_id=%s', (rule,),
    ).fetchone()[0] == 0


def test_dry_run_enforces_read_only_transaction(data, monkeypatch):
    conn = data['conn']
    version = f'read-only-{uuid4()}'
    _add_rule(data, version)
    original_read = aggregate_service._read_source

    def attempt_write(cur, selected_version):
        cur.execute('DELETE FROM evidence.review_aspect_aggregate WHERE false')
        return original_read(cur, selected_version)

    monkeypatch.setattr(aggregate_service, '_read_source', attempt_write)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        rebuild_review_aspect_aggregates(conn, version)


def test_unknown_version_is_rejected_without_writes(data):
    with pytest.raises(ValueError, match='no registered rules'):
        rebuild_review_aspect_aggregates(data['conn'], f'unknown-{uuid4()}', apply=True)
