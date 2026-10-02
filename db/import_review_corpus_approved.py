"""Import only mechanically valid, hash-bound coordinator-reviewed results."""
import json,os
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from src.services.review_batch import isolate_with_retry,validate_result
from src.services.review_observation_import import import_observations,read_json
from src.services.review_preparation import digest
ROOT=Path('outputs/review_full_corpus/20261002_authorized')
def main():
 approvals=read_json(ROOT/'semantic_review.json') if (ROOT/'semantic_review.json').exists() else {}
 conflicts=read_json(ROOT/'source_target_conflicts.json') if (ROOT/'source_target_conflicts.json').exists() else {'confirmed':[],'uncertain':[]}
 blocked={r['document_id'] for section in ['confirmed','uncertain'] for r in conflicts[section]}
 load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit')
 receipts=[]
 with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as conn:
  jobs=read_json(ROOT/'batches/jobs.json');supp=ROOT/'supplement_literal_regional_alias/batches/jobs.json'
  if supp.exists():jobs+=read_json(supp)
  for job in jobs:
   p=Path(job['path'])
   if not (p/'first_raw.json').exists():continue
   source=read_json(p/'input.json')
   if not any(r['document_id'] in approvals and approvals[r['document_id']].get('decision')=='accepted' for r in source['reviews']):continue
   try:report=isolate_with_retry(source,read_json(p/'wire.json'),read_json(p/'first_raw.json'),read_json(p/'rule_keys.json'),read_json(p/'retry_01_raw.json') if (p/'retry_01_raw.json').exists() else None)
   except (ValueError,TypeError):continue
   for candidate in report['validated_candidates']:
    doc=candidate['document_id'];approval=approvals.get(doc,{})
    if doc in blocked:continue
    if approval.get('decision')!='accepted' or any(approval.get(k)!=candidate[k] for k in ['result_sha256','input_sha256']):continue
    inp={**source,'reviews':[next(r for r in source['reviews'] if r['document_id']==doc)]};out={'analysis_version':source['analysis_version'],'results':[candidate['canonical_result']]}
    validate_result(inp,candidate['canonical_result'])
    info=import_observations(conn,inp,out);receipts.append({'document_id':doc,'result_sha256':candidate['result_sha256'],'receipt':info})
  counts={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['evidence.review_document','evidence.review_aspect_rule','evidence.review_aspect_observation','evidence.review_embedding','evidence.review_aspect_aggregate']}
 receipt={'approved_documents_checked':len(receipts),'documents':receipts,'database_counts':counts}
 directory=ROOT/'observation_import_receipts';directory.mkdir(exist_ok=True);path=directory/(digest(receipt)+'.json')
 if not path.exists():path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'approved_documents_checked':len(receipts),'database_counts':counts}))
if __name__=='__main__':main()
