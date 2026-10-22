"""Descriptive product/aspect/direction consolidation; never computes Q/R or scores."""
import json,os
from pathlib import Path
from collections import Counter,defaultdict
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from src.services.review_observation_import import read_json
ROOT=Path('outputs/review_full_corpus/20261002_authorized')

def main():
    reviews=read_json(ROOT/'semantic_review.json');rows=read_json(ROOT/'canonical_results.json');statuses=read_json(ROOT/'document_status.json');rules={r['id']:r for r in read_json(ROOT/'rules.json')}
    grouped=defaultdict(Counter);details=[];coverage=defaultdict(Counter)
    for status in statuses:
        doc=status['document_id'];decision=reviews.get(doc,{}).get('decision','not_personally_reviewed')
        coverage[status['part_type']][status['status']]+=1
        if doc in reviews:coverage[status['part_type']]['personally_reviewed']+=1
    for row in rows:
        review=row['review'];doc=review['document_id'];decision=reviews.get(doc,{}).get('decision','not_personally_reviewed')
        bucket='approved' if row['status']=='validated_candidate' and decision=='accepted' else 'source_quarantined' if row['status']=='source_quarantined' else decision
        for obs in row['result']['observations']:
            rule=rules[obs['rule_id']];key=(review['product_id'],review['part_type'],rule['aspect_code'],rule['context_code'],obs['direction'])
            grouped[key][bucket]+=1
            details.append({'document_id':doc,'product_id':review['product_id'],'part_type':review['part_type'],'aspect_code':rule['aspect_code'],'context_code':rule['context_code'],'direction':obs['direction'],'result_status':row['status'],'semantic_decision':decision,'import_gate':'approved_only' if bucket=='approved' else 'withheld','observation_text':obs['observation_text'],'evidence_sentences':obs['evidence_sentences']})
    risk_pending=[s['document_id'] for s in statuses if s['document_id'] not in reviews and (s['status'] in ['unresolved','mechanical_failed','source_quarantined'] or s.get('mechanical_retry_recovered') or s.get('source_identity_gate'))]
    load_dotenv('.env');os.environ.setdefault('DATABASE_URL','postgresql://truefit:truefit@127.0.0.1:5432/truefit')
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        confirmed=conn.execute('SELECT o.document_id::text,d.product_id::text,r.part_type,r.aspect_code,r.context_code,o.direction,o.observation_text,o.evidence_sentences FROM evidence.review_aspect_observation o JOIN evidence.review_document d ON d.id=o.document_id JOIN evidence.review_aspect_rule r ON r.id=o.rule_id WHERE r.analysis_version=%s ORDER BY d.product_id,r.aspect_code,r.context_code,o.direction,o.document_id',('review-aspect-v6-prod-20261002',)).fetchall()
        legacy_count=conn.execute('SELECT count(*) AS n FROM evidence.review_summary').fetchone()['n']
    confirmed_groups=Counter((o['product_id'],o['part_type'],o['aspect_code'],o['context_code'],o['direction']) for o in confirmed)
    def groups(counter):return [{'product_id':k[0],'part_type':k[1],'aspect_code':k[2],'context_code':k[3],'direction':k[4],'count':v,'score_computed':False} for k,v in sorted(counter.items())]
    artifacts={'consolidated_observation_drafts.json':details,'consolidated_product_aspect_direction.json':[{'product_id':k[0],'part_type':k[1],'aspect_code':k[2],'context_code':k[3],'direction':k[4],'counts_by_review_gate':dict(v),'score_computed':False} for k,v in sorted(grouped.items())],'confirmed_database_observations.json':confirmed,'confirmed_product_aspect_direction.json':groups(confirmed_groups),'semantic_review_scope.json':{'personally_reviewed_documents':len(reviews),'risk_review_pending_documents':risk_pending,'coverage_by_component':{k:dict(v) for k,v in sorted(coverage.items())},'selection':'All unresolved/mechanical/identity risks plus disclosed component-stratified nonempty/empty samples; not representative and not a full semantic audit.','legacy_review_summary_count':legacy_count,'actual_tokens':'unmeasured'}}
    for name,data in artifacts.items():(ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'canonical_draft_observations':len(details),'confirmed_database_observations':len(confirmed),'risk_review_pending':len(risk_pending),'legacy_review_summary':legacy_count},ensure_ascii=False))

if __name__=='__main__':main()
