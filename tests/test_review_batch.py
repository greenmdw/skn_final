import copy
from pathlib import Path
from uuid import uuid4
import pytest
from src.services.review_batch import short_wire,restore_keys,isolate_batch,prepare_batches
from src.services.review_evidence_wire import segment,reconstruct_wire
from src.services.review_preparation import digest


def fixture_data():
    ids=[str(uuid4()),str(uuid4())];prod=str(uuid4());rules=[dict(id=str(uuid4()),analysis_version='production-test',part_type='gpu',aspect_code='fan_quietness',context_code='gaming_load',definition=dict(label='fan',positive='quiet',negative='loud',context='gaming',match_policy='actual'))]
    source=dict(analysis_version='production-test',mode='production',rules=rules,reviews=[dict(document_id=i,product_id=prod,part_type='gpu',product_name='GPU',is_synthetic=False,body='게임 중 팬 소음이 정숙합니다. 조건은 그대로입니다.') for i in ids]);wire,keys=short_wire(source)
    raw=dict(analysis_version=source['analysis_version'],results=[dict(document_id=i,result='ok',observations=[dict(rule_key='gpu1',observation_text='게임 중 팬이 정숙했다.',direction='positive',evidence_ids=[segment(i,source['reviews'][n]['body'])[0]['evidence_id']])],diagnostics=[]) for n,i in enumerate(ids)])
    return source,wire,keys,raw


def test_short_keys_exact_restore_and_cross_component_doc_rejection():
    source,wire,keys,raw=fixture_data();out=restore_keys(source,wire,raw,keys)
    assert 'body' not in wire['reviews'][0]
    assert out['results'][0]['observations'][0]['rule_id']==source['rules'][0]['id']
    assert out['results'][0]['observations'][0]['evidence_sentences'][0] in source['reviews'][0]['body']
    bad=copy.deepcopy(raw);bad['results'][0]['observations'][0]['rule_key']='gpu99'
    with pytest.raises(ValueError,match='short rule key'):restore_keys(source,wire,bad,keys)
    bad=copy.deepcopy(raw);bad['results'][0]['observations'][0]['evidence_ids']=raw['results'][1]['observations'][0]['evidence_ids']
    with pytest.raises(ValueError,match='cross-document'):restore_keys(source,wire,bad,keys)
    bad=copy.deepcopy(wire);bad['reviews'][0]['evidence_spans'].pop()
    with pytest.raises(ValueError,match='wire/key'):restore_keys(source,bad,raw,keys)


def test_mixed_valid_failed_isolation_and_hash_bound_approval():
    source,wire,keys,raw=fixture_data();bad=copy.deepcopy(raw);bad['results'][1]['observations'][0]['rule_key']='invented'
    report=isolate_batch(source,wire,bad,keys)
    assert len(report['validated_candidates'])==1 and len(report['quarantine'])==1 and report['approved_importable']==[]
    c=report['validated_candidates'][0];a={c['document_id']:{**c,'decision':'accepted'}}
    assert len(isolate_batch(source,wire,bad,keys,a)['approved_importable'])==1
    a[c['document_id']]['result_sha256']='stale';assert not isolate_batch(source,wire,bad,keys,a)['approved_importable']
    partial=copy.deepcopy(raw);partial['results'][1]['result']='partial';partial['results'][1]['diagnostics']=[dict(code='ambiguous_rule',evidence_id=None,detail='Actual use uncertain')]
    assert len(isolate_batch(source,wire,partial,keys)['quarantine'])==1


def test_resumption_preserves_first_output_and_never_replays(tmp_path):
    source,wire,keys,raw=fixture_data();jobs=prepare_batches(tmp_path,source['reviews'],source['rules'])
    assert jobs[0]['status']=='pending'
    p=Path(jobs[0]['path'])/'first_raw.json'
    import json
    p.write_text(json.dumps(raw));before=p.read_bytes()
    assert prepare_batches(tmp_path,source['reviews'],source['rules'])[0]['status']=='completed_no_replay'
    assert p.read_bytes()==before


def test_complete_lossless_source_and_reordered_spans_rejected():
    source,wire,keys,raw=fixture_data();canonical_wire={**wire,'rules':source['rules']}
    assert reconstruct_wire(canonical_wire,source)==source
    bad=copy.deepcopy(canonical_wire);bad['reviews'][0]['evidence_spans'].reverse()
    with pytest.raises(ValueError):reconstruct_wire(bad,source)


def test_cross_component_key_and_top_level_contract_rejected():
    source,wire,keys,raw=fixture_data()
    source['rules'].append({**source['rules'][0],'id':str(uuid4()),'part_type':'cpu'})
    wire,keys=short_wire(source);bad=copy.deepcopy(raw);bad['results'][0]['observations'][0]['rule_key']='cpu1'
    with pytest.raises(ValueError,match='cross-component'):restore_keys(source,wire,bad,keys)
    bad=copy.deepcopy(raw);bad['extra']='unexpected'
    assert len(isolate_batch(source,wire,bad,keys)['quarantine'])==2


def test_preflight_rejects_pilot_version_and_bad_body():
    source,wire,keys,raw=fixture_data();source['analysis_version']='pilot-existing'
    with pytest.raises(ValueError,match='Pilot version'):short_wire(source)
    source,wire,keys,raw=fixture_data();source['reviews'][0]['body']=' '
    with pytest.raises(ValueError,match='Body'):short_wire(source)


def test_first_output_exclusive_even_malformed(tmp_path):
    from src.services.review_batch import save_first_output
    save_first_output(tmp_path,'not valid JSON yet; preserve raw')
    with pytest.raises(FileExistsError):save_first_output(tmp_path,'replacement')
    assert (tmp_path/'first_raw.json').read_text()=='not valid JSON yet; preserve raw'


def test_duplicate_json_keys_quarantined_without_replay(tmp_path):
    source,wire,keys,raw=fixture_data();job=Path(prepare_batches(tmp_path,source['reviews'],source['rules'])[0]['path'])
    (job/'first_raw.json').write_text('{"analysis_version":"a","analysis_version":"b","results":[]}')
    assert prepare_batches(tmp_path,source['reviews'],source['rules'])[0]['status']=='quarantined_no_auto_retry'
    assert 'Duplicate JSON key' in (job/'validation.json').read_text()


def test_targeted_mechanical_retry_preserves_success_and_semantic_uncertainty():
    from src.services.review_batch import isolate_with_retry
    source,wire,keys,raw=fixture_data();missing={**raw,'results':raw['results'][:1]};retry={**raw,'results':raw['results'][1:]}
    report=isolate_with_retry(source,wire,missing,keys,retry)
    assert len(report['validated_candidates'])==2 and not report['quarantine']
    assert report['first_attempt_quarantine'][0]['reason']=='missing/duplicate output'
    assert report['mechanically_recovered']==[raw['results'][1]['document_id']]
    replay=isolate_with_retry(source,wire,missing,keys,raw)
    assert replay['retry_error'] and len(replay['validated_candidates'])==1
    partial=copy.deepcopy(raw);partial['results'][1]['result']='partial';partial['results'][1]['diagnostics']=[dict(code='ambiguous_rule',evidence_id=None,detail='Uncertain')]
    unresolved=isolate_with_retry(source,wire,partial,keys,retry)
    assert unresolved['retry_error'] and len(unresolved['quarantine'])==1


def test_repeated_source_span_text_coalesces_exactly_without_fuzzy_correction():
    source,_,_,_=fixture_data();source['reviews']=source['reviews'][:1];source['reviews'][0]['body']='게임 팬은 조용합니다. 게임 팬은 조용합니다. '
    wire,keys=short_wire(source);spans=wire['reviews'][0]['evidence_spans'];assert spans[0]['text']==spans[1]['text']
    raw={'analysis_version':source['analysis_version'],'results':[{'document_id':source['reviews'][0]['document_id'],'result':'ok','observations':[{'rule_key':'gpu1','observation_text':'게임 팬 소음이 조용했다.','direction':'positive','evidence_ids':[s['evidence_id'] for s in spans]}],'diagnostics':[]}]}
    restored=restore_keys(source,wire,raw,keys)
    assert restored['results'][0]['observations'][0]['evidence_sentences']==[spans[0]['text']]
    assert len(isolate_batch(source,wire,raw,keys)['validated_candidates'])==1


def test_mechanical_retry_can_restore_partial_but_cannot_make_it_importable():
    from src.services.review_batch import isolate_with_retry
    source,wire,keys,raw=fixture_data();first={**raw,'results':raw['results'][:1]}
    partial=copy.deepcopy(raw['results'][1]);partial['result']='partial';partial['diagnostics']=[dict(code='ambiguous_rule',evidence_id=None,detail='Eligibility unresolved')]
    report=isolate_with_retry(source,wire,first,keys,{**raw,'results':[partial]})
    assert report['quarantine'][0]['reason']=='unresolved'
    assert report['quarantine'][0]['canonical_result']['result']=='partial'
    assert len(report['validated_candidates'])==1 and not report['approved_importable']


def test_extra_retry_metadata_remains_strictly_failed_with_attempt_history():
    from src.services.review_batch import isolate_with_retry
    source,wire,keys,raw=fixture_data();first={**raw,'results':raw['results'][:1]};retry={**raw,'results':raw['results'][1:],'retry_metadata':{'reason':'missing'}}
    report=isolate_with_retry(source,wire,first,keys,retry)
    assert not report['mechanically_recovered'] and len(report['validated_candidates'])==1
    assert report['first_attempt_quarantine'][0]['reason']=='missing/duplicate output'
    assert report['retry_attempt_quarantine'][0]['reason']=='batch version/results invalid'


def test_invalid_input_claim_against_valid_preflight_remains_error_not_accepted():
    source,wire,keys,raw=fixture_data();r=raw['results'][1];r.update(result='error',observations=[],diagnostics=[dict(code='invalid_input',evidence_id=None,detail='Claimed invalid analysis version')])
    report=isolate_batch(source,wire,raw,keys)
    q=report['quarantine'][0]
    assert q['reason']=='model_invalid_input_contradicts_preflight'
    assert q['canonical_result']['result']=='error' and not report['approved_importable']
    invalid=copy.deepcopy(source);invalid['rules'][0]['analysis_version']='actually-different'
    with pytest.raises(ValueError,match='version mismatch'):short_wire(invalid)
