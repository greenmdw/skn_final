"""견적 점검 — 용도 대비 균형 (CHK-06).

기준은 추천엔진 2단계(stage2_requirement)가 조건으로 정한 요구 등급·용량을 그대로 쓴다. 카탈로그와 같은 제품으로
확정된 부품만 판정하고, 조건이 없으면 판단하지 않는다.
"""
from __future__ import annotations

import os

import pytest

from src.dto import Candidate
from src.services import quote_review_service as qrs

# perf_tier·vram 은 카탈로그 스펙 — 이름은 실제 카탈로그와 같은 표기를 쓴다.
POOL = {
    "CPU": [Candidate(product_key="c-low", slot="CPU", name="Intel Core i3-12100F", price=130_000,
                      specs={"socket": "LGA1700", "perf_tier": 4.0}),
            Candidate(product_key="c-mid", slot="CPU", name="AMD Ryzen 5 7600", price=250_000,
                      specs={"socket": "AM5", "perf_tier": 6.0}),
            Candidate(product_key="c-top", slot="CPU", name="AMD Ryzen 9 9950X", price=800_000,
                      specs={"socket": "AM5", "perf_tier": 10.0})],
    "GPU": [Candidate(product_key="g-low", slot="GPU", name="NVIDIA GeForce RTX 3050 6GB", price=250_000,
                      specs={"perf_tier": 3.0, "vram_gb": 6.0}),
            Candidate(product_key="g-mid", slot="GPU", name="NVIDIA GeForce RTX 4060 Ti", price=500_000,
                      specs={"perf_tier": 6.0, "vram_gb": 8.0}),
            Candidate(product_key="g-top", slot="GPU", name="NVIDIA GeForce RTX 5090", price=3_500_000,
                      specs={"perf_tier": 10.0, "vram_gb": 32.0})],
    "RAM": [Candidate(product_key="r-16", slot="RAM", name="삼성전자 DDR5-5600 (16GB)", price=60_000,
                      specs={"mem_type": "DDR5", "capacity_gb": 16, "module_config": "16GB × 1"}),
            Candidate(product_key="r-64", slot="RAM", name="삼성전자 DDR5-6400 (64GB)", price=300_000,
                      specs={"mem_type": "DDR5", "capacity_gb": 64, "module_config": "64GB × 1"})],
    "저장장치": [Candidate(product_key="s1", slot="저장장치", name="Samsung 990 PRO", price=180_000, specs={"capacity_gb": 2000})],
}

GAME_QHD = {"purpose": "game", "resolution": "QHD_165"}       # 요구: GPU 등급 7 · CPU 등급 5 · RAM 16GB · VRAM 12GB
OFFICE = {"purpose": "office"}                                # 요구: GPU 등급 3 · CPU 등급 4 · RAM 16GB · 저장 500GB


def balance(quote: dict, conditions: dict | None) -> dict:
    return qrs.analyze(quote, conditions, by_slot=POOL)["balance"]


def rows(quote: dict, conditions: dict | None) -> dict[tuple[str, str], dict]:
    return {(r["part"], r["aspect"]): r for r in balance(quote, conditions)["rows"]}


# ── 조건이 없으면 판단하지 않는다 ───────────────────────────────────────────────────

def test_without_a_purpose_the_balance_is_not_judged():
    result = balance({"GPU": "RTX 4060 Ti"}, None)
    assert result["available"] is False and "용도" in result["reason"] and result["rows"] == []
    assert balance({"GPU": "RTX 4060 Ti"}, {"budget_max": 1_500_000})["available"] is False   # 예산만으로는 용도를 모른다


# ── 부족 · 충족 · 과함 (2단계 기준) ───────────────────────────────────────────────────

def test_a_gpu_below_the_stage2_tier_for_the_resolution_is_short():
    row = rows({"GPU": "RTX 4060 Ti 8GB"}, GAME_QHD)[("GPU", "성능 등급")]           # 등급 6 < QHD 요구 7
    assert row["state"] == "short" and row["measured"] == 6 and row["target"] == 7
    assert "QHD 165Hz" in row["detail"] and "낮습니다" in row["detail"]


def test_the_same_gpu_is_enough_for_a_lower_resolution():
    assert rows({"GPU": "RTX 4060 Ti"}, {"purpose": "game", "resolution": "FHD_144"})[("GPU", "성능 등급")]["state"] == "ok"


def test_vram_is_checked_against_the_requirement_too():
    row = rows({"GPU": "RTX 4060 Ti"}, GAME_QHD)[("GPU", "VRAM")]                    # 8GB < QHD 요구 12GB
    assert row["state"] == "short" and row["target"] == 12


def test_a_flagship_gpu_for_office_work_is_excessive():
    row = rows({"GPU": "RTX 5090"}, OFFICE)[("GPU", "성능 등급")]
    assert row["state"] == "excess" and "과합니다" in row["detail"]


def test_a_weak_cpu_is_short_and_a_fitting_one_is_ok():
    assert rows({"CPU": "인텔 i3-12100F"}, GAME_QHD)[("CPU", "성능 등급")]["state"] == "short"      # 4 < 5
    assert rows({"CPU": "라이젠 5 7600"}, GAME_QHD)[("CPU", "성능 등급")]["state"] == "ok"


def test_ram_capacity_is_short_below_the_requirement_and_excessive_far_above_it():
    assert rows({"RAM": "삼성전자 DDR5-5600 16GB"}, GAME_QHD)[("RAM", "용량")]["state"] == "ok"
    assert rows({"RAM": "삼성전자 DDR5-6400 64GB"}, GAME_QHD)[("RAM", "용량")]["state"] == "excess"   # 16GB 요구의 4배
    assert rows({"RAM": "삼성전자 DDR5-6400 64GB"}, {"purpose": "creation"})[("RAM", "용량")]["state"] == "ok"   # 창작은 32GB 요구


def test_a_kit_written_as_two_sticks_counts_both_sticks():
    """"16GB x2"는 32GB — 카탈로그의 낱개 16GB 로 읽으면 창작(32GB 요구)에서 부족으로 잘못 나온다."""
    row = rows({"RAM": "삼성전자 DDR5-5600 (16GB) x2"}, {"purpose": "creation"})[("RAM", "용량")]
    assert row["measured"] == 32 and row["state"] == "ok"


def test_storage_capacity_written_in_the_text_is_compared():
    assert rows({"저장장치": "삼성 990 PRO 500GB"}, OFFICE)[("저장장치", "용량")]["state"] == "ok"        # 사무 500GB
    assert rows({"저장장치": "삼성 990 PRO 500GB"}, GAME_QHD)[("저장장치", "용량")]["state"] == "short"    # 게임 1TB


# ── 모르는 것은 모른다고 ─────────────────────────────────────────────────────────────

def test_parts_the_catalog_does_not_know_are_not_judged():
    row = rows({"GPU": "어떤 신형 그래픽카드"}, GAME_QHD)[("GPU", "성능 등급")]
    assert row["state"] == "unknown" and "찾지 못해" in row["detail"]


def test_a_nearest_but_unconfirmed_product_is_not_judged_either():
    row = rows({"CPU": "9950X"}, GAME_QHD)[("CPU", "성능 등급")]          # 짧게 적어 '가장 비슷함'으로만 잡힌다
    assert row["state"] == "unknown"


def test_the_stage2_requirement_is_reported_with_its_basis():
    result = balance({"GPU": "RTX 4060 Ti"}, {"purpose": "game"})            # 해상도를 안 정하면 기본값 기준
    assert result["requirement"]["label"] == "게임 · FHD 144Hz(기본값)"
    assert any("기본 해상도" in n for n in result["notes"]) and any("거친 값" in n for n in result["notes"])


def test_an_unknown_game_is_reported_and_the_resolution_requirement_still_applies():
    result = balance({"GPU": "RTX 4060 Ti"}, {"purpose": "game", "resolution": "FHD_144", "games": ["없는게임"]})
    assert any("없는게임" in n for n in result["notes"])
    assert result["available"] is True


def test_a_heavy_game_raises_the_requirement_like_the_recommendation_engine_does():
    plain = rows({"GPU": "RTX 4060 Ti"}, {"purpose": "game", "resolution": "FHD_144"})[("GPU", "성능 등급")]
    heavy = rows({"GPU": "RTX 4060 Ti"}, {"purpose": "game", "resolution": "FHD_144", "games": ["스타필드"]})[("GPU", "성능 등급")]
    assert plain["target"] == 6 and heavy["target"] == 7 and heavy["state"] == "short"


# ── 예산 ─────────────────────────────────────────────────────────────────────────────

def test_a_quote_over_the_budget_is_flagged_with_the_sum():
    quote = {"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원"}
    row = rows(quote, {**GAME_QHD, "budget_max": 600_000})[("예산", "예산")]
    assert row["state"] == "excess" and "750,000원 > 예산 600,000원" in row["detail"]
    assert "더 큽니다" not in row["detail"]                              # 두 부품 모두 가격이 있어 합계가 확정이다
    partial = rows({"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원", "RAM": "삼성전자 DDR5-5600 16GB"},
                   {**GAME_QHD, "budget_max": 600_000})[("예산", "예산")]
    assert partial["state"] == "excess" and "더 큽니다" in partial["detail"]      # 가격 없는 부품이 있으면 실제 합계는 더 크다


def test_a_complete_quote_within_the_budget_is_ok_and_an_incomplete_one_is_unknown():
    complete = rows({"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti 500,000원"}, {**GAME_QHD, "budget_max": 900_000})
    assert complete[("예산", "예산")]["state"] == "ok"
    incomplete = rows({"CPU": "라이젠 5 7600 250,000원", "GPU": "RTX 4060 Ti"}, {**GAME_QHD, "budget_max": 900_000})
    assert incomplete[("예산", "예산")]["state"] == "unknown"


def test_the_price_share_per_part_is_compared_with_the_stage2_allocation():
    """GPU 에 예산의 40% 를 배분하는 게 기준인데 견적은 CPU 에 몰아 썼다 — GPU 는 부족 투자, CPU 는 과투자."""
    quote = {"CPU": "AMD Ryzen 9 9950X 800,000원", "GPU": "RTX 3050 6GB 250,000원", "RAM": "삼성전자 DDR5-5600 16GB 60,000원",
             "메인보드": "어떤보드 200,000원", "저장장치": "삼성 990 PRO 180,000원", "파워": "어떤파워 100,000원"}
    r = rows(quote, {"purpose": "game", "resolution": "FHD_144"})
    assert r[("GPU", "예산 비중")]["state"] == "short"
    assert r[("CPU", "예산 비중")]["state"] == "excess"


def test_the_price_share_needs_enough_priced_parts():
    r = rows({"CPU": "AMD Ryzen 9 9950X 800,000원", "GPU": "RTX 3050 6GB 250,000원"}, GAME_QHD)
    assert not any(aspect == "예산 비중" for _, aspect in r)


# ── 저장·조회 (HTTP, 일회용 DB) ──────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
db_only = pytest.mark.skipif(not DSN, reason="requires disposable test database")


@db_only
def test_conditions_are_saved_and_kept_when_only_the_quote_is_edited(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    with TestClient(app) as client:
        created = client.post("/pc/reviews", json={
            "current_specs": {"GPU": "RTX 4060 Ti"}, "conditions": {"purpose": "game", "resolution": "QHD_165"}}).json()
        assert created["balance"]["available"] is True and created["input"]["conditions"]["resolution"] == "QHD_165"
        # 견적만 고쳐 다시 보내면(조건 생략) 조건이 유지된다
        kept = client.put(f"/pc/reviews/{created['list_id']}", json={"current_specs": {"GPU": "RTX 4070"}}).json()
        assert kept["input"]["conditions"] == created["input"]["conditions"] and kept["balance"]["available"] is True
        # 빈 조건을 보내면 지워진다
        cleared = client.put(f"/pc/reviews/{created['list_id']}",
                             json={"current_specs": {"GPU": "RTX 4070"}, "conditions": {}}).json()
        assert cleared["balance"]["available"] is False and cleared["input"]["conditions"] == {}
        assert client.get(f"/pc/reviews/{created['list_id']}").json()["balance"] == cleared["balance"]


@db_only
def test_invalid_conditions_are_rejected(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app

    with TestClient(app) as client:
        res = client.post("/pc/reviews", json={"current_specs": {"CPU": "i5-14400F"}, "conditions": {"purpose": "게임"}})
        assert res.status_code == 422


# ── 같은 모델의 용량 변형 ─────────────────────────────────────────────────────────────

def test_a_gpu_vram_variant_written_in_the_text_wins_over_the_catalog_one():
    """카탈로그의 RTX 4060 Ti 는 8GB 인데 견적이 16GB 를 적었다 — 글의 VRAM 으로 판정하고, 다른 변형의 가격은 비교하지 않는다."""
    review = qrs.analyze({"GPU": "RTX 4060 Ti 16GB 560,000원"}, {"purpose": "game", "resolution": "QHD_165"}, by_slot=POOL)
    vram = next(r for r in review["balance"]["rows"] if r["aspect"] == "VRAM")
    assert vram["measured"] == 16 and vram["state"] == "ok"
    price = review["prices"]["rows"][0]
    assert price["state"] == "no_catalog" and "변형" in price["detail"]


def test_a_gpu_text_with_the_same_vram_as_the_catalog_keeps_the_catalog_price():
    price = qrs.analyze({"GPU": "RTX 4060 Ti 8GB 510,000원"}, by_slot=POOL)["prices"]["rows"][0]
    assert price["state"] == "similar" and price["catalog"] == 500_000
