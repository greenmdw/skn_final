"""Review replacement changes only its weighted term (점수는 반올림하지 않는다)."""
from copy import deepcopy

import pytest

from src.dto import Candidate, HardFilterResult, RequirementSpec, ReviewRequirementProfile, ReviewScoreDetail, Slots
from src.engine import stage3b_rank as ranker


def _detail(value, part_type='gpu'):
    return ReviewScoreDetail(profile=ReviewRequirementProfile(
        profile_version='test', analysis_version='test', part_type=part_type,
    ), value=value)


@pytest.mark.parametrize('priority,noise_sensitive', [('performance',False),('value',False),('quiet',False),('performance',True),('quiet',True)])
def test_review_delta_uses_actual_weights_and_preserves_other_terms(priority, noise_sensitive):
    rules = deepcopy(ranker.load_computer_rules())
    weights, _ = ranker._weights_for({'priority':priority,'noise_sensitive':noise_sensitive}, rules['ranking'])
    cand = Candidate(product_key='gpu',slot='GPU',name='GPU',price=31001,
                     specs={'perf_tier':6.3,'power_w':123})
    args = (cand, 100000 * 0.4, 'GPU', weights)
    old = ranker._score(*args, review_detail=_detail(.5))
    new = ranker._score(*args, review_detail=_detail(.525123456))
    # 중간 반올림이 없으므로 리뷰 값 차이가 가중치만큼 그대로 점수 차이가 된다.
    assert new.score - old.score == pytest.approx(weights['리뷰']*(.525123456-.5),abs=1e-14)
    assert new.breakdown['리뷰'] == .525123456
    assert {k:v for k,v in old.breakdown.items() if k!='리뷰'} == {k:v for k,v in new.breakdown.items() if k!='리뷰'}
    assert new.verdict == old.verdict == 'Pass'
    assert new.specs == old.specs


def test_ram_pair_has_no_bonus_and_score_is_the_plain_weighted_sum():
    """정책 §2.5 — 모듈 2개 구성에 별도 가산점이 없고, 가격 축은 구성 가격으로 계산된다."""
    rules = ranker.load_computer_rules()['ranking']
    assert 'ram_dual_channel_bonus' not in rules
    cand = Candidate(product_key='ram',slot='RAM',name='RAM',price=20000,
                     specs={'capacity_gb':16,'module_config':'8GB x 2'},review_detail=_detail(.525,'ram'))
    result = ranker._score(cand,80000.0,'RAM')
    price_axis = 80000 / (80000 + 20000)
    base = sum(rules['weights'][k]*v for k, v in {'가격':price_axis,'성능':.5,'리뷰':.525}.items())
    assert result.score == pytest.approx(base, abs=1e-14)      # S_final = S_base — 감점 없음
    assert result.score_notes == ['neutral:성능']


def test_equal_scores_are_ordered_by_price_then_product_key():
    specs = {'perf_tier':5}
    first = Candidate(product_key='first',slot='GPU',name='first',price=10,specs=specs,review_detail=_detail(.5))
    second = first.model_copy(update={'product_key':'second','name':'second'})
    spec = RequirementSpec(list_id='demo',category='computer',mode='build',targets={'GPU':{}},
                           budget={'total':100,'alloc':{'GPU':1}})
    slots = Slots(category='computer',mode='build',objective_text='',values={'purpose':'game'})
    result = ranker.run(HardFilterResult(slots={'GPU':[second,first]}),spec,slots,lambda _:None,require_review_details=True)
    assert [c['product_key'] for c in result.slots['GPU']['pool']] == ['first','second']
    assert all(c['review_detail']['value']==.5 for c in result.slots['GPU']['pool'])
