"""Import canonical review observations from the private setup bundle.

Exact reimports preserve existing IDs. Changed source observations are rejected when
they could make existing aggregates stale; setup_all rebuilds aggregates afterward.
"""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.review_observation_import import read_json

NAMESPACE = UUID('17697f07-d9f4-45b4-85d4-9b2f1624a94d')


def apply_all(conn, root, *, apply=False):
    bundle_manifest = read_json(root / 'bundle_manifest.json')
    if (bundle_manifest.get('bundle_version') != 'review-seed-v1'
            or bundle_manifest.get('database_import_allowed') is not True):
        raise ValueError('Unsupported review seed bundle version')
    names = ['documents.json', 'rules.json', 'canonical_results.json',
             'consolidated_observation_drafts.json']
    hashes = bundle_manifest.get('sha256', {})
    for name in names:
        expected = hashes.get(name)
        if not expected:
            raise ValueError(f'Missing review seed checksum: {name}')
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Changed review seed artifact: {name}')
    if bundle_manifest.get('analysis_version') != 'review-aspect-v6-prod-20261002':
        raise ValueError('Review seed analysis version does not match setup baseline')
    canonical = read_json(root / 'canonical_results.json')
    drafts = read_json(root / 'consolidated_observation_drafts.json')
    seed_documents = read_json(root / 'documents.json')
    seed_by_id = {r['document_id']: r for r in seed_documents}
    if len(seed_by_id) != len(seed_documents) or len(seed_documents) != bundle_manifest.get('documents'):
        raise ValueError('Review seed document count or identity mismatch')
    if len(drafts) != bundle_manifest.get('observations'):
        raise ValueError('Review seed observation count mismatch')
    excluded = set(bundle_manifest.get('excluded_document_ids', []))
    canonical_ids = {row['review']['document_id'] for row in canonical}
    draft_ids = {row['document_id'] for row in drafts}
    if excluded & (set(seed_by_id) | canonical_ids | draft_ids):
        raise ValueError('Quarantined source identity is present in observation bundle')
    for row in canonical:
        review = row['review']
        source = seed_by_id.get(review['document_id'])
        if (source is None or review['body'] != source['body']
                or review['part_type'] != source['part_type']
                or review['is_synthetic'] is not False):
            raise ValueError('Canonical review differs from seeded document: '+review['document_id'])
    with conn.cursor() as cur:
        registered_documents = {
            row[0]: (row[1], row[2])
            for row in cur.execute('SELECT id::text,product_id::text,body FROM evidence.review_document')
        }
    observations = []
    for row in canonical:
        review = row['review']
        registered = registered_documents.get(review['document_id'])
        if registered is None or registered[1] != review['body']:
            raise ValueError('Source document mismatch: '+review['document_id'])
        # Catalog product UUIDs are database-local; document identity and exact body
        # remain stable, while the bundle maps the product through exact brand/model.
        review = {**review, 'product_id': registered[0]}
        observations.extend((review, obs) for obs in row['result']['observations'])
    reconstructed = []
    rules = {r['id']: r for r in read_json(root / 'rules.json')}
    seen = set()
    for review, obs in observations:
        key = (review['document_id'], obs['rule_id'])
        if key in seen:
            raise ValueError('Duplicate document/rule')
        seen.add(key)
        rule = rules[obs['rule_id']]
        if rule['part_type'] != review['part_type'] or obs['direction'] not in {'positive','negative','mixed'}:
            raise ValueError('Rule/direction mismatch')
        if not obs['observation_text'].strip() or not obs['evidence_sentences'] or not all(isinstance(e,str) and e.strip() and e in review['body'] for e in obs['evidence_sentences']):
            raise ValueError('Invalid evidence')
        reconstructed.append((review['document_id'],review['product_id'],rule['aspect_code'],rule['context_code'],obs['direction'],obs['observation_text'],obs['evidence_sentences']))
    assert reconstructed == [(d['document_id'],registered_documents[d['document_id']][0],d['aspect_code'],d['context_code'],d['direction'],d['observation_text'],d['evidence_sentences']) for d in drafts]
    with conn.transaction():
        conn.execute('LOCK TABLE evidence.review_document, evidence.review_aspect_rule, evidence.review_aspect_observation, evidence.review_aspect_aggregate, evidence.review_aspect_aggregate_member IN SHARE ROW EXCLUSIVE MODE')
        has_aggregates = bool(
            conn.execute('SELECT EXISTS (SELECT 1 FROM evidence.review_aspect_aggregate) '
                         'OR EXISTS (SELECT 1 FROM evidence.review_aspect_aggregate_member)').fetchone()[0]
        )
        documents = {r[0]:r[1:] for r in conn.execute('SELECT id::text,product_id::text,body FROM evidence.review_document')}
        registered = {r[0]:r[1:] for r in conn.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,k,definition FROM evidence.review_aspect_rule')}
        old = {(r[1],r[2]):r for r in conn.execute('SELECT id::text,document_id::text,rule_id::text,observation_text,direction,evidence_sentences FROM evidence.review_aspect_observation')}
        expected_keys = {(r['document_id'], o['rule_id']) for r, o in observations}
        bundle_rule_ids = set(rules)
        unexpected = {
            key for key in old
            if key[1] in bundle_rule_ids and key not in expected_keys
        }
        if unexpected:
            raise ValueError('Existing observations differ from the immutable review bundle')
        for review, obs in observations:
            if documents.get(review['document_id']) != (review['product_id'],review['body']):
                raise ValueError('Source document mismatch')
            rule = rules[obs['rule_id']]
            if registered.get(obs['rule_id']) != tuple(rule[k] for k in ['analysis_version','part_type','aspect_code','context_code','k','definition']):
                raise ValueError('Registered rule mismatch')
            existing = old.get((review['document_id'],obs['rule_id']))
            if existing and existing[3:] != (obs['observation_text'],obs['direction'],obs['evidence_sentences']):
                raise ValueError('Existing observation differs')
        added = sum((r['document_id'],o['rule_id']) not in old for r,o in observations)
        exact_reimport = all(
            (r['document_id'], o['rule_id']) in old
            and old[(r['document_id'], o['rule_id'])][3:] ==
                (o['observation_text'], o['direction'], o['evidence_sentences'])
            for r, o in observations
        )
        if has_aggregates and not exact_reimport:
            raise ValueError('Existing aggregates require coordinated observation rebuild')
        if apply:
            with conn.cursor() as cur:
                cur.executemany('INSERT INTO evidence.review_aspect_observation (id,document_id,rule_id,observation_text,direction,evidence_sentences) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (document_id,rule_id) DO NOTHING', [(str(uuid5(NAMESPACE,r['document_id']+':'+o['rule_id'])),r['document_id'],o['rule_id'],o['observation_text'],o['direction'],Jsonb(o['evidence_sentences'])) for r,o in observations])
            actual = {(r[0],r[1]):r[2:] for r in conn.execute('SELECT document_id::text,rule_id::text,observation_text,direction,evidence_sentences FROM evidence.review_aspect_observation')}
            assert all(actual[(r['document_id'],o['rule_id'])] == (o['observation_text'],o['direction'],o['evidence_sentences']) for r,o in observations)
            assert all(conn.execute('SELECT id::text FROM evidence.review_aspect_observation WHERE document_id=%s AND rule_id=%s',key).fetchone()[0] == val[0] for key,val in old.items())
        return {'canonical_observations':len(observations),'existing_preserved':len(old),'inserted':added if apply else 0,'would_insert':added if not apply else 0,'applied':apply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('data/review_seed'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    load_dotenv('.env')
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        result=apply_all(conn,args.root,apply=args.apply)
    print(json.dumps(result))


if __name__=='__main__':
    main()
