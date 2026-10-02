"""User-authorized integration run: import all canonical drafts as observations.

No semantic approval gate: intended for verifying recommendation integration.
Preserves existing observation IDs and rejects changed/unknown source data.
Optionally removes the superseded draft archive after verifying identical content.
"""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
from src.services.review_observation_import import read_json

NAMESPACE = UUID('17697f07-d9f4-45b4-85d4-9b2f1624a94d')


def apply_all(conn, root, *, apply=False):
    canonical = read_json(root / 'canonical_results.json')
    drafts = read_json(root / 'consolidated_observation_drafts.json')
    observations = [(row['review'], obs) for row in canonical for obs in row['result']['observations']]
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
    assert reconstructed == [(d['document_id'],d['product_id'],d['aspect_code'],d['context_code'],d['direction'],d['observation_text'],d['evidence_sentences']) for d in drafts]
    with conn.transaction():
        conn.execute('LOCK TABLE evidence.review_document, evidence.review_aspect_rule, evidence.review_aspect_observation, evidence.review_aspect_aggregate, evidence.review_aspect_aggregate_member IN SHARE ROW EXCLUSIVE MODE')
        if conn.execute('SELECT count(*) FROM evidence.review_aspect_aggregate').fetchone()[0] or conn.execute('SELECT count(*) FROM evidence.review_aspect_aggregate_member').fetchone()[0]:
            raise ValueError('Existing aggregates require coordinated rebuild')
        documents = {r[0]:r[1:] for r in conn.execute('SELECT id::text,product_id::text,body FROM evidence.review_document')}
        registered = {r[0]:r[1:] for r in conn.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,k,definition FROM evidence.review_aspect_rule')}
        old = {(r[1],r[2]):r for r in conn.execute('SELECT id::text,document_id::text,rule_id::text,observation_text,direction,evidence_sentences FROM evidence.review_aspect_observation')}
        for review, obs in observations:
            if documents.get(review['document_id']) != (review['product_id'],review['body']):
                raise ValueError('Source document mismatch')
            rule = rules[obs['rule_id']]
            if registered.get(obs['rule_id']) != tuple(rule[k] for k in ['analysis_version','part_type','aspect_code','context_code','k','definition']):
                raise ValueError('Registered rule mismatch')
            existing = old.get((review['document_id'],obs['rule_id']))
            if existing and existing[3:] != (obs['observation_text'],obs['direction'],obs['evidence_sentences']):
                raise ValueError('Existing observation differs')
        archive = conn.execute("SELECT to_regclass('evidence.review_aspect_observation_draft')").fetchone()[0]
        if archive:
            saved = conn.execute('SELECT source_run,source_ordinal,payload FROM evidence.review_aspect_observation_draft ORDER BY source_run,source_ordinal').fetchall()
            if [(r[0],r[1],r[2]) for r in saved] != [('20261002_authorized',i,d) for i,d in enumerate(drafts)]:
                raise ValueError('Archive has unexpected data; refusing drop')
        added = sum((r['document_id'],o['rule_id']) not in old for r,o in observations)
        if apply:
            with conn.cursor() as cur:
                cur.executemany('INSERT INTO evidence.review_aspect_observation (id,document_id,rule_id,observation_text,direction,evidence_sentences) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (document_id,rule_id) DO NOTHING', [(str(uuid5(NAMESPACE,r['document_id']+':'+o['rule_id'])),r['document_id'],o['rule_id'],o['observation_text'],o['direction'],Jsonb(o['evidence_sentences'])) for r,o in observations])
            actual = {(r[0],r[1]):r[2:] for r in conn.execute('SELECT document_id::text,rule_id::text,observation_text,direction,evidence_sentences FROM evidence.review_aspect_observation')}
            assert all(actual[(r['document_id'],o['rule_id'])] == (o['observation_text'],o['direction'],o['evidence_sentences']) for r,o in observations)
            assert all(conn.execute('SELECT id::text FROM evidence.review_aspect_observation WHERE document_id=%s AND rule_id=%s',key).fetchone()[0] == val[0] for key,val in old.items())
            if archive:
                conn.execute('DROP TABLE evidence.review_aspect_observation_draft')
            conn.execute("DELETE FROM _migrations.schema_migrations WHERE version='0009_review_observation_draft'")
        return {'canonical_observations':len(observations),'existing_preserved':len(old),'inserted':added if apply else 0,'would_insert':added if not apply else 0,'applied':apply,'draft_archive_removed':bool(archive) and apply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('outputs/review_full_corpus/20261002_authorized'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    load_dotenv('.env')
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        result=apply_all(conn,args.root,apply=args.apply)
    print(json.dumps(result))


if __name__=='__main__':
    main()
