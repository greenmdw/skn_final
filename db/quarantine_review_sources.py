"""Rollback only two confirmed incorrect, run-owned, unprocessed source inserts."""
import argparse,json,os
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from src.services.review_source_quarantine import compensate_source_conflicts
from src.services.review_preparation import digest

ROOT=Path('outputs/review_full_corpus/20261002_authorized')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    manifest=json.loads((ROOT/'source_manifest.json').read_text())
    decisions=json.loads((ROOT/'source_target_conflicts.json').read_text())['confirmed']
    load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit')
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as conn:
        if not args.apply:conn.execute('SET default_transaction_read_only=on')
        report=compensate_source_conflicts(conn,manifest,decisions,Path('outputs/review_production_provenance'),apply=args.apply)
    receipts=ROOT/'source_compensation_receipts';receipts.mkdir(exist_ok=True)
    path=receipts/(('apply_' if args.apply else 'dry_run_')+digest(report)+'.json')
    if not path.exists():path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
