"""Stage 5 renders exactly the review details retained by the ranking snapshot."""
from src.dto import BuildItem, BuildResult, RankResult, VerificationResult
from src.engine import stage5_explain as explain


def _candidate(state, p=0, n=0, mixed=0, members=None):
    return {
        "product_key": "selected-product", "product_id": "product-uuid",
        "review_detail": {
            "value": 0.5, "profile": {
                "profile_version": "profile-v", "analysis_version": "analysis-v",
            },
            "contributions": [{
                "aspect_code": "fan_quietness", "context_code": "gaming_load",
                "rule_id": "selected-rule", "aggregate_id": "selected-aggregate",
                "alpha": 0.25, "q": 0.5, "p": p, "n": n, "mixed": mixed,
                "evidence_state": state, "members": members or [],
            }],
        },
    }


def test_review_line_distinguishes_neutral_states_and_uses_real_selected_member():
    cases = [
        (_candidate("balanced", p=2, n=2), "균형"),
        (_candidate("mixed_only", mixed=3), "혼합 방향 관측만 있음"),
        (_candidate("no_observations"), "선택 조건에 관측 없음"),
        (_candidate("selected_rule_missing"), "등록 규칙 없음"),
        (_candidate("product_id_missing"), "상품 식별자 없음"),
    ]
    lines = []
    for candidate, expected in cases:
        line, _evidence, caveat = explain._review_line(candidate)
        assert expected in line
        assert "R=0.500" in line and "확률" in caveat
        lines.append(line)
    assert len(set(lines)) == len(lines)

    member = {
        "observation_id": "chosen-observation", "document_id": "chosen-document",
        "source_code": "fixture-source", "direction": "positive",
        "observation_text": "quiet under gaming load", "evidence_sentences": ["quiet under gaming load"],
    }
    candidate = _candidate("observed", p=1, members=[member])
    _line, evidence, _caveat = explain._review_line(candidate)
    assert evidence == [{
        "kind": "review_aspect_observation", "product_id": "product-uuid",
        "profile_version": "profile-v", "analysis_version": "analysis-v",
        "aspect_code": "fan_quietness", "context_code": "gaming_load",
        "rule_id": "selected-rule", "aggregate_id": "selected-aggregate",
        "observation_id": "chosen-observation", "document_id": "chosen-document",
        "source_code": "fixture-source", "direction": "positive",
        "text": "quiet under gaming load", "evidence_sentences": ["quiet under gaming load"],
    }]


def test_explanation_uses_candidate_from_full_pool_when_outside_top_n(monkeypatch):
    monkeypatch.setattr(explain, "call_llm", lambda *_a, **_k: {
        "headline": "선택 구성", "summary": "조건에 맞춘 구성입니다.",
        "items": [{"slot": "GPU", "reason": "조건에 맞습니다."}], "caveats": [],
    })
    candidate = _candidate("balanced", p=2, n=2, members=[{
        "observation_id": "pool-observation", "document_id": "pool-document",
        "source_code": "fixture", "direction": "positive",
        "observation_text": "pool positive fact", "evidence_sentences": [],
    }])
    rank = RankResult(slots={"GPU": {"ranked": [], "pool": [candidate]}}, weights_used={"리뷰": 0.2})
    build = BuildResult(list_id="list", items=[
        BuildItem(slot="GPU", product_key="selected-product", name="GPU", price=100),
    ], totals={"price": 100}, budget={"max": 200})
    result = explain.run(build, VerificationResult(list_id="list", category="computer", mode="set"),
                         lambda _message: None, rank=rank)
    assert "균형" in result.review_line_by_slot["GPU"]
    assert result.items[0].evidence[0]["observation_id"] == "pool-observation"
    assert result.items[0].evidence[0]["document_id"] == "pool-document"
