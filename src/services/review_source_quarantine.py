"""Compensate only this run's unprocessed inserts with confirmed source conflicts.

This is separate from the insert-only importer. Full source/provenance and frozen
worker inputs remain immutable; a durable tombstone prevents accidental reload.
Legacy documents, changed documents and any processed document are rejected.
"""
import json
from pathlib import Path
from psycopg.rows import dict_row
from src.services.review_preparation import digest, encoded, validate_manifest_sources


def compensate_source_conflicts(conn, manifest, decisions, provenance_root, *, apply=False):
    validate_manifest_sources(manifest)
    if not manifest.get('database_import_allowed'):
        raise ValueError('Not an authorized application run')
    rows = {r['document_id']: r for r in manifest['rows'] if r['status'] == 'matched'}
    ids = [d['document_id'] for d in decisions]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate quarantine document')
    report = {'dry_run': not apply, 'remove_owned_unprocessed': [], 'already_absent': [], 'preserved_originals': True}
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        if apply:
            cur.execute('LOCK TABLE evidence.review_document, evidence.review_aspect_observation, evidence.review_embedding IN SHARE ROW EXCLUSIVE MODE')
        actions = []
        for decision in decisions:
            doc_id = decision['document_id']
            row = rows.get(doc_id)
            if not row or decision.get('decision') != 'confirmed_source_target_conflict' or not decision.get('reason'):
                raise ValueError('Not a confirmed owned source conflict')
            ledger = Path(provenance_root) / (doc_id + '.json')
            expected = {'source_identity': row['source_identity'], 'record': row['record'], 'document': row['document'], 'part_type': row['part_type']}
            if not ledger.exists() or json.loads(ledger.read_text()) != expected:
                raise ValueError('Missing or changed run-owned provenance')
            tombstone = Path(provenance_root) / (doc_id + '.excluded.json')
            payload = {'document_id': doc_id, 'source_identity': row['source_identity'], 'source_record_sha256': row['record_sha256'], 'document_sha256': digest(row['document']), 'decision': decision}
            if tombstone.exists() and json.loads(tombstone.read_text()) != payload:
                raise ValueError('Conflicting exclusion tombstone')
            cur.execute('SELECT id::text,product_id::text,source_code,is_synthetic,body,posted_at FROM evidence.review_document WHERE id=%s', (doc_id,))
            existing = cur.fetchone()
            if existing and existing != row['document']:
                raise ValueError('Changed document cannot be compensated')
            cur.execute('SELECT count(*) AS n FROM evidence.review_aspect_observation WHERE document_id=%s', (doc_id,))
            if cur.fetchone()['n']:
                raise ValueError('Processed observations require coordinated rebuild')
            cur.execute('SELECT count(*) AS n FROM evidence.review_embedding WHERE review_id=%s', (doc_id,))
            if cur.fetchone()['n']:
                raise ValueError('Processed embedding requires coordinated rebuild')
            cur.execute('SELECT count(*) AS n FROM evidence.review_aspect_aggregate WHERE product_id=%s', (row['product_id'],))
            if cur.fetchone()['n']:
                raise ValueError('Existing product aggregate requires coordinated rebuild')
            actions.append((doc_id, tombstone, payload, bool(existing)))
            report['remove_owned_unprocessed' if existing else 'already_absent'].append(doc_id)
        if apply:
            for doc_id, tombstone, payload, existing in actions:
                if not tombstone.exists():
                    with tombstone.open('x') as f:
                        f.write(encoded(payload) + '\n')
                if existing:
                    cur.execute('DELETE FROM evidence.review_document WHERE id=%s', (doc_id,))
                    assert cur.rowcount == 1
                cur.execute('SELECT count(*) AS n FROM evidence.review_document WHERE id=%s', (doc_id,))
                assert cur.fetchone()['n'] == 0
    return report
