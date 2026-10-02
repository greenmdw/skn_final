"""Frozen supplemental literal regional model mapping; main run stays unchanged."""
import json,os
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from src.services.review_preparation import prepare_documents,catalog_snapshot,preparation_plan,encoded
from src.services.review_batch import prepare_batches,require_registered_input
from run_review_corpus import ROOT,save,state

def main():
 load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit');target=ROOT/'supplement_literal_regional_alias';target.mkdir(exist_ok=True)
 with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as conn:
  catalog=catalog_snapshot(conn);manifest=prepare_documents(Path('data/reviews').glob('*_review_processed.jsonl'),catalog)
  manifest['rows']=[r for r in manifest['rows'] if r['status']=='matched' and r['record']['data_kind']=='real' and r['record']['model']=='LS32DG800SNXZA'];assert len(manifest['rows'])==2 and all(r['status']=='matched' for r in manifest['rows'])
  manifest['database_import_allowed']=True;manifest['counts']={'matched':2};manifest['authorization']='Same explicit full actual-review loading authorization; main frozen corpus artifacts unchanged.'
  manifest['literal_alias_evidence']={'source':'data/peripherals/monitor_processed.csv','catalog_model':'Odyssey OLED G8 G80SD LS32DG802','official_image_url_contains_source_code':'https://images.samsung.com/is/image/samsung/p6pim/us/ls32dg800snxza/gallery/us-gaming-ls32dg800snxza----inch-odyssey-oled-g--g--sd-silver-552008412','consistent_basic_properties':'32-inch 3840x2160 240Hz OLED G80SD; source first review explicitly states4k240HzOLED; metadata product_name G80SD and literal variant LS32DG802SNXZA. Source image directly links US model800 to this catalog basic product; no guessed retail SKU.'}
  for row in manifest['rows']:row['source_verification_approved']=True
  save(target/'source_manifest.json',manifest);rules=json.loads((ROOT/'rules.json').read_text());save(target/'db_before.json',state(conn))
  dry=preparation_plan(conn,manifest,[],Path('outputs/review_production_provenance'));save(target/'dry_run.json',dry)
  applied=preparation_plan(conn,manifest,[],Path('outputs/review_production_provenance'),apply=True);save(target/'apply_receipt.json',applied);save(target/'db_after.json',state(conn))
  products={p['id']:p for p in catalog};docs=[{'document_id':r['document_id'],'product_id':r['product_id'],'part_type':r['part_type'],'product_name':products[r['product_id']]['name'],'is_synthetic':False,'body':r['document']['body']} for r in manifest['rows']]
  jobs=prepare_batches(target/'batches',docs,rules)
  for job in jobs:require_registered_input(conn,json.loads((Path(job['path'])/'input.json').read_text()))
  save(target/'dispatch_manifest.json',{'registered_preflight_pass':True,'documents':2,'batches':1,'worker_model':'gpt-6-luna','reasoning_effort':'medium','batch_size_max':6})
  print(encoded({'dry':dry,'apply':applied,'dispatch':jobs[0]['path']}))
if __name__=='__main__':main()
