"""E2 — 조건 기반 리뷰 축 문장 정렬 (F-1, 계획서 §3.1).

`config/computer_verification_rules.yaml`의 `explanation.review_focus` 표가 조건(priority 등)
→ 리뷰 축 매핑을 쥐고 있고, `src/engine/review_focus.py`는 그 표를 읽어 **정렬만** 한다 —
점수화·후보 선택에는 쓰지 않는다(결정 0001). DB 불필요.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest
import yaml

from src.config import REVIEW_SUMMARIES_DEMO
from src.engine import review_focus, stage2_requirement

# noctua-nh-d15: top_summaries = [냉각성능, 소음, 설치난이도] (data/review_summaries.json) —
# priority=quiet 매핑([소음, 팬소음, 코일소음, 발열, 쿨링, 냉각성능]) 아래 소음이 냉각성능보다
# 먼저 매치돼야 한다.
_COOLER_KEY = "noctua-nh-d15"


def _cooler_summaries() -> list[dict]:
    rows = json.loads(REVIEW_SUMMARIES_DEMO.read_text(encoding="utf-8"))
    row = next(r for r in rows if r["product_key"] == _COOLER_KEY)
    assert [s["axis"] for s in row["top_summaries"]] == ["냉각성능", "소음", "설치난이도"]
    return row["top_summaries"]


def test_priority_quiet_puts_noise_axis_first():
    ordered = review_focus.order_summaries(_cooler_summaries(), {"priority": "quiet"})
    assert [s["axis"] for s in ordered] == ["소음", "냉각성능", "설치난이도"]
    assert ordered[0]["matched_by"] == "priority:quiet"
    assert ordered[1]["matched_by"] == "priority:quiet"
    assert ordered[2]["matched_by"] is None


def test_no_matching_condition_keeps_original_order():
    original = _cooler_summaries()
    ordered = review_focus.order_summaries(original, {})
    assert [s["axis"] for s in ordered] == [s["axis"] for s in original]
    assert all(s["matched_by"] is None for s in ordered)
    # 원본은 바뀌지 않는다(사본만 matched_by를 얻는다)
    assert all("matched_by" not in s for s in original)


def test_sentiment_does_not_affect_order():
    baseline = [s["axis"] for s in review_focus.order_summaries(_cooler_summaries(), {"priority": "quiet"})]
    flipped = _cooler_summaries()
    for s in flipped:
        s["sentiment"] = "부정" if s["sentiment"] == "긍정" else "긍정"
    flipped_order = [s["axis"] for s in review_focus.order_summaries(flipped, {"priority": "quiet"})]
    assert flipped_order == baseline


def test_focus_axes_priority_over_purpose_dedup_and_order():
    # priority=quiet 과 purpose=game 을 같이 주면, priority 가 먼저 훑고(quiet 목록에 이미 발열이
    # 있음) purpose(game)의 발열은 중복이라 건너뛰고 게임성능만 새로 붙는다.
    axes = review_focus.focus_axes({"priority": "quiet", "purpose": "game"})
    names = [a for a, _ in axes]
    assert names == ["소음", "팬소음", "코일소음", "발열", "쿨링", "냉각성능", "게임성능"]
    by_axis = dict(axes)
    assert by_axis["발열"] == "priority:quiet"   # priority 가 먼저 차지 — purpose 로 덮이지 않음
    assert by_axis["게임성능"] == "purpose:game"


def test_focus_axes_noise_sensitive_bool_condition():
    axes = review_focus.focus_axes({"noise_sensitive": True})
    assert axes == [("소음", "noise_sensitive:true"), ("팬소음", "noise_sensitive:true"),
                    ("코일소음", "noise_sensitive:true")]
    assert review_focus.focus_axes({"noise_sensitive": False}) == []


def test_all_configured_axes_appear_in_corpus_at_least_once():
    """오타 방지 — review_focus 표의 모든 축 이름이 top_summaries[].axis 코퍼스에 실재한다."""
    rows = json.loads(REVIEW_SUMMARIES_DEMO.read_text(encoding="utf-8"))
    corpus_axes = {s["axis"] for r in rows for s in r.get("top_summaries", [])}
    focus_cfg = stage2_requirement.load_computer_rules()["explanation"]["review_focus"]
    configured_axes = {axis for sub in focus_cfg.values() for axes in sub.values() for axis in axes}
    missing = configured_axes - corpus_axes
    assert not missing, f"코퍼스에 없는 축: {missing}"
    assert configured_axes    # 표가 비어있지 않음을 전제로 한다


def test_review_highlights_contract_shape_and_is_synthetic():
    out = review_focus.review_highlights(_COOLER_KEY, {"priority": "quiet"}, limit=3)
    assert out["status"] == "ready"
    assert out["is_synthetic"] is True
    # matched_axes = 실제로 낸 items 중 matched_by가 붙은 축만(순서 유지, 중복 제거) —
    # 설치난이도는 이 상품 문장에 있지만 quiet 표에 없어 매치 안 됐으므로 빠진다.
    assert out["matched_axes"] == ["소음", "냉각성능"]
    assert len(out["items"]) == 3
    assert out["items"][0]["axis"] == "소음"
    assert out["items"][0]["matched_by"] == "priority:quiet"
    expected_fields = {"axis", "sentiment", "text", "source_label", "source_url",
                       "collected_at", "orig_refs", "matched_by"}
    for item in out["items"]:
        assert set(item) == expected_fields


def test_review_highlights_matched_axes_empty_when_no_item_matches():
    """quiet 조건이어도 상품 문장에 quiet 표 축이 하나도 없으면 matched_axes는 빈 리스트이고,
    순서는 조건이 없을 때와 같다(전부 matched_by=None, 원래 순서 유지)."""
    key = "intel-core-i5-14400f"
    rows = json.loads(REVIEW_SUMMARIES_DEMO.read_text(encoding="utf-8"))
    row = next(r for r in rows if r["product_key"] == key)
    axes = [s["axis"] for s in row["top_summaries"]]
    assert axes == ["번들쿨러", "게임성능", "전력효율"]   # 셋 다 quiet 표 축과 겹치지 않는다

    out = review_focus.review_highlights(key, {"priority": "quiet"}, limit=3)
    assert out["status"] == "ready"
    assert out["matched_axes"] == []
    assert [item["axis"] for item in out["items"]] == axes
    assert all(item["matched_by"] is None for item in out["items"])


def test_review_highlights_respects_limit():
    out = review_focus.review_highlights(_COOLER_KEY, {}, limit=1)
    assert len(out["items"]) == 1


def test_review_highlights_matched_axes_excludes_items_cut_by_limit():
    """limit 으로 잘려 나간 매치 항목의 축은 matched_axes 에 넣지 않는다."""
    out = review_focus.review_highlights(_COOLER_KEY, {"priority": "quiet"}, limit=1)
    assert [item["axis"] for item in out["items"]] == ["소음"]
    assert out["matched_axes"] == ["소음"]   # 냉각성능은 매치됐지만 limit=1 로 안 나갔으니 제외


def test_review_highlights_unknown_product_is_none():
    out = review_focus.review_highlights("no-such-product-xyz", {"priority": "quiet"})
    assert out == {"status": "none", "is_synthetic": True, "matched_axes": [], "items": []}


def test_review_highlights_matches_slug_like_candidate_keys():
    """원문 그대로는 못 찾아도, 소문자·공백→하이픈 슬러그로는 찾는다 — review_service.candidate_keys
    와 같은 매칭 방식(원 키 우선 시도 후 슬러그로 재시도)."""
    out = review_focus.review_highlights("Noctua NH-D15", {})
    assert out["status"] == "ready"
    assert out["items"][0]["axis"] == "냉각성능"   # 조건 없음 → 원래 순서(첫 항목)


# ── 로드 검증 (stage2_requirement._load_computer_rules) ──────────────────────

def _dump_with_review_focus(tmp_path, review_focus_value, name="bad.yaml"):
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules.setdefault("explanation", {})["review_focus"] = review_focus_value
    path = tmp_path / name
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_load_rejects_unknown_top_level_key(tmp_path):
    path = _dump_with_review_focus(tmp_path, {"unknown_condition": {"quiet": ["소음"]}})
    with pytest.raises(stage2_requirement.RequirementRuleError, match="리뷰 축 정렬"):
        stage2_requirement.load_computer_rules(path)


def test_load_rejects_value_outside_enum(tmp_path):
    # priority 의 slot_schema enum 은 performance/value/quiet 뿐 — "silent" 은 없다
    path = _dump_with_review_focus(tmp_path, {"priority": {"silent": ["소음"]}})
    with pytest.raises(stage2_requirement.RequirementRuleError, match="리뷰 축 정렬"):
        stage2_requirement.load_computer_rules(path)


def test_load_rejects_empty_axis_list(tmp_path):
    path = _dump_with_review_focus(tmp_path, {"priority": {"quiet": []}})
    with pytest.raises(stage2_requirement.RequirementRuleError, match="리뷰 축 정렬"):
        stage2_requirement.load_computer_rules(path)


def test_load_accepts_missing_review_focus_section(tmp_path):
    """선택 절 — explanation 전체 또는 review_focus 만 없어도 통과한다."""
    rules = deepcopy(stage2_requirement.load_computer_rules())
    rules.pop("explanation", None)
    path = tmp_path / "no_explanation.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    loaded = stage2_requirement.load_computer_rules(path)
    assert "explanation" not in loaded
