"""Reconstruct all frozen input/wire/key snapshots from original source manifests."""
import hashlib,json
from pathlib import Path
from src.services.review_batch import short_wire,canonical_rules
from src.services.review_preparation import validate_manifest_sources
ROOT=Path('outputs/review_full_corpus/20261002_authorized')
def main():
 catalog={p['id']:p for p in json.loads((ROOT/'catalog.json').read_text())};rules=json.loads((ROOT/'rules.json').read_text());hashes={};checked=0
 for manifest,jobroot in [(ROOT/'source_manifest.json',ROOT/'batches'),(ROOT/'supplement_literal_regional_alias/source_manifest.json',ROOT/'supplement_literal_regional_alias/batches')]:
  m=json.loads(manifest.read_text());validate_manifest_sources(m)
  docs=[{'document_id':row['document_id'],'product_id':row['product_id'],'part_type':row['part_type'],'product_name':catalog[row['product_id']]['name'],'is_synthetic':False,'body':row['document']['body']} for row in m['rows'] if row['status']=='matched']
  if jobroot==ROOT/'batches':docs.sort(key=lambda d:(d['part_type'],d['product_id'],d['document_id']))
  for n,start in enumerate(range(0,len(docs),6),1):
   reviews=docs[start:start+6];parts={d['part_type'] for d in reviews};expected={'analysis_version':rules[0]['analysis_version'],'mode':'production','rules':[x for x in canonical_rules(rules) if x['part_type'] in parts],'reviews':reviews};wire,keys=short_wire(expected);p=jobroot/f'batch_{n:05d}'
   for name,value in [('input.json',expected),('wire.json',wire),('rule_keys.json',keys)]:
    f=p/name
    if json.loads(f.read_text())!=value:raise ValueError('Changed frozen input snapshot: '+str(f))
    hashes[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
   checked+=1
 value={'batches_verified_against_original_frozen_manifests':checked,'files':hashes,'rule_snapshot_sha256':hashlib.sha256((ROOT/'rules.json').read_bytes()).hexdigest()};p=ROOT/'frozen_input_checksums.json'
 if p.exists() and json.loads(p.read_text())!=value:raise ValueError('Frozen input checksum mismatch')
 if not p.exists():p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'verified_batches':checked,'checksummed_files':len(hashes),'original_source_files_unchanged':True}))
if __name__=='__main__':main()
