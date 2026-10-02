"""Exercise the CLI with the user's three-review agent response, including commit visibility."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[1]
AGENT_OUTPUT = r'''{"analysis_version":"aspect-smoke-test-v1","results":[{"document_id":"00000000-0000-4000-8000-000000000101","result":"ok","observations":[{"rule_id":"00000000-0000-4000-8000-000000000009","observation_text":"The registered GPU's fan is barely audible during gaming","direction":"positive","evidence_sentences":["게임 중 팬 소리는 거의 안 들립니다."]}],"diagnostics":[]},{"document_id":"00000000-0000-4000-8000-000000000102","result":"ok","observations":[{"rule_id":"00000000-0000-4000-8000-000000000009","observation_text":"The registered GPU's fan noise during gaming is loud and disturbing","direction":"negative","evidence_sentences":["게임 중 팬 소리가 너무 커서 거슬립니다."]}],"diagnostics":[]},{"document_id":"00000000-0000-4000-8000-000000000103","result":"ok","observations":[],"diagnostics":[{"code":"not_experienced","evidence_text":"게임할 때 팬이 조용하면 좋겠어요.","detail":"Reviewer has not used the product yet; the statement is an expectation, not an actual experience."}]}]}'''


def test_agent_response_is_committed_by_cli(tmp_path):
    output = json.loads(AGENT_OUTPUT)
    ids = [r['document_id'] for r in output['results']]
    rule_id = output['results'][0]['observations'][0]['rule_id']
    definition = dict(label='Fan quietness', positive='Low or barely audible fan noise',
                      negative='Loud or disturbing fan noise', context='During gaming',
                      match_policy='Apply only to actual fan-noise experiences explicitly reported during gaming. Do not infer a noise source or workload.')
    bodies = ['게임 중 팬 소리는 거의 안 들립니다.', '게임 중 팬 소리가 너무 커서 거슬립니다.',
              '아직 사용 전입니다. 게임할 때 팬이 조용하면 좋겠어요.']
    dsn = os.environ['DATABASE_URL']
    with psycopg.connect(dsn) as conn:
        assert 'test' in conn.info.dbname.lower()
        # The prompt's product UUID is fictional; map only the input to a seeded GPU.
        product = str(uuid4())
        conn.execute("INSERT INTO catalog.product(id,name,brand,model,product_type) VALUES (%s,'CLI import GPU','Test',%s,'gpu')",(product,product))
        conn.execute('INSERT INTO catalog.gpu_spec(product_id) VALUES (%s)',(product,))
        for doc, body in zip(ids, bodies):
            conn.execute('INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body) '
                         'VALUES (%s,%s,%s,true,%s)', (doc, product, 'synthetic-smoke-test', body))
        conn.execute('INSERT INTO evidence.review_aspect_rule '
                     '(id,analysis_version,part_type,aspect_code,context_code,k,definition) '
                     "VALUES (%s,%s,'gpu','fan_quietness','gaming_load',4,%s)",
                     (rule_id, output['analysis_version'], Jsonb(definition)))
    try:
        source = dict(analysis_version=output['analysis_version'], mode='test', rules=[dict(
            id=rule_id, analysis_version=output['analysis_version'], part_type='gpu',
            aspect_code='fan_quietness', context_code='gaming_load', definition=definition)],
            reviews=[dict(document_id=doc, product_id=product, part_type='gpu', product_name='Test GPU A',
                          is_synthetic=True, body=body) for doc, body in zip(ids, bodies)])
        input_file, output_file = tmp_path / 'input.json', tmp_path / 'output.json'
        input_file.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        output_file.write_text(AGENT_OUTPUT, encoding='utf-8')
        command = [sys.executable, str(ROOT / 'db/import_review_observations.py'),
                   '--input', str(input_file), '--output', str(output_file)]

        def run(*extra):
            result = subprocess.run(command + list(extra), cwd=ROOT, capture_output=True, text=True,
                                    timeout=30, env={**os.environ, 'DATABASE_URL': dsn})
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        def stored():
            # A fresh connection proves that the CLI committed, not just executed INSERT.
            with psycopg.connect(dsn) as conn:
                return conn.execute('SELECT document_id::text, rule_id::text, observation_text, '
                                    'direction, evidence_sentences, id::text '
                                    'FROM evidence.review_aspect_observation '
                                    'WHERE document_id=ANY(%s::uuid[]) ORDER BY document_id', (ids,)).fetchall()

        assert run('--dry-run') == dict(documents=3, observations=2, changed_documents=2, dry_run=True)
        assert stored() == []
        assert run() == dict(documents=3, observations=2, changed_documents=2, dry_run=False)
        rows = stored()
        assert len(rows) == 2
        for row, expected in zip(rows, output['results'][:2]):
            obs = expected['observations'][0]
            assert row[:5] == (expected['document_id'], obs['rule_id'], obs['observation_text'],
                               obs['direction'], obs['evidence_sentences'])
        assert run() == dict(documents=3, observations=2, changed_documents=0, dry_run=False)
        assert stored() == rows
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute('DELETE FROM evidence.review_aspect_observation WHERE document_id=ANY(%s::uuid[])', (ids,))
            conn.execute('DELETE FROM evidence.review_document WHERE id=ANY(%s::uuid[])', (ids,))
            conn.execute('DELETE FROM evidence.review_aspect_rule WHERE id=%s', (rule_id,))
            conn.execute('DELETE FROM catalog.gpu_spec WHERE product_id=%s',(product,))
            conn.execute('DELETE FROM catalog.product WHERE id=%s',(product,))
