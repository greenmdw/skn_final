"""Review replacement changes only its weighted term, before final rounding."""
from copy import deepcopy

import pytest

from src.dto import Candidate, HardFilterResult, RequirementSpec, ReviewRequirementProfile, ReviewScoreDetail, Slots
from src.engine import stage3b_rank as ranker


def _detail(value, part_type='gpu'):
    return ReviewScoreDetail(profile=ReviewRequirementProfile(
        profile_version='test', analysis_version='test', part_type=part_type,
    ), value=value)


@pytest.mark.parametrize('priority,noise_sensitive', [('performance',False),('value',False),('quiet',False),('performance',True),('quiet',True)])
@pytest.mark.parametrize('verdict', ['Pass','Pending'])
def test_review_delta_uses_actual_weights_and_preserves_other_terms(monkeypatch, priority, noise_sensitive, verdict):
    rules = deepcopy(ranker.load_computer_rules())
    weights, _ = ranker._weights_for({'priority':priority,'noise_sensitive':noise_sensitive}, rules['ranking'])
    cand = Candidate(product_key='gpu',slot='GPU',name='GPU',price=31001,verdict=verdict,
                     specs={'perf_tier':6.3,'power_w':123})
    old = ranker._score(cand,6.5,100000,'GPU',{'tgp_budget_w':200},weights,gap_penalty=.023,
                        review_detail=_detail(.5))
    observed = []
    builtin_round = round

    def capture_round(value, digits=None):
        observed.append((value,digits))
        return builtin_round(value,digits) if digits is not None else builtin_round(value)

    monkeypatch.setattr(ranker,'round',capture_round,raising=False)
    ranker._score(cand,6.5,100000,'GPU',{'tgp_budget_w':200},weights,gap_penalty=.023,
                 review_detail=_detail(.5))
    raw_old = observed[-1][0]
    observed.clear()
    new = ranker._score(cand,6.5,100000,'GPU',{'tgp_budget_w':200},weights,gap_penalty=.023,
                        review_detail=_detail(.525123456))
    raw_new = observed[-1][0]
    assert raw_new-raw_old == pytest.approx(weights['리뷰']*(.525123456-.5),abs=1e-14)
    assert new.score == builtin_round(raw_old+weights['리뷰']*(.525123456-.5),3)
    assert new.breakdown['리뷰'] == .525123456
    assert {k:v for k,v in old.breakdown.items() if k!='리뷰'} == {k:v for k,v in new.breakdown.items() if k!='리뷰'}
    assert new.verdict == old.verdict == verdict
    assert new.specs == old.specs


def test_ram_bonus_pending_and_gap_are_preserved():
    rules = ranker.load_computer_rules()['ranking']
    target = {'capacity_gb_min':16}
    cand = Candidate(product_key='ram',slot='RAM',name='RAM',price=20000,verdict='Pending',
                     specs={'capacity_gb':16,'module_config':'8GB x 2'},review_detail=_detail(.525,'ram'))
    result = ranker._score(cand,None,100000,'RAM',target,gap_penalty=.01)
    expected = sum(rules['weights'].get(k,0)*v for k,v in {
        '가격':.8,'성능':.5,'밸런스':.5,'리뷰':.525,'호환여유':.5,
    }.items()) - ranker.PENDING_SCORE_PENALTY - .01 + ranker._ram_dual_channel_bonus(cand,'RAM',target,rules)
    assert result.score == round(expected,3)


def test_equal_scores_keep_input_order_and_details_in_pool():
    first = Candidate(product_key='first',slot='GPU',name='first',price=10,review_detail=_detail(.5))
    second = first.model_copy(update={'product_key':'second','name':'second'})
    spec = RequirementSpec(list_id='demo',category='computer',mode='build',targets={'GPU':{}},
                           budget={'total':100,'alloc':{'GPU':1}})
    slots = Slots(category='computer',mode='build',objective_text='',values={'purpose':'game'})
    result = ranker.run(HardFilterResult(slots={'GPU':[first,second]}),spec,slots,lambda _:None,require_review_details=True)
    assert [c['product_key'] for c in result.slots['GPU']['pool']] == ['first','second']
    assert all(c['review_detail']['value']==.5 for c in result.slots['GPU']['pool'])
