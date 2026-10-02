import json
import pytest
from tests.test_review_preparation import prepared
from src.services.review_preparation import preparation_plan
from src.services.review_source_quarantine import compensate_source_conflicts


@pytest.mark.db
def test_owned_unprocessed_compensation_preserves_source_and_blocks_reload(prepared):
    conn, manifest, rules, ledger = prepared
    preparation_plan(conn, manifest, rules, ledger, apply=True)
    row = manifest['rows'][0]
    decision = [{'document_id': row['document_id'], 'decision': 'confirmed_source_target_conflict', 'reason': 'Original body explicitly identifies another used model.'}]
    original = (ledger / (row['document_id'] + '.json')).read_bytes()
    assert compensate_source_conflicts(conn, manifest, decision, ledger)['remove_owned_unprocessed'] == [row['document_id']]
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0] == 1
    compensate_source_conflicts(conn, manifest, decision, ledger, apply=True)
    assert (ledger / (row['document_id'] + '.json')).read_bytes() == original
    assert compensate_source_conflicts(conn, manifest, decision, ledger, apply=True)['already_absent'] == [row['document_id']]
    assert preparation_plan(conn, manifest, rules, ledger)['conflicts'][0]['reason'] == 'source_identity_quarantined_never_reload'
    with pytest.raises(ValueError, match='conflicts'):
        preparation_plan(conn, manifest, rules, ledger, apply=True)


@pytest.mark.db
def test_compensation_rejects_unowned_and_processed_document(prepared):
    conn, manifest, rules, ledger = prepared
    preparation_plan(conn, manifest, rules, ledger, apply=True)
    row = manifest['rows'][0]
    decision = [{'document_id': row['document_id'], 'decision': 'confirmed_source_target_conflict', 'reason': 'Explicit other target.'}]
    conn.execute('INSERT INTO evidence.review_aspect_observation(document_id,rule_id,observation_text,direction,evidence_sentences) VALUES (%s,%s,%s,%s,%s::jsonb)', (row['document_id'], rules[0]['id'], 'Quiet fan', 'positive', json.dumps([row['document']['body']])))
    with pytest.raises(ValueError, match='Processed observations'):
        compensate_source_conflicts(conn, manifest, decision, ledger, apply=True)
    assert not (ledger / (row['document_id'] + '.excluded.json')).exists()
    conn.execute('DELETE FROM evidence.review_aspect_observation WHERE document_id=%s', (row['document_id'],))
    (ledger / (row['document_id'] + '.json')).unlink()
    with pytest.raises(ValueError, match='provenance'):
        compensate_source_conflicts(conn, manifest, decision, ledger, apply=True)
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0] == 1
