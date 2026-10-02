"""Bounded offline wire preparation, failure isolation, and explicit approval exports."""
import json
from pathlib import Path
from uuid import UUID
from src.services.review_evidence_wire import wire_input,reconstruct_wire,restore
from src.services.review_observation_import import Input,Output,read_json
from src.services.review_preparation import digest,encoded,PARTS


def canonical_rules(registered):
    return [{k:r[k] for k in ['id','analysis_version','part_type','aspect_code','context_code','definition']} for r in registered]

def short_wire(source):
    inp=Input.model_validate(source)
    if inp.mode!='production' or any(r.is_synthetic for r in inp.reviews):raise ValueError('Production actual-source reviews only')
    if not 1<=len(inp.reviews)<=6:raise ValueError('Batch size1..6')
    if len({r.document_id for r in inp.reviews})!=len(inp.reviews):raise ValueError('Duplicate document ID')
    if source['analysis_version'].startswith('pilot'):raise ValueError('Pilot version not production')
    if not source['analysis_version'].strip():raise ValueError('Blank version')
    for r in inp.rules:
        if set(r.definition)!={'label','positive','negative','context','match_policy'} or any(not isinstance(v,str) or not v.strip() for v in r.definition.values()):raise ValueError('Incomplete rule definition')
    rules=sorted(source['rules'],key=lambda r:(r['part_type'],r['aspect_code'],r['context_code']))
    keys={};counts={}
    for r in rules:
        if r['analysis_version']!=source['analysis_version']:raise ValueError('Rule version mismatch')
        counts[r['part_type']]=counts.get(r['part_type'],0)+1;key=r['part_type']+str(counts[r['part_type']]);keys[key]=r['id']
    if len(set(keys.values()))!=len(rules):raise ValueError('Duplicate rule UUID')
    for r in inp.reviews:
        if not r.body.strip() or not any(x.part_type==r.part_type for x in inp.rules):raise ValueError('Body/rule component mismatch')
    wire=wire_input(source);wire['rules']=[{**{k:v for k,v in r.items() if k!='id'},'rule_key':key} for key,r in zip(keys,rules)]
    return wire,keys


def restore_keys(source,wire,raw,keys):
    expected,expected_keys=short_wire(source)
    if wire!=expected or keys!=expected_keys:raise ValueError('Frozen wire/key mapping differs')
    # reconstruct_wire expects UUID rules; the spans are still verified completely.
    full={**wire,'rules':source['rules']};reconstruct_wire(full,source)
    mapped=json.loads(encoded(raw))
    if not isinstance(mapped.get('results'),list):raise ValueError('Output results array required')
    docs={r['document_id']:r for r in source['reviews']};rules={r['id']:r for r in source['rules']}
    for result in mapped['results']:
        doc=docs.get(result.get('document_id'))
        if doc is None:raise ValueError('Unknown/cross-document result')
        for obs in result.get('observations',[]):
            if set(obs)!={'rule_key','observation_text','direction','evidence_ids'}:raise ValueError('Short-key observation fields')
            key=obs.pop('rule_key');rid=keys.get(key)
            if not rid or rules[rid]['part_type']!=doc['part_type']:raise ValueError('Unknown/cross-component short rule key')
            obs['rule_id']=rid
    restored=restore(source,mapped)
    # Source datasets sometimes repeat identical sentences at distinct span IDs.
    # The canonical contract requires unique evidence strings; exact deduplication
    # retains every distinct original string and changes no semantic content.
    for result in restored['results']:
        for obs in result['observations']:
            obs['evidence_sentences']=list(dict.fromkeys(obs['evidence_sentences']))
    return restored


def validate_result(source,result):
    out=Output.model_validate({'analysis_version':source['analysis_version'],'results':[result]});entry=out.results[0]
    review=source['reviews'][0];rules={r['id']:r for r in source['rules']};seen=set()
    if str(entry.document_id)!=review['document_id']:raise ValueError('Document ID mismatch')
    codes={d.code for d in entry.diagnostics}
    unresolved=bool(codes&{'ambiguous_rule','unmapped_rule'})
    if entry.result=='partial' and not unresolved or unresolved and entry.result not in {'partial','error'}:raise ValueError('Partial/diagnostic mismatch')
    if entry.result=='error' and (entry.observations or not codes&{'invalid_input','analysis_failed','synthetic_in_production'}):raise ValueError('Error contract')
    for obs in entry.observations:
        rid=str(obs.rule_id);r=rules.get(rid)
        if not r or r['part_type']!=review['part_type'] or rid in seen:raise ValueError('Rule membership/component/duplicate')
        seen.add(rid)
        if not obs.observation_text.strip() or len(set(obs.evidence_sentences))!=len(obs.evidence_sentences) or any(not e.strip() or e not in review['body'] for e in obs.evidence_sentences):raise ValueError('Exact evidence/text invalid')
    for d in entry.diagnostics:
        if not d.detail.strip() or d.evidence_text is not None and (not d.evidence_text.strip() or d.evidence_text not in review['body']):raise ValueError('Diagnostic evidence/detail')
    return 'unresolved' if entry.result!='ok' or codes&{'ambiguous_rule','unmapped_rule','invalid_input','analysis_failed','synthetic_in_production'} else 'validated_candidate'


def isolate_batch(source,wire,raw,keys,approvals=None):
    """Per-document isolation; a malformed doc does not discard other valid docs.

    Approval is bound to canonical document result hash and input hash. A model ok
    or a mechanically valid candidate never supplies approval or triggers scores.
    """
    approvals=approvals or {};report={'validated_candidates':[],'approved_importable':[],'quarantine':[]};results=raw.get('results') if isinstance(raw,dict) else None
    if not isinstance(raw,dict) or set(raw)!={'analysis_version','results'} or raw.get('analysis_version')!=source['analysis_version'] or not isinstance(results,list):
        report['quarantine']=[{'document_id':r['document_id'],'reason':'batch version/results invalid'} for r in source['reviews']];return report
    for review in source['reviews']:
        doc=review['document_id'];matches=[r for r in results if isinstance(r,dict) and r.get('document_id')==doc]
        if len(matches)!=1:report['quarantine'].append({'document_id':doc,'reason':'missing/duplicate output'});continue
        single={**source,'reviews':[review]}
        # Restore against entire frozen source then slice, so batch key mapping stays frozen.
        try:
            mapped=restore_keys(source,wire,{'analysis_version':raw['analysis_version'],'results':[matches[0] if r['document_id']==doc else {'document_id':r['document_id'],'result':'ok','observations':[],'diagnostics':[]} for r in source['reviews']]},keys)
            result=next(r for r in mapped['results'] if r['document_id']==doc);status=validate_result(single,result)
            if status!='validated_candidate':
                contradiction=any(d['code']=='invalid_input' for d in result['diagnostics'])
                report['quarantine'].append({'document_id':doc,'reason':'model_invalid_input_contradicts_preflight' if contradiction else status,'canonical_result':result,'contradictory_model_invalid_input':contradiction});continue
            candidate={'document_id':doc,'result_sha256':digest(result),'input_sha256':digest(single),'canonical_result':result};report['validated_candidates'].append(candidate)
            a=approvals.get(doc)
            if a and a.get('decision')=='accepted' and a.get('result_sha256')==candidate['result_sha256'] and a.get('input_sha256')==candidate['input_sha256']:
                report['approved_importable'].append({'input':single,'output':{'analysis_version':raw['analysis_version'],'results':[result]}})
        except (ValueError,KeyError,TypeError) as exc:report['quarantine'].append({'document_id':doc,'reason':str(exc)})
    for r in results:
        if not isinstance(r,dict) or r.get('document_id') not in {x['document_id'] for x in source['reviews']}:report['quarantine'].append({'document_id':None,'reason':'unexpected result'})
    return report


def prepare_batches(root:Path,documents,rules):
    root.mkdir(parents=True,exist_ok=True);jobs=[]
    for i in range(0,len(documents),6):
        rs=documents[i:i+6];parts={r['part_type'] for r in rs};source={'analysis_version':rules[0]['analysis_version'],'mode':'production','rules':[r for r in canonical_rules(rules) if r['part_type'] in parts],'reviews':rs};wire,keys=short_wire(source);job=root/f'batch_{i//6+1:05d}';job.mkdir(exist_ok=True)
        for name,value in [('input.json',source),('wire.json',wire),('rule_keys.json',keys)]:
            p=job/name
            if p.exists() and json.loads(p.read_text())!=value:raise ValueError('Frozen batch changed; new run required')
            if not p.exists():p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        raw=job/'first_raw.json';status='pending'
        if raw.exists():
            try:report=isolate_batch(source,wire,read_json(raw),keys)
            except (ValueError,TypeError) as exc:report={'quarantine':[{'reason':str(exc)}]}
            (job/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');status='completed_no_replay' if not report['quarantine'] else 'quarantined_no_auto_retry'
        jobs.append({'path':str(job),'document_ids':[r['document_id'] for r in rs],'status':status,'first_output':'first_raw.json','model':'gpt-6-luna','reasoning_effort':'medium','fork_turns':'none'})
    (root/'jobs.json').write_text(json.dumps(jobs,ensure_ascii=False,indent=2)+'\n');return jobs


def require_registered_input(conn,source):
    """Read-only dispatch prerequisite: canonical docs/rules must already exist."""
    from psycopg.rows import dict_row
    from psycopg import sql
    short_wire(source)
    with conn.cursor(row_factory=dict_row) as cur:
        for r in source['rules']:
            cur.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,definition FROM evidence.review_aspect_rule WHERE id=%s',(r['id'],))
            if cur.fetchone()!=r:raise ValueError('Missing/changed registered rule')
        for r in source['reviews']:
            cur.execute('SELECT product_id::text,body,is_synthetic FROM evidence.review_document WHERE id=%s',(r['document_id'],))
            if cur.fetchone()!={k:r[k] for k in ['product_id','body','is_synthetic']}:raise ValueError('Missing/changed registered document')
            cur.execute(sql.SQL('SELECT 1 FROM catalog.{} WHERE product_id=%s').format(sql.Identifier(r['part_type']+'_spec')),(r['product_id'],))
            if not cur.fetchone():raise ValueError('Missing component spec membership')
    return True


def save_first_output(batch_dir:Path,text:str):
    """Preserve exact first worker bytes (including malformed output) exclusively."""
    with (batch_dir/'first_raw.json').open('x',encoding='utf-8') as f:
        f.write(text)


def isolate_with_retry(source,wire,first_raw,keys,retry_raw=None):
    """One targeted mechanical retry, preserving first failure history.

    Semantically unresolved and mechanically successful results are immutable.
    Replaying any such document in the retry rejects that retry as a whole.
    """
    first=isolate_batch(source,wire,first_raw,keys)
    if retry_raw is None:return first
    report=json.loads(encoded(first));failed={r.get('document_id') for r in first['quarantine'] if not r.get('canonical_result') and r.get('document_id') is not None}
    targets=[r.get('document_id') for r in retry_raw.get('results',[]) if isinstance(r,dict)] if isinstance(retry_raw,dict) else []
    report['first_attempt_quarantine']=first['quarantine'];report['mechanically_recovered']=[]
    if not targets or len(set(targets))!=len(targets) or any(doc not in failed for doc in targets):
        report['retry_error']='Retry must target only unique originally mechanically failed documents';return report
    retry=isolate_batch(source,wire,retry_raw,keys)
    report['retry_attempt_quarantine']=[r for r in retry['quarantine'] if r.get('document_id') in targets or r.get('document_id') is None]
    recovered_unresolved=[]
    for candidate in retry['validated_candidates']:
        if candidate['document_id'] in failed:
            report['validated_candidates'].append(candidate);report['mechanically_recovered'].append(candidate['document_id'])
    for item in retry['quarantine']:
        if item.get('document_id') in failed and item.get('canonical_result'):
            recovered_unresolved.append(item);report['mechanically_recovered'].append(item['document_id'])
    report['quarantine']=[r for r in report['quarantine'] if r.get('document_id') not in report['mechanically_recovered']]
    report['quarantine'].extend(recovered_unresolved)
    return report
