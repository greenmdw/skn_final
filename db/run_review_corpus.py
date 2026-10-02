"""Authorized full corpus setup/checkpoint. No model calls or implicit approval."""
import argparse,json,os
from collections import Counter
from pathlib import Path
from uuid import uuid5
import psycopg
from dotenv import load_dotenv
from src.services.review_preparation import (prepare_documents,catalog_snapshot,production_rules,preparation_plan,encoded,digest,RULE_NS,VERSION)
from src.services.review_batch import prepare_batches,require_registered_input

ROOT=Path('outputs/review_full_corpus/20261002_authorized')
QUALITIES={
 'keyboard':{'typing_feel':('Typing feel','comfortable/smooth/precise experienced typing','uncomfortable/stiff/missed experienced typing'), 'typing_noise':('Typing sound','experienced quiet/pleasant typing sound','experienced excessive/disruptive typing sound'), 'connection_stability':('Connection reliability','experienced reliable wired/wireless connection','experienced disconnects, failed pairing or connection instability'), 'controls_usability':('Controls and configuration','experienced easy shortcuts, software or remapping','experienced inconvenient shortcuts, software or remapping'), 'physical_usability':('Layout and ergonomics','experienced comfortable layout, size or posture','experienced inconvenient layout, size or posture')},
 'mouse':{'tracking_input':('Tracking and clicks','experienced accurate tracking/responsive reliable clicks','experienced inaccurate tracking/missed or unintended clicks'), 'ergonomics':('Grip and comfort','experienced comfortable grip, weight or posture','experienced uncomfortable grip, weight or fatigue'), 'connection_stability':('Connection reliability','experienced stable pairing/connection','experienced disconnects or failed pairing'), 'controls_usability':('Controls and software','experienced convenient buttons, scroll or configuration','experienced inconvenient buttons, scroll or configuration'), 'battery_runtime':('Battery use','experienced satisfactory runtime/charging','experienced insufficient runtime/inconvenient charging')},
 'monitor':{'image_quality':('Displayed image quality','experienced clear, accurate or satisfying image/color/brightness','experienced poor image/color/brightness, bleed or artifacts'), 'motion_response':('Motion performance','experienced smooth responsive motion','experienced blur, ghosting, tearing or lag'), 'connection_stability':('Connection reliability','experienced reliable display connection/wake','experienced connection/wake failures'), 'controls_ergonomics':('Controls and positioning','experienced convenient menus, stand or adjustment','experienced inconvenient menus, stand or adjustment'), 'functional_reliability':('Actual functioning','expressed satisfactory functional reliability in actual use','experienced malfunction, flicker, dead pixels or failure')},
 'speaker':{'sound_quality':('Reproduced sound','experienced clear/balanced/satisfying sound','experienced muffled/distorted/unsatisfying sound'), 'output_level':('Usable output level','experienced sufficient usable loudness','experienced insufficient usable loudness'), 'unwanted_noise':('Unwanted noise','experienced absence of hiss/hum/interference','experienced hiss/hum/interference'), 'connection_controls':('Connections and controls','experienced convenient connections/volume controls','experienced inconvenient connections/volume controls'), 'functional_reliability':('Actual functioning','expressed reliable operation in actual use','experienced channel/dropout/power failures')}
}

def peripheral_rules():
 rows=[]
 for part,aspects in QUALITIES.items():
  for code,(label,pos,neg) in aspects.items():
   context='actual_use';rows.append({'id':str(uuid5(RULE_NS,':'.join([VERSION,part,code,context]))),'analysis_version':VERSION,'part_type':part,'aspect_code':code,'context_code':context,'k':4,'definition':{'label':label,'positive':pos,'negative':neg,'context':'Concrete actual installed/used target-product experience; preserve task, connection, environment and comparator in evidence.','match_policy':'Only explicit experienced functional evaluation. Specification/future possibility, price/design preference, shipping/service and bare generic praise are not evidence. Opposing evaluation of the same inseparable aspect/context is mixed; distinct setups must retain qualification. Diagnose ambiguous_rule or unmapped_rule with partial when eligible evidence cannot be assigned conservatively.'}})
 return rows

def state(conn):
 return {t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['catalog.product','evidence.review_document','evidence.review_aspect_rule','evidence.review_aspect_observation','evidence.review_embedding','evidence.review_aspect_aggregate']}

def save(p,obj):
 s=encoded(obj)+'\n'
 if p.exists() and p.read_text()!=s:raise ValueError('Frozen artifact changed: '+str(p))
 if not p.exists():p.write_text(s)

def setup(conn,apply=False):
 ROOT.mkdir(parents=True,exist_ok=True);catalog=catalog_snapshot(conn);save(ROOT/'catalog.json',catalog)
 if (ROOT/'source_manifest.json').exists():manifest=json.loads((ROOT/'source_manifest.json').read_text())
 else:
  manifest=prepare_documents(Path('data/reviews').glob('*_review_processed.jsonl'),catalog)
  manifest['database_import_allowed']=True;manifest['authorization']='2026-10-02 explicit user: load all actual reviews, instruct observations, consolidate; no synthetic production, no destructive overwrites'
  manifest['mapping_policy']='Brand/full model or distinguishing literal model code; regional aliases only with local seed links; catalog basic option rather than retail SKU. Historical research flag is not an approval barrier.'
  manifest['model_alias_evidence']={'27GP850-B':'data/peripherals/monitor_processed.csv: official support product-27GP850-BC','34WP65C-B':'data/peripherals/monitor_processed.csv: official image 34WP65C-B_AEK_EEUK_UK_C and support product-34WP65C-BL'}
  for row in manifest['rows']:
   if row['status']=='matched':
    note=str((row['record'].get('metadata') or {}).get('listing_note') or '')
    if 'prev_gen' in note or 'variant_' in note:
     row['status']='contradictory_generation_or_variant';row['reason']=note;row.pop('document',None);continue
    row['source_verification_approved']=True
    row['identity_check']='Actual-source manufacturer/model maps uniquely to catalog basic option; no contradicted model suffix; model-encoded capacities preserved. SSD catalog may represent capacity options rather than one retail SKU.'
  manifest['counts']=dict(Counter(r['status'] for r in manifest['rows']));save(ROOT/'source_manifest.json',manifest)
 pilot=json.loads(Path('outputs/review_aspect_luna_regression/20261002_compact_v6/regression/rules.json').read_text())
 rules=production_rules(pilot,k=4)+peripheral_rules();save(ROOT/'rules.json',rules)
 save(ROOT/'rule_policy.json',{'PC':'82 frozen v6 definitions unchanged','peripheral':'new explicitly scoped actual-use functional contract v1 under production version; no scoring-axis changes','k':4,'k_policy':'Provisional operational choice only, no claim of extraction accuracy or score computation','database_import_allowed':True})
 if not (ROOT/'db_before.json').exists():save(ROOT/'db_before.json',state(conn))
 plan=preparation_plan(conn,manifest,rules,Path('outputs/review_production_provenance'),apply=apply)
 receipts=ROOT/'receipts';receipts.mkdir(exist_ok=True)
 receipt=receipts/(('apply_' if apply else 'dry_run_')+digest(plan)+'.json');save(receipt,plan)
 legacy_receipt=ROOT/('apply_receipt.json' if apply else 'dry_run.json')
 if not legacy_receipt.exists():save(legacy_receipt,plan)
 if apply:
  save(ROOT/'db_after_loading.json',state(conn))
  products={p['id']:p for p in catalog};docs=[{'document_id':r['document_id'],'product_id':r['product_id'],'part_type':r['part_type'],'product_name':products[r['product_id']]['name'],'is_synthetic':False,'body':r['document']['body']} for r in manifest['rows'] if r['status']=='matched']
  docs.sort(key=lambda r:(r['part_type'],r['product_id'],r['document_id']))
  jobs=prepare_batches(ROOT/'batches',docs,rules)
  for job in jobs:require_registered_input(conn,json.loads((Path(job['path'])/'input.json').read_text()))
  save(ROOT/'dispatch_manifest.json',{'registered_preflight_pass':True,'documents':len(docs),'batches':len(jobs),'batch_size_max':6,'worker_model':'gpt-6-luna','reasoning_effort':'medium','max_concurrency':2,'actual_tokens':'unmeasured'})
 print(encoded({'counts':manifest['counts'],'plan':plan,'batches':len(jobs) if apply else None}))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');a=parser.parse_args();load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit')
 with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as c:
  if not a.apply:c.execute('SET default_transaction_read_only=on')
  setup(c,a.apply)
