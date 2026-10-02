"""Read-only production source/rule read-back and bounded-run cost/accounting audit."""
import json,os,hashlib
from pathlib import Path
from collections import Counter
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
ROOT=Path('outputs/review_full_corpus/20261002_authorized')
def read(p):return json.loads(p.read_text())
def main():
 manifests=[read(ROOT/'source_manifest.json'),read(ROOT/'supplement_literal_regional_alias/source_manifest.json')]
 excluded={r['document_id'] for r in read(ROOT/'source_target_conflicts.json')['confirmed']}
 expected={r['document_id']:r['document'] for m in manifests for r in m['rows'] if r['status']=='matched' and r['document_id'] not in excluded}
 rules=read(ROOT/'rules.json');load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit')
 with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
  c.execute('SET TRANSACTION READ ONLY')
  docs=c.execute('SELECT id::text,product_id::text,source_code,is_synthetic,body,posted_at FROM evidence.review_document').fetchall();actual={d['id']:d for d in docs}
  assert set(expected)==set(actual),'Document identity mismatch'
  assert all(actual[k]==v for k,v in expected.items()),'Original body/metadata mismatch'
  registered={r['id']:r for r in c.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,k,definition FROM evidence.review_aspect_rule').fetchall()}
  assert registered=={r['id']:{k:r[k] for k in ['id','analysis_version','part_type','aspect_code','context_code','k','definition']} for r in rules},'Registered rule mismatch'
  counts={t:c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ['catalog.product','evidence.review_document','evidence.review_aspect_rule','evidence.review_aspect_observation','evidence.review_embedding','evidence.review_aspect_aggregate','evidence.review_summary']}
 assert all((Path('outputs/review_production_provenance')/(k+'.excluded.json')).exists() for k in excluded)
 jobs=read(ROOT/'batches/jobs.json')+read(ROOT/'supplement_literal_regional_alias/batches/jobs.json');paths=[Path(j['path']) for j in jobs]
 retries=[p for p in paths if (p/'retry_01_raw.json').exists()]
 statuses=read(ROOT/'document_status.json');reviewed=read(ROOT/'semantic_review.json');canonical=read(ROOT/'canonical_results.json')
 retrydocs=[]
 for p in retries:
  raw=read(p/'retry_01_raw.json');retrydocs.extend(r.get('document_id') for r in raw.get('results',[]))
 cost={'actual_tokens':'unmeasured','backend_model_call_count':'unmeasured; collaboration tasks may contain multiple backend model operations','first_raw_batch_files':len(paths),'documents_dispatched_once':sum(len(read(p/'input.json')['reviews']) for p in paths),'targeted_retry_batch_files':len(retries),'targeted_retry_result_rows':len(retrydocs),'targeted_retry_unique_documents':len(set(retrydocs)),'worker_assignment_groups':len(read(ROOT/'worker_assignments.json')),'worker_model':'gpt-6-luna','reasoning_effort':'medium','maximum_concurrent_workers':2,'input_characters_proxy':sum(len((p/'wire.json').read_text()) for p in paths),'proxy_is_not_actual_tokens_or_token_savings':True}
 summary={'original_documents_exact_readback':len(actual),'registered_rules_exact_readback':len(registered),'excluded_documents_absent':sorted(excluded),'db_counts':counts,'batch_completion':len(paths),'pending_batches':sum(not (p/'first_raw.json').exists() for p in paths),'document_status_counts':dict(Counter(s['status'] for s in statuses)),'personal_review_decisions':dict(Counter(r['decision'] for r in reviewed.values())),'personally_reviewed_documents':len(reviewed),'not_personally_reviewed_documents':len(statuses)-len(reviewed),'canonical_observation_drafts':sum(len(r['result']['observations']) for r in canonical),'database_import_allowed':True,'scoring_or_embedding_run':False}
 for name,obj in [('final_readback_audit.json',summary),('cost_and_attempt_accounting.json',cost)]: (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'exact_original_documents':len(actual),'exact_registered_rules':len(registered),'first_batches':len(paths),'retry_batches':len(retries),'retry_documents':len(set(retrydocs)),'db_observations':counts['evidence.review_aspect_observation']},ensure_ascii=False))
if __name__=='__main__':main()
