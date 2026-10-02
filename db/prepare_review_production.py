#!/usr/bin/env python3
"""Read-only production preparation by default. --apply requires an approved manifest."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from src.services.review_preparation import catalog_snapshot,prepare_documents,production_rules,preparation_plan,digest
from src.services.review_batch import prepare_batches

def save(path,value):
    text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=text:raise ValueError('Refusing to overwrite preparation artifact; use new output directory: '+str(path))
    if not path.exists():path.write_text(text)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--source-dir',type=Path,default=Path('data/reviews'));p.add_argument('--pilot-rules',type=Path,default=Path('outputs/review_aspect_luna_regression/20261002_compact_v6/regression/rules.json'));p.add_argument('--provenance-root',type=Path,default=Path('outputs/review_production_provenance'));p.add_argument('--k',type=float);p.add_argument('--manifest',type=Path);p.add_argument('--rules',type=Path);p.add_argument('--scope',choices=['all','documents','rules'],default='all');p.add_argument('--apply',action='store_true');p.add_argument('--batch-limit',type=int,default=1)
    a=p.parse_args();dsn=os.environ.get('DATABASE_URL')
    if not dsn:raise ValueError('DATABASE_URL must be explicitly set')
    a.output_dir.mkdir(parents=True,exist_ok=True)
    with psycopg.connect(dsn,connect_timeout=10,autocommit=True) as conn:
        if not a.apply:conn.execute('SET default_transaction_read_only=on')
        cat=catalog_snapshot(conn)
        manifest=json.loads(a.manifest.read_text()) if a.manifest else prepare_documents(a.source_dir.glob('*_review_processed.jsonl'),cat)
        rules=json.loads(a.rules.read_text()) if a.rules else production_rules(json.loads(a.pilot_rules.read_text()),k=a.k)
        save(a.output_dir/'catalog.json',cat);save(a.output_dir/'source_manifest.json',manifest);save(a.output_dir/'production_rules.json',rules)
        plan=preparation_plan(conn,manifest if a.scope!='rules' else {**manifest,'rows':[]},rules if a.scope!='documents' else [],a.provenance_root,apply=a.apply)
        receipts=a.output_dir/'receipts';receipts.mkdir(exist_ok=True)
        save(receipts/(('apply_' if a.apply else 'dry_run_')+digest(plan)[:16]+'.json'),plan)
        if not a.apply and a.batch_limit>0:
            names={r['id']:r['name'] for r in cat};docs=[{'document_id':r['document_id'],'product_id':r['product_id'],'part_type':r['part_type'],'product_name':names[r['product_id']],'is_synthetic':False,'body':r['record']['text']} for r in manifest['rows'] if r['status']=='matched' and r['part_type'] in {'cpu','gpu','mainboard','ram','ssd','psu','case','cooler'}][:a.batch_limit*6]
            jobs=prepare_batches(a.output_dir/'batches',docs,rules)
            save(a.output_dir/'dispatch_gate.json',{'dispatch_allowed':False,'reason':'Preparation only. Documents/rules must exist, source/SKU prerequisites and registration configuration must be approved, and observations require semantic approval. No model call executed.','prepared_jobs':len(jobs)})
    print(json.dumps({'source_counts':manifest['counts'],'document_plan':plan['documents'],'rule_plan':plan['rules'],'conflicts':len(plan['conflicts']),'apply_allowed':plan['apply_allowed'],'applied':a.apply}));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError) as exc:print('Preparation rejected: '+str(exc),file=sys.stderr);raise SystemExit(1)
    except psycopg.Error as exc:print('Database operation failed (SQLSTATE='+str(exc.sqlstate)+'); transaction rolled back',file=sys.stderr);raise SystemExit(1)
