#!/usr/bin/env python3
"""Offline per-document isolation. No DB/model calls; first_raw.json is read-only."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.services.review_batch import isolate_batch
from src.services.review_observation_import import read_json

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch-dir',type=Path,required=True);p.add_argument('--approvals',type=Path);a=p.parse_args();root=a.batch_dir
    source=read_json(root/'input.json');wire=read_json(root/'wire.json');keys=read_json(root/'rule_keys.json');approval=read_json(a.approvals) if a.approvals else {}
    try:
        raw=read_json(root/'first_raw.json');report=isolate_batch(source,wire,raw,keys,approval)
    except (OSError,ValueError) as exc:
        report={'validated_candidates':[],'approved_importable':[],'quarantine':[{'document_id':r['document_id'],'reason':'Raw JSON rejected: '+str(exc)} for r in source['reviews']]}
    (root/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for candidate in report['validated_candidates']:
        target=root/'candidates';target.mkdir(exist_ok=True);(target/(candidate['document_id']+'.json')).write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')
    for item in report['approved_importable']:
        target=root/'approved'/item['input']['reviews'][0]['document_id'];target.mkdir(parents=True,exist_ok=True)
        for key in ['input','output']:(target/(key+'.json')).write_text(json.dumps(item[key],ensure_ascii=False,indent=2)+'\n')
    # Any previously exported approvals that no longer match must not remain importable.
    allowed={item['input']['reviews'][0]['document_id'] for item in report['approved_importable']}
    stale=[str(d) for d in (root/'approved').glob('*') if d.is_dir() and d.name not in allowed]
    report['stale_approved_exports']=stale
    if stale:
        from uuid import uuid4
        for old in map(Path,stale):
            target=root/'quarantined_exports'/(old.name+'-'+uuid4().hex);target.parent.mkdir(exist_ok=True);old.rename(target)
        report['stale_approved_exports_quarantined']=True
        (root/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:len(report[k]) for k in ['validated_candidates','approved_importable','quarantine']}));return 1 if report['quarantine'] else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError) as exc:print('Batch rejected: '+str(exc),file=sys.stderr);raise SystemExit(1)
