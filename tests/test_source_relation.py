"""올린 사진 여러 장의 관계 판정(한 견적의 여러 장 / 서로 다른 견적) — 순수 판정과 분석 차단."""
from __future__ import annotations

from src.engine import source_relation as sr


def _src(*ids, totals=()):
    return [{"id": i, "type": "image", "status": "completed", "quote_total": 2_000_000 if i in totals else None} for i in ids]


def _item(category, name, *sources):
    return {"category": category, "normalized_name": name, "source_ids": list(sources)}


FULL = ("CPU", "GPU", "RAM", "메인보드", "파워")


def test_one_photo_has_nothing_to_judge():
    assert sr.judge(_src("s1"), [_item("CPU", "a", "s1")])["applies"] is False


def test_a_quote_split_across_photos_shows_different_categories_per_photo_and_is_single_with_high_confidence():
    items = [_item("CPU", "i5", "s1"), _item("GPU", "4060", "s1"), _item("RAM", "16GB", "s2"), _item("파워", "600W", "s2")]
    out = sr.judge(_src("s1", "s2", totals=("s1",)), items)
    assert out["applies"] and out["mode"] == "single" and out["confidence"] == "high" and not out["confirmed"]
    assert any("겹치는 부품군이 없어요" in r for r in out["reasons"])


def test_two_full_builds_with_different_parts_and_two_totals_are_separate_with_high_confidence():
    items = [_item(c, f"{c} A", "s1") for c in FULL] + [_item(c, f"{c} B", "s2") for c in FULL]
    out = sr.judge(_src("s1", "s2", totals=("s1", "s2")), items)
    assert out["mode"] == "separate" and out["confidence"] == "high"
    assert any("서로 다른 제품" in r for r in out["reasons"]) and any("총액" in r for r in out["reasons"])


def test_the_same_parts_seen_in_both_photos_mean_one_quote_photographed_twice():
    items = [_item("CPU", "i5", "s1", "s2"), _item("GPU", "4060", "s1", "s2"), _item("RAM", "16GB", "s1")]
    out = sr.judge(_src("s1", "s2"), items)
    assert out["mode"] == "single" and out["confidence"] == "high" and any("같은 부품 2개" in r for r in out["reasons"])


def test_a_single_conflicting_category_alone_is_not_enough_and_asks_the_user():
    items = [_item("CPU", "i5", "s1"), _item("GPU", "4060", "s1"), _item("GPU", "7600", "s2"), _item("메인보드", "B650", "s2")]
    out = sr.judge(_src("s1", "s2"), items)
    assert out["mode"] == "separate" and out["confidence"] == "low"          # 근거가 하나뿐이라 약하다 — 사용자에게 확인을 받는다
    assert len(out["reasons"]) == 1 and "서로 다른 제품" in out["reasons"][0]


def test_the_users_choice_wins_and_is_marked_confirmed():
    items = [_item(c, f"{c} A", "s1") for c in FULL] + [_item(c, f"{c} B", "s2") for c in FULL]
    out = sr.judge(_src("s1", "s2"), items, choice="single")
    assert out == {"applies": True, "mode": "single", "confidence": "high", "confirmed": True,
                   "reasons": ["사용자가 직접 확인했어요."], "doubts": []}
