import copy,json,os
from uuid import uuid4
import psycopg
import pytest
from src.services.review_preparation import (exact_match,prepare_documents,catalog_snapshot,production_rules,preparation_plan)


def test_exact_mapping_never_strips_sku_or_picks_ambiguous():
    r={'manufacturer':'로지텍(Logitech)','model':'MX Keys S'}
    cat=[dict(id=str(uuid4()),brand='Logitech',model='MX Keys S',product_type='keyboard')]
    assert exact_match(r,'keyboard',cat)['status']=='matched'
    assert exact_match({**r,'model':'MX Keys'},'keyboard',cat)['status']=='unmatched'
    assert exact_match(r,'keyboard',cat+[{**cat[0],'id':str(uuid4())}])['status']=='ambiguous'
    assert exact_match({**r,'manufacturer':'Logi'},'keyboard',cat)['status']=='unmatched'


@pytest.fixture
def prepared(tmp_path):
    with psycopg.connect(os.environ['DATABASE_URL']) as conn:
        cat=catalog_snapshot(conn);p=next(x for x in cat if x['product_type']=='gpu')
        record={'manufacturer':p['brand'],'model':p['model'],'data_kind':'real','text':'게임 중 팬 소음이 정숙합니다.','metadata':{'component_type':'GPU','review_id':str(uuid4())}}
        path=tmp_path/'computer_review_processed.jsonl';path.write_text(json.dumps(record,ensure_ascii=False)+'\n')
        manifest=prepare_documents([path],cat);manifest['database_import_allowed']=True
        definition={'label':'fan','positive':'Quiet fan','negative':'Loud fan','context':'Gaming','match_policy':'Explicit actual experience'}
        rules=production_rules([dict(id=str(uuid4()),part_type='gpu',aspect_code='fan_quietness',context_code='gaming_load',definition=definition)],k=4)
        # Production version may have same key in another test; the shared fixture transaction rolls back.
        yield conn,manifest,rules,tmp_path/'provenance'
        conn.rollback()


@pytest.mark.db
def test_import_dry_run_noop_and_immutable_metadata(prepared):
    conn,m,r,ledger=prepared
    m=json.loads(json.dumps(m,sort_keys=True))  # Frozen sorted JSON must not change SQL parameter order.
    before=conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0]
    assert preparation_plan(conn,m,r,ledger)['documents']['create']==1
    assert not ledger.exists()
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0]==before
    assert preparation_plan(conn,m,r,ledger,apply=True)['documents']['create']==1
    assert preparation_plan(conn,m,r,ledger)['documents']['same']==1
    assert preparation_plan(conn,m,r,ledger,apply=True)['rules']['same']==1
    original_source=next(iter(m['source_hashes']));original_text=__import__('pathlib').Path(original_source).read_text()
    changed_record=json.loads(original_text);changed_record['text']='New actual body'
    __import__('pathlib').Path(original_source).write_text(json.dumps(changed_record)+'\n')
    fresh=prepare_documents([original_source],catalog_snapshot(conn));fresh['database_import_allowed']=True
    assert fresh['rows'][0]['document_id']==m['rows'][0]['document_id']
    assert preparation_plan(conn,fresh,r,ledger)['conflicts'][0]['reason']=='provenance_changed_rebuild_required'
    __import__('pathlib').Path(original_source).write_text(original_text)
    changed=copy.deepcopy(m);changed['rows'][0]['document']['body']='Changed'
    with pytest.raises(ValueError,match='Body differs'):preparation_plan(conn,changed,r,ledger,apply=True)
    row=m['rows'][0];payload=json.loads((ledger/(row['document_id']+'.json')).read_text());payload['record']['metadata']['new']='changed';(ledger/(row['document_id']+'.json')).write_text(json.dumps(payload))
    assert preparation_plan(conn,m,r,ledger)['conflicts'][0]['reason']=='provenance_changed_rebuild_required'
    with pytest.raises(ValueError,match='conflicts'):preparation_plan(conn,m,r,ledger,apply=True)
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0]==before+1


@pytest.mark.db
def test_rule_conflict_and_unfixed_k_never_overwrite(prepared):
    conn,m,r,ledger=prepared;preparation_plan(conn,m,r,ledger,apply=True)
    bad=copy.deepcopy(r);bad[0]['definition']['positive']='Different';report=preparation_plan(conn,m,bad,ledger)
    assert report['conflicts'][0]['reason']=='registered_rule_conflict_never_overwrite'
    bad=copy.deepcopy(r);bad[0]['k']=None
    assert preparation_plan(conn,m,bad,ledger)['conflicts'][0]['reason']=='production_k_not_frozen'


@pytest.mark.db
def test_unverified_source_and_failed_transaction_isolated(prepared):
    conn,m,r,ledger=prepared;m['rows'][0]['source_verification_required']=True
    assert preparation_plan(conn,m,r,ledger)['conflicts'][0]['reason']=='source_sku_verification_not_approved'
    with pytest.raises(ValueError):preparation_plan(conn,m,r,ledger,apply=True)
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0]==0


@pytest.mark.db
def test_manifest_cannot_replace_original_record_or_invalid_rule_k(prepared):
    from src.services.review_preparation import digest
    conn,m,r,ledger=prepared
    bad=copy.deepcopy(m);bad['rows'][0]['record']['metadata']['new']='invented';bad['rows'][0]['record_sha256']=digest(bad['rows'][0]['record'])
    with pytest.raises(ValueError,match='frozen original'):preparation_plan(conn,bad,r,ledger)
    bad=copy.deepcopy(r);bad[0]['k']=float('nan')
    with pytest.raises(ValueError,match='rule k'):preparation_plan(conn,m,bad,ledger)


@pytest.mark.db
def test_sql_failure_rolls_back_all_documents_and_retry_uses_ledger(prepared):
    conn,m,r,ledger=prepared
    conn.execute("CREATE FUNCTION pg_temp.review_test_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated test failure'; END $$")
    conn.execute('CREATE TRIGGER review_test_fail BEFORE INSERT ON evidence.review_aspect_rule FOR EACH ROW EXECUTE FUNCTION pg_temp.review_test_fail()')
    with pytest.raises(psycopg.errors.RaiseException):preparation_plan(conn,m,r,ledger,apply=True)
    assert conn.execute('SELECT count(*) FROM evidence.review_document').fetchone()[0]==0
    assert list(ledger.glob('*.json'))  # planned provenance survives, conveys no approval
    conn.execute('DROP TRIGGER review_test_fail ON evidence.review_aspect_rule')
    assert preparation_plan(conn,m,r,ledger,apply=True)['documents']['create']==1


@pytest.mark.db
def test_cli_apply_rerun_keeps_provenance_and_distinct_receipts(prepared,tmp_path,monkeypatch):
    import runpy,sys
    conn,m,r,ledger=prepared
    manifest=tmp_path/'approved.json';manifest.write_text(json.dumps(m))
    rules=tmp_path/'rules.json';rules.write_text(json.dumps(r))
    monkeypatch.setattr(sys,'argv',['prepare','--output-dir',str(tmp_path/'run'),'--manifest',str(manifest),'--rules',str(rules),'--provenance-root',str(ledger),'--apply','--batch-limit','0'])
    main=runpy.run_path('db/prepare_review_production.py')['main']
    try:
        assert main()==0
        assert main()==0
        assert len(list((tmp_path/'run/receipts').glob('apply_*.json')))==2
    finally:
        # Only this isolated test DB's rows; CLI owns/commits a separate connection.
        conn.rollback()
        with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as clean:
            clean.execute('DELETE FROM evidence.review_document WHERE id=%s',(m['rows'][0]['document_id'],))
            clean.execute('DELETE FROM evidence.review_aspect_rule WHERE id=%s',(r[0]['id'],))


def test_literal_monitor_code_and_documented_alias_do_not_guess_variants():
    p=dict(id=str(uuid4()),brand='Dell',model='UltraSharp U3223QE',product_type='monitor')
    assert exact_match({'manufacturer':'Dell','model':'U3223QE'},'monitor',[p])['status']=='matched'
    assert exact_match({'manufacturer':'Dell','model':'U2723QE'},'monitor',[p])['status']=='unmatched'
    lg={**p,'brand':'LG','model':'UltraGear 27GP850'}
    assert exact_match({'manufacturer':'LG','model':'27GP850-B'},'monitor',[lg])['status']=='matched'
    assert exact_match({'manufacturer':'LG','model':'27GP850-P'},'monitor',[lg])['status']=='unmatched'
    kb={**p,'brand':'한성','model':'GK898B PRO','product_type':'keyboard'}
    assert exact_match({'manufacturer':'한성','model':'GK898B'},'keyboard',[kb])['status']=='unmatched'


@pytest.mark.db
def test_peripheral_registration_and_observation_contract(prepared,tmp_path):
    import runpy
    peripheral_rules=runpy.run_path("db/run_review_corpus.py")["peripheral_rules"]
    from src.services.review_batch import short_wire,restore_keys,require_registered_input
    from src.services.review_observation_import import import_observations
    conn,_,_,_=prepared
    cat=catalog_snapshot(conn);p=next(x for x in cat if x['product_type']=='mouse')
    body='손에 편안하고 오래 써도 피로하지 않습니다.'
    record=dict(manufacturer=p['brand'],model=p['model'],data_kind='real',text=body,metadata={'review_id':str(uuid4())})
    path=tmp_path/'mouse_review_processed.jsonl';path.write_text(json.dumps(record,ensure_ascii=False)+'\n')
    m=prepare_documents([path],cat);m['database_import_allowed']=True
    rules=[r for r in peripheral_rules() if r['part_type']=='mouse'];ledger=tmp_path/'peripheral_ledger'
    assert preparation_plan(conn,m,rules,ledger)['documents']['create']==1
    preparation_plan(conn,m,rules,ledger,apply=True)
    d=m['rows'][0]['document'];src={'analysis_version':rules[0]['analysis_version'],'mode':'production','rules':[{k:r[k] for k in ['id','analysis_version','part_type','aspect_code','context_code','definition']} for r in rules],'reviews':[{'document_id':d['id'],'product_id':d['product_id'],'part_type':'mouse','product_name':p['name'],'is_synthetic':False,'body':body}]}
    assert require_registered_input(conn,src)
    wire,keys=short_wire(src);key=next(k for k,v in keys.items() if v==next(r['id'] for r in rules if r['aspect_code']=='ergonomics'))
    raw={'analysis_version':src['analysis_version'],'results':[{'document_id':d['id'],'result':'ok','observations':[{'rule_key':key,'observation_text':'사용 중 손이 편안하고 피로가 적었다.','direction':'positive','evidence_ids':[wire['reviews'][0]['evidence_spans'][0]['evidence_id']]}],'diagnostics':[]}]}
    canonical=restore_keys(src,wire,raw,keys)
    report=import_observations(conn,src,canonical)
    assert conn.execute('SELECT evidence_sentences FROM evidence.review_aspect_observation WHERE document_id=%s',(d['id'],)).fetchone()[0]==[body]
    import_observations(conn,src,canonical)
    assert conn.execute('SELECT count(*) FROM evidence.review_aspect_observation WHERE document_id=%s',(d['id'],)).fetchone()[0]==1


def test_literal_samsung_seed_image_alias_rejects_other_model_code():
    p=dict(id=str(uuid4()),brand='Samsung',model='Odyssey OLED G8 G80SD LS32DG802',product_type='monitor')
    assert exact_match(dict(manufacturer='Samsung',model='LS32DG800SNXZA'),'monitor',[p])['status']=='matched'
    assert exact_match(dict(manufacturer='Samsung',model='LS27DG500ENXZA'),'monitor',[p])['status']=='unmatched'
    assert exact_match(dict(manufacturer='LG',model='LS32DG800SNXZA'),'monitor',[p])['status']=='unmatched'
