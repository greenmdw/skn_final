"""Explicit review prerequisite for recommendation-success regressions, test DBs only.

Other review tests keep an empty baseline. This fixture uses mixed-only evidence so
existing recommendation regression expectations retain a neutral review score.
"""
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from src.services.review_aspect_score import load_review_profile_config


@contextmanager
def neutral_review_prerequisite(dsn):
    if 'test' not in conninfo_to_dict(dsn).get('dbname','').lower():
        raise ValueError('review regression prerequisites require an isolated test database')
    config = load_review_profile_config()
    rules = []
    document_id, observation_id, aggregate_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(dsn,autocommit=True) as conn:
        with conn.transaction():
            for part_type, aspects in config['part_types'].items():
                for aspect, entry in aspects.items():
                    for context in entry['contexts']:
                        rule_id = uuid4()
                        conn.execute(
                            'INSERT INTO evidence.review_aspect_rule '
                            '(id,analysis_version,part_type,aspect_code,context_code,k,definition) '
                            'VALUES (%s,%s,%s,%s,%s,4,%s)',
                            (rule_id,config['analysis_version'],part_type,aspect,context,
                             Jsonb({'fixture':'neutral recommendation regression'})),
                        )
                        rules.append(rule_id)
                        if (part_type,aspect,context)==('gpu','fan_quietness','gaming_load'):
                            fan_rule = rule_id
            product_id = conn.execute('SELECT product_id FROM catalog.gpu_spec LIMIT 1').fetchone()[0]
            conn.execute(
                'INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) '
                "VALUES (%s,%s,'test-recommendation-prerequisite',false,'Mixed fan experience')",
                (document_id,product_id),
            )
            conn.execute(
                'INSERT INTO evidence.review_aspect_observation '
                '(id,document_id,rule_id,observation_text,direction,evidence_sentences) '
                "VALUES (%s,%s,%s,'Mixed fan experience','mixed',%s)",
                (observation_id,document_id,fan_rule,Jsonb(['Mixed fan experience'])),
            )
            conn.execute(
                'INSERT INTO evidence.review_aspect_aggregate(id,product_id,rule_id,p,n,mixed,k) '
                'VALUES (%s,%s,%s,0,0,1,4)',(aggregate_id,product_id,fan_rule),
            )
            conn.execute(
                'INSERT INTO evidence.review_aspect_aggregate_member(aggregate_id,observation_id) '
                'VALUES (%s,%s)',(aggregate_id,observation_id),
            )
        try:
            yield
        finally:
            with conn.transaction():
                conn.execute('DELETE FROM evidence.review_aspect_aggregate_member WHERE aggregate_id=%s',(aggregate_id,))
                conn.execute('DELETE FROM evidence.review_aspect_aggregate WHERE id=%s',(aggregate_id,))
                conn.execute('DELETE FROM evidence.review_aspect_observation WHERE id=%s',(observation_id,))
                conn.execute('DELETE FROM evidence.review_document WHERE id=%s',(document_id,))
                conn.execute('DELETE FROM evidence.review_aspect_rule WHERE id=ANY(%s::uuid[])',(rules,))
