"""견적 점검 — 우리 추천과 나란히 비교 (CHK-07).

같은 조건으로 추천엔진 2~4단계를 그대로 부르는지, 예산이 없을 때의 처리, 엔진 실패 격리, 카탈로그 비오염을 본다.
합성 카탈로그(CATALOG_SOURCE=mock)로 DB 없이 결정적으로 돈다.
"""
from __future__ import annotations

import os

import pytest

from src.engine.stage3_0_candidates import load_pc_catalog
from src.services import quote_compare
from src.services import quote_review_service as qrs

QUOTE = {"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원", "RAM": "DDR5 16GB 60,000원"}
GAME = {"purpose": "game", "resolution": "QHD_165", "budget_max": 2_000_000}


@pytest.fixture(autouse=True)
def _synthetic_catalog(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")


def compare(quote: dict, conditions: dict | None, **kw) -> dict:
    return qrs.analyze(quote, conditions, **kw)["compare"]


# ── 같은 조건을 만들 수 있을 때만 비교한다 ───────────────────────────────────────────

def test_without_a_purpose_there_is_no_same_condition_recommendation():
    result = compare(QUOTE, {"budget_max": 2_000_000})
    assert result["available"] is False and "용도" in result["reason"] and result["rows"] == []


def test_without_any_budget_the_engine_is_not_run():
    """예산 없이 돌리면 제약이 사라져 GPU 한 개에 수백만 원을 쓰는 구성이 나온다 — 비교하지 않고 이유를 알린다."""
    result = compare({"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti"}, {"purpose": "game"})      # GPU 가격 없음 → 합계 불명
    assert result["available"] is False and "예산" in result["reason"]


def test_a_complete_quote_without_a_budget_uses_its_own_total_as_the_budget():
    result = compare({"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원"}, {"purpose": "game"})
    assert result["available"] is True
    used = result["conditions_used"]
    assert used["budget"] == 750_000 and used["budget_source"] == "quote_total"
    assert any("견적 합계 750,000원을 예산으로" in n for n in result["notes"])


def test_the_budget_condition_wins_over_the_quote_total():
    used = compare(QUOTE, GAME)["conditions_used"]
    assert used["budget"] == 2_000_000 and used["budget_source"] == "condition"


# ── 나란히 놓는다 ─────────────────────────────────────────────────────────────────────

def test_every_slot_of_our_recommendation_is_a_row_with_the_quote_side_when_the_quote_has_it():
    result = compare(QUOTE, GAME)
    rows = {r["part"]: r for r in result["rows"]}
    assert set(rows) == {"CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"}
    assert rows["CPU"]["quote"]["price"] == 250_000 and rows["CPU"]["ours"]["price"] > 0
    assert rows["케이스"]["quote"] is None and "견적에 이 부품이 없습니다" in rows["케이스"]["detail"]
    assert result["summary"]["missing_in_quote"] == 5


def test_the_price_difference_is_quote_minus_ours_in_won_and_percent():
    row = {r["part"]: r for r in compare(QUOTE, GAME)["rows"]}["CPU"]
    assert row["price_diff"] == 250_000 - row["ours"]["price"]
    assert row["price_diff_pct"] == round(row["price_diff"] / row["ours"]["price"] * 100, 1)
    assert row["price_state"] in ("cheaper", "similar", "pricier") and f"{row['price_diff']:+,}원" in row["detail"]


def test_a_quote_part_that_is_the_same_product_as_ours_is_marked_the_same():
    ours_cpu = next(r for r in compare(QUOTE, GAME)["rows"] if r["part"] == "CPU")["ours"]["name"]
    row = next(r for r in compare({"CPU": ours_cpu}, {**GAME, "budget_max": 2_000_000})["rows"] if r["part"] == "CPU")
    assert row["same_product"] is True and "같은 제품" in row["detail"]


def test_the_same_slots_total_only_counts_parts_the_quote_has_a_price_for():
    s = compare(QUOTE, GAME)["summary"]
    assert s["same_slots"] == ["CPU", "GPU", "RAM"]
    assert s["quote_total"] == 250_000 + 500_000 + 60_000
    assert s["diff"] == s["quote_total"] - s["our_total_same_slots"]


def test_our_recommendation_is_listed_with_its_own_compatibility_result():
    ours = compare(QUOTE, GAME)["ours"]
    assert len(ours["items"]) == 8 and ours["total"] == sum(i["price"] for i in ours["items"])
    assert isinstance(ours["link_check"], dict) and "budget" not in ours["incompatible"]


# ── 예산 초과·조건 기록 ──────────────────────────────────────────────────────────────

def test_an_over_budget_recommendation_is_shown_and_flagged_not_hidden():
    result = compare(QUOTE, {**GAME, "budget_max": 300_000})
    assert result["available"] is True and result["summary"]["over_budget"] is True
    assert any("우리 추천도 예산 300,000원을 넘습니다" in n for n in result["notes"])


def test_unspecified_priority_and_resolution_are_disclosed():
    notes = compare(QUOTE, {"purpose": "game", "budget_max": 2_000_000})["notes"]
    assert any("우선순위" in n for n in notes) and any("기본 해상도" in n for n in notes)
    assert not any("우선순위" in n for n in compare(QUOTE, {**GAME, "priority": "value"})["notes"])


@pytest.mark.parametrize("priority", ["performance", "value", "quiet"])
def test_priority_is_passed_to_the_engine(priority):
    result = compare(QUOTE, {**GAME, "priority": priority})
    assert result["available"] and result["conditions_used"]["priority"] == priority


def test_a_different_priority_can_change_what_the_engine_recommends():
    totals = {p: compare(QUOTE, {**GAME, "priority": p})["ours"]["total"] for p in ("performance", "value")}
    assert totals["performance"] >= totals["value"]                   # 성능 우선은 예산을 채우는 쪽, 가성비는 싼 쪽


# ── 격리 ──────────────────────────────────────────────────────────────────────────────

def test_an_engine_failure_does_not_break_the_rest_of_the_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(quote_compare, "_recommend", boom)
    review = qrs.analyze(QUOTE, GAME)
    assert review["compare"]["available"] is False and "계산하지 못했습니다" in review["compare"]["reason"]
    assert review["compat"]["checks"] and review["prices"]["available"] and review["balance"]["available"]


def test_a_catalog_missing_a_slot_is_reported_not_crashed():
    pool = {slot: cands for slot, cands in load_pc_catalog(lambda _m: None).items() if slot != "쿨러"}
    result = compare(QUOTE, GAME, by_slot=pool)
    assert result["available"] is False and "쿨러" in result["reason"]


def test_the_engine_does_not_pollute_the_catalog_used_for_matching():
    pool = load_pc_catalog(lambda _m: None)
    before = {slot: [c.model_dump() for c in cands] for slot, cands in pool.items()}
    compare(QUOTE, GAME, by_slot=pool)
    assert {slot: [c.model_dump() for c in cands] for slot, cands in pool.items()} == before


# ── 저장·조회 (HTTP, 일회용 DB) ──────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")


@pytest.mark.skipif(not DSN, reason="requires disposable test database")
def test_the_comparison_is_saved_with_the_review_and_priority_is_validated():
    from fastapi.testclient import TestClient
    from src.api import app

    with TestClient(app) as client:
        body = {"current_specs": QUOTE, "conditions": {**GAME, "priority": "value"}}
        created = client.post("/pc/reviews", json=body).json()
        assert created["compare"]["available"] is True and created["input"]["conditions"]["priority"] == "value"
        assert client.get(f"/pc/reviews/{created['list_id']}").json()["compare"] == created["compare"]
        bad = client.post("/pc/reviews", json={**body, "conditions": {**GAME, "priority": "가성비"}})
        assert bad.status_code == 422
