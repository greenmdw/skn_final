"""Print original sources for coordinator personal review, never an extractor prompt."""
import argparse,json
from pathlib import Path
from src.services.review_observation_import import read_json
ROOT=Path('outputs/review_full_corpus/20261002_authorized')

def main():
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=25);args=p.parse_args()
    reviewed=read_json(ROOT/'semantic_review.json');rows=read_json(ROOT/'canonical_results.json');rules={r['id']:r for r in read_json(ROOT/'rules.json')}
    statuses={r['document_id']:r for r in read_json(ROOT/'document_status.json')}
    pack=[r for r in rows if r['review']['document_id'] not in reviewed and (r['status'] in ['unresolved','source_quarantined'] or statuses[r['review']['document_id']].get('mechanical_retry_recovered'))][:args.limit]
    (ROOT/'current_review_pack_ids.json').write_text(json.dumps([r['review']['document_id'] for r in pack])+'\n')
    for i,row in enumerate(pack):
        review=row['review'];body=review['body']
        print(f'[{i}] {review["document_id"]} {review["part_type"]} {review["product_name"]}\nBODY:{body}')
        for obs in row['result']['observations']:
            rule=rules[obs['rule_id']]
            print('OBS',rule['aspect_code'],rule['context_code'],obs['direction'],obs['observation_text'],'E',[(body.find(e),len(e)) for e in obs['evidence_sentences']])
        print('DIAG',row['result']['diagnostics'])
    print('Read the full printed source before recording a personal decision; this script does not approve results.')

if __name__=='__main__':main()
