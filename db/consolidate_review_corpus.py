"""Collect full corpus observations with no automatic semantic approval."""
import json,hashlib
from pathlib import Path
from collections import Counter,defaultdict
from src.services.review_batch import isolate_batch,isolate_with_retry
from src.services.review_observation_import import read_json
ROOT=Path('outputs/review_full_corpus/20261002_authorized')
def main():
 jobs=json.loads((ROOT/'batches/jobs.json').read_text());supp=ROOT/'supplement_literal_regional_alias/batches/jobs.json'
 if supp.exists():jobs+=json.loads(supp.read_text())
 records=[];combined=[];counts=Counter();coverage=Counter();byaspect=Counter();attempts=[]
 source_conflicts=json.loads((ROOT/'source_target_conflicts.json').read_text()) if (ROOT/'source_target_conflicts.json').exists() else {'confirmed':[],'uncertain':[]}
 excluded={r['document_id'] for r in source_conflicts['confirmed']}
 target_uncertain={r['document_id'] for r in source_conflicts['uncertain']}
 for job in jobs:
  p=Path(job['path']);source=read_json(p/'input.json');raw=p/'first_raw.json'
  if not raw.exists():
   for r in source['reviews']:records.append({'document_id':r['document_id'],'part_type':r['part_type'],'status':'pending','batch':str(p)})
   counts['pending']+=len(source['reviews']);continue
  try:
   report=isolate_batch(source,read_json(p/'wire.json'),read_json(raw),read_json(p/'rule_keys.json'))
  except (ValueError,TypeError) as e:report={'validated_candidates':[],'approved_importable':[],'quarantine':[{'document_id':r['document_id'],'reason':str(e)} for r in source['reviews']]}
  recovered=[];retry=p/'retry_01_raw.json'
  if retry.exists():
   try:
    report=isolate_with_retry(source,read_json(p/'wire.json'),read_json(raw),read_json(p/'rule_keys.json'),read_json(retry))
    recovered=report.get('mechanically_recovered',[])
   except (ValueError,TypeError) as e:report['retry_error']=str(e)
   report['retry_01_sha256']=hashlib.sha256(retry.read_bytes()).hexdigest()
  (p/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
  restored={r['document_id']:r['canonical_result'] for r in report['validated_candidates']}
  restored.update({r['document_id']:r['canonical_result'] for r in report['quarantine'] if r.get('canonical_result')})
  (p/'canonical_output.json').write_text(json.dumps({'analysis_version':source['analysis_version'],'results':[restored[r['document_id']] for r in source['reviews'] if r['document_id'] in restored],'missing_or_invalid_documents':[r['document_id'] for r in source['reviews'] if r['document_id'] not in restored]},ensure_ascii=False,indent=2)+'\n')
  attempts.append({'batch':str(p),'first_raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'input_sha256':hashlib.sha256((p/'input.json').read_bytes()).hexdigest()})
  candidates={r['document_id']:r for r in report['validated_candidates']};q={r.get('document_id'):r for r in report['quarantine']};rules={r['id']:r for r in source['rules']}
  for review in source['reviews']:
   doc=review['document_id'];entry={'document_id':doc,'product_id':review['product_id'],'part_type':review['part_type'],'batch':str(p)}
   if doc in candidates:
    c=candidates[doc];result=c['canonical_result'];entry.update(status='validated_candidate',observation_count=len(result['observations']),result_sha256=c['result_sha256'],input_sha256=c['input_sha256'],mechanical_retry_recovered=doc in recovered);combined.append({'review':review,'result':result,'status':'validated_candidate'});coverage[review['part_type']]+=1
    for o in result['observations']:byaspect[(review['product_id'],review['part_type'],rules[o['rule_id']]['aspect_code'],rules[o['rule_id']]['context_code'],o['direction'])]+=1
   else:
    quarantine=q.get(doc,{'reason':'unexpected isolation failure'});entry.update(status='unresolved' if quarantine.get('canonical_result') else 'mechanical_failed',reason=quarantine['reason'])
    if quarantine.get('canonical_result'):combined.append({'review':review,'result':quarantine['canonical_result'],'status':'unresolved'})
   if doc in excluded:
    entry['extraction_status']=entry['status'];entry['status']='source_quarantined';entry['reason']='confirmed_source_target_conflict; owned unprocessed insert compensated, original preserved'
    if combined and combined[-1]['review']['document_id']==doc:combined[-1]['status']='source_quarantined'
   elif doc in target_uncertain:entry['source_identity_gate']='source_target_uncertain_not_importable'
   counts[entry['status']]+=1;records.append(entry)
 def write(name,obj):(ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
 write('progress.json',{'document_counts':dict(counts),'completed_batches':len(attempts),'total_batches':len(jobs),'mechanical_valid_by_component':dict(coverage),'actual_tokens':'unmeasured','semantic_review':'Not yet all reviewed; candidates do not imply acceptance'})
 write('document_status.json',records);write('canonical_results.json',combined);write('batch_attempts.json',attempts);write('product_aspect_direction_drafts.json',[{'product_id':k[0],'part_type':k[1],'aspect_code':k[2],'context_code':k[3],'direction':k[4],'count':v,'approval':'draft_not_scored'} for k,v in sorted(byaspect.items())])
 print(json.dumps({'counts':dict(counts),'completed_batches':len(attempts),'observations':sum(len(r['result']['observations']) for r in combined)},ensure_ascii=False))
if __name__=='__main__':main()
