"""추출 정확도 평가 채점(`peripheral_post_eval_metrics`) — 손으로 계산한 작은 입력으로 M1~M13 을 확인한다."""
from __future__ import annotations

import pytest

from src.engine import peripheral_post_eval_metrics as m


def _it(sentence, attr="grip", value="good", status="confirmed", idx=0, reasons=None, side=None):
    return {"sentence": sentence, "product_index": idx, "attribute": attr,
            "direction": None if side else value, "side": side, "status": status, "reasons": reasons or []}


def _g(sentence, attr="grip", value="good", idx=0, **kw):
    base = {"sentence": sentence, "product_index": idx, "experienced": True, "comparison": False,
            "spec_statement": False, "attribute": attr, "direction": value, "side": None}
    base.update(kw)
    return base


GOLD = {
    "P1": {"is_review": True, "has_injection": False, "hand_cm": 19.0, "purposes": ["fps"], "situations": [],
           "items": [_g("그립이 좋다."), _g("클릭이 아쉽다.", "click", "bad"),
                     _g("무게는 63g이다.", "other", None, spec_statement=True),
                     _g("A보다 가볍다.", "weight_feel", None, comparison=True, side="light")]},
    "N1": {"is_review": False, "reason": "question", "has_injection": False, "items": []},
}


def _run(items, **kw):
    base = {"rep": 1, "analyzable": True, "skip_reason": None,
            "author": {"purposes": ["fps"], "situations": [], "hand_size": None, "hand_cm": 19.2}, "items": items}
    base.update(kw)
    return base


def test_perfect_run_scores_one():
    rec = {"P1": {"runs": [_run([_it("그립이 좋다."), _it("클릭이 아쉽다.", "click", "bad")])]},
           "N1": {"runs": [{"rep": 1, "analyzable": False, "skip_reason": "question", "author": {}, "items": []}]}}
    s = m.score(rec, GOLD)["all"]
    assert s["M1"] == 1.0 and s["M2"] == 1.0 and s["M3"] == 1.0 and s["M4"] == 1.0
    assert s["M5"] == 1.0 and s["M6"] == 1.0 and s["M11"] == 1.0 and s["M10_extra_values"] == 0


def test_recall_precision_attribute_and_direction():
    items = [_it("그립이 좋다.", "grip", "bad"),               # 문장 맞고 속성 맞고 방향 틀림
             _it("클릭이 아쉽다.", "wheel", "bad"),              # 문장 맞고 속성 틀림
             _it("처음 보는 문장이다.")]                          # 정답에 없음 → 정밀도 하락
    s = m.score({"P1": {"runs": [_run(items)]}}, GOLD)["all"]
    assert s["M3"] == 1.0                                       # 체감 대상 2개를 모두 문장으로 뽑았다
    assert s["M4"] == pytest.approx(2 / 3)
    assert s["M5"] == 0.5 and s["M6"] == 0.0


def test_exclusion_rule_counts_confirmed_spec_and_comparison():
    items = [_it("그립이 좋다."), _it("무게는 63g이다.", "other", None), _it("A보다 가볍다.", "weight_feel", None, side="light")]
    s = m.score({"P1": {"runs": [_run(items)]}}, GOLD)["all"]
    assert s["M8_spec"] == pytest.approx(1 / 3) and s["M8_comparison"] == pytest.approx(1 / 3)


def test_author_conditions_invented_and_hand_length_tolerance():
    run = _run([_it("그립이 좋다.")])
    run["author"] = {"purposes": ["fps", "office"], "situations": ["mic"], "hand_size": None, "hand_cm": 20.0}
    s = m.score({"P1": {"runs": [run]}}, GOLD)["all"]
    assert s["M10_extra_values"] == 2                            # office, mic 는 정답에 없다
    assert s["M11"] == 0.0                                       # 19.0 vs 20.0 은 ±0.5cm 밖


def test_non_review_misjudged_and_reason():
    rec = {"N1": {"runs": [_run([_it("그립이 좋다.")])]}}      # 사용기가 아닌 글을 사용기로 분석함
    s = m.score(rec, GOLD)["all"]
    assert s["M1"] == 0.0 and s["M2"] == 0.0


def test_reproducibility_is_jaccard_between_runs():
    a = _run([_it("그립이 좋다."), _it("클릭이 아쉽다.", "click", "bad")])
    b = _run([_it("그립이 좋다.")], rep=2)
    assert m.reproducibility({"runs": [a, b]}) == pytest.approx(0.5)
    assert m.reproducibility({"runs": [a]}) is None


def test_gold_free_counts_hallucination_and_errors():
    rec = {"X": {"runs": [_run([_it("a"), _it("b", status="excluded", reasons=["sentence_not_in_body"])]),
                          {"rep": 2, "error": "boom"}]}}
    out = m.gold_free(rec)
    assert out["M9_hallucinated_sentences"] == 1 and out["run_errors"] == 1 and out["raw_items"] == 2


def test_multi_product_attribution():
    gold = {"E1": {"is_review": True, "multi_product": True, "has_injection": False, "items": [
        _g("가볍다.", idx=0), _g("무겁다.", "grip", "bad", idx=1)]}}
    rec = {"E1": {"runs": [_run([_it("가볍다.", idx=0), _it("무겁다.", "grip", "bad", idx=0)])]}}   # 둘째가 제품을 잘못 붙임
    assert m.score(rec, gold)["all"]["M7"] == 0.5
