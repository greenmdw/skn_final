"""Exact catalog mapping and immutable review/rule preparation; never guesses SKUs."""
from __future__ import annotations
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DOCUMENT_NS = uuid5(NAMESPACE_URL, 'truefit:production:review-document:v1')
RULE_NS = uuid5(NAMESPACE_URL, 'truefit:production:review-rule:v1')
VERSION = 'review-aspect-v6-prod-20261002'
PARTS = {'cpu','gpu','mainboard','ram','ssd','psu','case','cooler','keyboard','mouse','monitor','speaker'}
# Literal regional suffix aliases evidenced by the seed's own official support/
# image links. This is a product/basic-option identity, not a retail SKU assertion.
MODEL_ALIASES = {'monitor': {'27GP850-B':'UltraGear 27GP850',
                            '34WP65C-B':'UltraWide 34WP65C',
                            'LS32DG800SNXZA':'Odyssey OLED G8 G80SD LS32DG802'}}

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()

def normalized(value):
    return ' '.join(str(value).casefold().split())

def part_type(value):
    return 'mainboard' if value == 'motherboard' else value

def brands(value):
    # Only literal full brand and explicitly supplied parenthetical aliases.
    return {normalized(value), *(normalized(s) for s in re.findall(r'\(([^()]+)\)',value))}

def exact_match(record, part, catalog):
    model=normalized(record['model'])
    alias=MODEL_ALIASES.get(part,{}).get(record['model'])
    def model_equal(p):
        pm=normalized(p['model'])
        if pm==model:return True
        if alias and pm==normalized(alias):return True
        # A complete distinguishing model code may have descriptive line-name
        # words around it. Never remove/change a code suffix or infer a variant.
        return part=='monitor' and bool(re.search(r'\d',model)) and bool(re.search(r'(?<![a-z0-9-])'+re.escape(model)+r'(?![a-z0-9-])',pm))
    candidates = [p for p in catalog if part_type(p['product_type']) == part
                  and model_equal(p)
                  and normalized(p['brand']) in brands(record['manufacturer'])]
    return {'status': 'matched' if len(candidates)==1 else 'ambiguous' if candidates else 'unmatched',
            'candidate_ids': [str(p['id']) for p in candidates],
            'evidence': {'source_brand':record['manufacturer'],'source_model':record['model'],
                         'normalization':'case/whitespace; literal brand aliases; monitor complete model-code token or documented seed alias',
                         'literal_model_alias':alias,
                         'retail_sku_certification':False}}

def catalog_snapshot(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT id::text,name,brand,model,product_type,attributes FROM catalog.product ORDER BY id')
        return cur.fetchall()

def prepare_documents(paths, catalog):
    rows=[]; identities={}; counts=Counter(); file_hashes={}
    for path in sorted(map(Path, paths)):
        file_hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        default=path.name.removesuffix('_review_processed.jsonl')
        for line_no,line in enumerate(path.read_text().splitlines(),1):
            if not line.strip():continue
            record=json.loads(line); metadata=record.get('metadata') or {}
            part=part_type(str(metadata.get('component_type',default)).lower())
            row={'source_file':str(path),'source_line':line_no,'record':record,'record_sha256':digest(record),'part_type':part}
            if record.get('data_kind')!='real':row['status']='synthetic_excluded'
            elif not isinstance(record.get('text'),str) or not record['text'].strip():row['status']='invalid_body'
            else:
                match=exact_match(record,part,catalog);row.update(match)
                # IDs do not contain body/product hashes, so changed input conflicts.
                external=metadata.get('review_id') or metadata.get('Review_ID')
                identity=path.name+(':external:'+str(external) if external else ':row:'+str(line_no))
                row['source_identity']=identity;row['identity_kind']='external_id' if external else 'frozen_file_row'
                row['source_verification_required']=metadata.get('sku_match_status')=='not_evaluated' or metadata.get('model_match_status')=='model_family_matched' or 'unreviewed' in str(metadata.get('usage_status',''))
                row['source_verification_approved']=False
                row['document_id']=str(uuid5(DOCUMENT_NS,identity))
                previous=identities.get(identity)
                if previous:
                    row['status']='duplicate' if previous['record_sha256']==row['record_sha256'] else 'identity_conflict'
                    if row['status']=='identity_conflict':previous['status']='identity_conflict'
                else:identities[identity]=row
                if row['status']=='matched':
                    row['product_id']=match['candidate_ids'][0]
                    row['document']={'id':row['document_id'],'product_id':row['product_id'],
                        'source_code':'processed-jsonl-v1:'+default,'is_synthetic':False,
                        'body':record['text'],'posted_at':None}
            rows.append(row)
    counts.update(r['status'] for r in rows)
    return {'manifest_version':'review-source-v1','database_import_allowed':False,'source_hashes':file_hashes,
            'catalog_sha256':digest(catalog),'counts':dict(counts),'rows':rows,
            'provenance_policy':'Full original normalized record/metadata retained in immutable external ledger, no added DB columns. Date-only/unknown-zone dates retained externally; posted_at NULL. Missing external IDs use frozen file-row identity; source reorder requires explicit reconciliation.'}

def production_rules(pilot_rules, *, k=None):
    if k is not None and (not math.isfinite(float(k)) or float(k)<=0):raise ValueError('k must be finite and positive')
    return [{'id':str(uuid5(RULE_NS,VERSION+':'+r['part_type']+':'+r['aspect_code']+':'+r['context_code'])),
             **{key:r[key] for key in ['part_type','aspect_code','context_code','definition']},
             'analysis_version':VERSION,'k':k,'pilot_rule_id':r['id']} for r in pilot_rules]

def validate_manifest_sources(manifest):
    source_lines={}
    for p,h in manifest['source_hashes'].items():
        if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:raise ValueError('Changed source file; freeze/reconcile required: '+p)
        source_lines[p]=Path(p).read_text().splitlines()
    for row in manifest['rows']:
        if digest(row['record'])!=row['record_sha256']:raise ValueError('Changed manifest record')
        try:original=json.loads(source_lines[row['source_file']][row['source_line']-1])
        except (KeyError,IndexError,ValueError):raise ValueError('Invalid original source address')
        if original!=row['record']:raise ValueError('Manifest record differs from frozen original source')
        if row.get('document'):
            doc=row['document']
            if original.get('data_kind')!='real' or doc['is_synthetic'] is not False:raise ValueError('Actual-source production only')
            if doc['body']!=original['text']:raise ValueError('Body differs from original source')
            metadata=original.get('metadata') or {};external=metadata.get('review_id') or metadata.get('Review_ID')
            identity=Path(row['source_file']).name+(':external:'+str(external) if external else ':row:'+str(row['source_line']))
            if row['source_identity']!=identity or doc['id']!=str(uuid5(DOCUMENT_NS,identity)):raise ValueError('Production document namespace/identity mismatch')

def preparation_plan(conn, manifest, rules, provenance_root:Path, *, apply=False):
    """One DB transaction, no UPDATE/DELETE. Immutable provenance is staged first.

    Ledger files can remain after rollback: they preserve intended input, confer no
    approval, and make retry deterministic. Existing DB docs without provenance
    are conflicts; changed docs/metadata require a coordinated rebuild.
    """
    validate_manifest_sources(manifest)
    if apply and not manifest.get('database_import_allowed'):raise ValueError('Manifest is preparation-only, not approved for database import')
    docs=[r for r in manifest['rows'] if r['status']=='matched'];conflicts=[];new_docs=[];new_rules=[];same_docs=0;same_rules=0
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        if apply:
            cur.execute('LOCK TABLE catalog.product IN SHARE MODE')
            cur.execute('LOCK TABLE evidence.review_document,evidence.review_aspect_rule IN SHARE ROW EXCLUSIVE MODE')
        current_catalog=catalog_snapshot(conn)
        for row in docs:
            if (provenance_root/(row['document_id']+'.excluded.json')).exists():
                conflicts.append({'document_id':row['document_id'],'reason':'source_identity_quarantined_never_reload'});continue
            doc=row['document'];cur.execute('SELECT id::text,product_id::text,source_code,is_synthetic,body,posted_at FROM evidence.review_document WHERE id=%s',(doc['id'],));existing=cur.fetchone()
            cur.execute('SELECT id::text,name,brand,model,product_type,attributes FROM catalog.product WHERE id=%s',(doc['product_id'],));product=cur.fetchone()
            match=exact_match(row['record'],row['part_type'],current_catalog)
            if not product or match['status']!='matched' or match['candidate_ids']!=[doc['product_id']]:conflicts.append({'document_id':doc['id'],'reason':'catalog_changed'});continue
            if row.get('source_verification_required') and not row.get('source_verification_approved'):
                conflicts.append({'document_id':doc['id'],'reason':'source_sku_verification_not_approved'});continue
            ledger=provenance_root/(doc['id']+'.json');payload={'source_identity':row['source_identity'],'record':row['record'],'document':doc,'part_type':row['part_type']}
            if ledger.exists() and json.loads(ledger.read_text())!=payload:conflicts.append({'document_id':doc['id'],'reason':'provenance_changed_rebuild_required'});continue
            if existing:
                if existing!=doc:conflicts.append({'document_id':doc['id'],'reason':'document_changed_rebuild_required'})
                elif not ledger.exists():conflicts.append({'document_id':doc['id'],'reason':'missing_immutable_provenance'})
                else:same_docs+=1
            else:new_docs.append((doc,ledger,payload))
        seen=set()
        for r in rules:
            key=(r['analysis_version'],r['part_type'],r['aspect_code'],r['context_code'])
            if r['part_type'] not in PARTS or any(not isinstance(v,str) or not v.strip() for v in key):raise ValueError('Invalid rule component/key')
            if key in seen:raise ValueError('Duplicate production rule key')
            seen.add(key)
            if r['analysis_version']!=VERSION or r['id']!=str(uuid5(RULE_NS,':'.join(key))):raise ValueError('Rule version/production UUID mismatch')
            if r['k'] is not None and (isinstance(r['k'],bool) or not isinstance(r['k'],(int,float)) or not math.isfinite(r['k']) or r['k']<=0):raise ValueError('Invalid configured rule k')
            if set(r['definition'])!={'label','positive','negative','context','match_policy'} or any(not isinstance(v,str) or not v.strip() for v in r['definition'].values()):raise ValueError('Incomplete registered definition')
            if r['k'] is None:conflicts.append({'rule_id':r['id'],'reason':'production_k_not_frozen'});continue
            desired={k:r[k] for k in ['id','analysis_version','part_type','aspect_code','context_code','k','definition']}
            cur.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,k,definition FROM evidence.review_aspect_rule WHERE id=%s OR (analysis_version,part_type,aspect_code,context_code)=(%s,%s,%s,%s)',(r['id'],*key));existing=cur.fetchall()
            if not existing:new_rules.append(desired)
            elif len(existing)==1 and existing[0]==desired:same_rules+=1
            else:conflicts.append({'rule_id':r['id'],'reason':'registered_rule_conflict_never_overwrite'})
        report={'dry_run':not apply,'documents':{'create':len(new_docs),'same':same_docs,'selected':len(docs)},'rules':{'create':len(new_rules),'same':same_rules,'selected':len(rules)},'conflicts':conflicts,'constraints_clear':not conflicts,'apply_allowed':not conflicts and bool(manifest.get('database_import_allowed')),'rollback':'Any SQL/error aborts whole transaction; no overwrite/delete. External immutable planned provenance may remain.'}
        if apply:
            if conflicts:raise ValueError('Preparation conflicts; no database writes')
            provenance_root.mkdir(parents=True,exist_ok=True)
            for doc,ledger,payload in new_docs:
                text=encoded(payload)+'\n'
                if not ledger.exists():
                    with ledger.open('x') as f:f.write(text)
                elif json.loads(ledger.read_text())!=payload:raise ValueError('Concurrent provenance change')
                cur.execute('INSERT INTO evidence.review_document(id,product_id,source_code,is_synthetic,body,posted_at) VALUES (%s,%s,%s,%s,%s,%s)',tuple(doc[k] for k in ['id','product_id','source_code','is_synthetic','body','posted_at']))
                cur.execute('SELECT id::text,product_id::text,source_code,is_synthetic,body,posted_at FROM evidence.review_document WHERE id=%s',(doc['id'],));assert cur.fetchone()==doc
            for rule in new_rules:
                cur.execute('INSERT INTO evidence.review_aspect_rule(id,analysis_version,part_type,aspect_code,context_code,k,definition) VALUES (%s,%s,%s,%s,%s,%s,%s)',tuple(rule[k] for k in ['id','analysis_version','part_type','aspect_code','context_code','k'])+(Jsonb(rule['definition']),))
                cur.execute('SELECT id::text,analysis_version,part_type,aspect_code,context_code,k,definition FROM evidence.review_aspect_rule WHERE id=%s',(rule['id'],));assert cur.fetchone()==rule
    return report
