import copy
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from src.services.review_observation_import import import_observations

pytestmark = pytest.mark.db


@pytest.fixture
def sample():
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        product = conn.execute('SELECT product_id FROM catalog.gpu_spec LIMIT 1').fetchone()[0]
        doc, rule = uuid4(), uuid4()
        body = '게임 중 팬 소리는 거의 안 들립니다.'
        conn.execute('INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) '
                     'VALUES (%s,%s,%s,false,%s)', (doc, product, 'test', body))
        version = str(uuid4())
        conn.execute('INSERT INTO evidence.review_aspect_rule '
                     '(id,analysis_version,part_type,aspect_code,context_code,k,definition) '
                     "VALUES (%s,%s,'gpu','fan_quietness','gaming_load',4,%s)",
                     (rule, version, Jsonb({'positive': 'Low noise'})))
        source = dict(analysis_version=version, mode='production', rules=[dict(
            id=str(rule), analysis_version=version, part_type='gpu', aspect_code='fan_quietness',
            context_code='gaming_load', definition={'positive': 'Low noise'})], reviews=[dict(
                document_id=str(doc), product_id=str(product), part_type='gpu', product_name='GPU',
                is_synthetic=False, body=body)])
        output = dict(analysis_version=version, results=[dict(document_id=str(doc), result='ok',
            observations=[dict(rule_id=str(rule), observation_text='Quiet fan during gaming',
                               direction='positive', evidence_sentences=[body])], diagnostics=[])])
        yield conn, source, output
        conn.rollback()


def test_import_replace_dry_run_and_idempotence(sample):
    conn, source, output = sample
    assert import_observations(conn, source, output, dry_run=True)['changed_documents'] == 1
    assert conn.execute('SELECT count(*) FROM evidence.review_aspect_observation').fetchone()[0] == 0
    assert import_observations(conn, source, output)['changed_documents'] == 1
    identity = conn.execute('SELECT id FROM evidence.review_aspect_observation').fetchone()[0]
    assert import_observations(conn, source, output)['changed_documents'] == 0
    output['results'][0]['observations'][0]['direction'] = 'negative'
    import_observations(conn, source, output)
    assert conn.execute('SELECT id FROM evidence.review_aspect_observation').fetchone()[0] == identity
    output['results'][0]['observations'] = []
    import_observations(conn, source, output)
    assert conn.execute('SELECT count(*) FROM evidence.review_aspect_observation').fetchone()[0] == 0


@pytest.mark.parametrize('failure', ['partial', 'evidence', 'version', 'missing', 'duplicate', 'stale', 'part'])
def test_invalid_import_leaves_existing_observations_unchanged(sample, failure):
    conn, source, output = sample
    import_observations(conn, source, output)
    changed = copy.deepcopy(output)
    if failure == 'partial': changed['results'][0]['result'] = 'partial'
    if failure == 'evidence': changed['results'][0]['observations'][0]['evidence_sentences'] = ['invented']
    if failure == 'version': changed['analysis_version'] = 'wrong'
    if failure == 'missing': changed['results'] = []
    if failure == 'duplicate': changed['results'][0]['observations'] *= 2
    if failure == 'stale': source['reviews'][0]['body'] += ' changed'
    if failure == 'part': source['reviews'][0]['part_type'] = 'cpu'
    with pytest.raises(ValueError): import_observations(conn, source, changed)
    assert conn.execute('SELECT direction FROM evidence.review_aspect_observation').fetchone()[0] == 'positive'


def test_aggregate_blocks_changes_but_allows_exact_reimport(sample):
    conn, source, output = sample
    import_observations(conn, source, output)
    conn.execute('INSERT INTO evidence.review_aspect_aggregate(product_id,rule_id,p,n,mixed,k) '
                 'VALUES (%s,%s,1,0,0,4)', (source['reviews'][0]['product_id'], source['rules'][0]['id']))
    assert import_observations(conn, source, output)['changed_documents'] == 0
    output['results'][0]['observations'] = []
    with pytest.raises(ValueError, match='rebuild'): import_observations(conn, source, output)
