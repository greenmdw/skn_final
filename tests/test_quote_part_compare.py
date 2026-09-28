"""견적 점검 — 같은 카테고리 부품 비교 (CHK-10).

견적 속 부품 하나를 같은 부품군의 다른 제품과 스펙·가격·리뷰로 나란히, 견적의 나머지 부품과 호환되는지 함께. 조회만 한다.
"""
from __future__ import annotations

import os

import pytest

from src.dto import Candidate
from src.services import quote_alternatives as qa, quote_chat_service as chat, quote_facts
from src.services import quote_review_service as qrs

POOL = {
    "CPU": [
        Candidate(product_key="cpu:amd:ryzen-5-5600x", slot="CPU", name="AMD Ryzen 5 5600X", price=200_000,
                  specs={"socket": "AM4", "perf_tier": 6.0, "tdp_w": 65, "mem_type": "DDR4"}),
        Candidate(product_key="cpu:amd:ryzen-5-7600", slot="CPU", name="AMD Ryzen 5 7600", price=250_000,
                  specs={"socket": "AM5", "perf_tier": 6.0, "tdp_w": 65, "mem_type": "DDR5"}),
        Candidate(product_key="cpu:amd:ryzen-5-5500", slot="CPU", name="AMD Ryzen 5 5500", price=130_000,
                  specs={"socket": "AM4", "perf_tier": 5.0, "tdp_w": 65, "mem_type": "DDR4"}),
        Candidate(product_key="cpu:amd:ryzen-7-5800x3d", slot="CPU", name="AMD Ryzen 7 5800X3D", price=380_000,
                  specs={"socket": "AM4", "perf_tier": 8.0, "tdp_w": 105, "mem_type": "DDR4"}),
    ],
    "GPU": [
        Candidate(product_key="gpu:nvidia:rtx-4060-ti", slot="GPU", name="NVIDIA GeForce RTX 4060 Ti", price=500_000,
                  specs={"perf_tier": 6.0, "vram_gb": 8.0, "power_w": 160, "length_mm": 244}),
        Candidate(product_key="gpu:nvidia:rtx-4070", slot="GPU", name="NVIDIA GeForce RTX 4070", price=700_000,
                  specs={"perf_tier": 7.0, "vram_gb": 12.0, "power_w": 200, "length_mm": 244}),
    ],
}
QUOTE = {"CPU": "라이젠 5 5600X 210,000원", "GPU": "RTX 4060 Ti 520,000원", "메인보드": "MSI PRO B450M 100,000원"}
COND = {"purpose": "game", "resolution": "FHD_144", "budget_max": 1_500_000}


@pytest.fixture(autouse=True)
def _brief(monkeypatch):
    """리뷰 조회는 실제 산출물 파일에 기대지 않게 고정한다."""
    from src.services import review_service
    monkeypatch.setattr(review_service, "review_brief", lambda key: {
        "total_count": 42 if key.endswith("5600x") else None,
        "plain": {"headline": "관측된 리뷰가 있어요." if key.endswith("5600x") else "리뷰 데이터가 없어요.", "points": [], "reason": None}})


@pytest.fixture()
def review() -> dict:
    return qrs.analyze(QUOTE, COND, by_slot=POOL)


# ── 나란히 놓기 ───────────────────────────────────────────────────────────────────────

def test_named_targets_are_compared_with_price_and_spec_differences(review):
    result = qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"])
    assert result["baseline"]["name"] == "AMD Ryzen 5 5600X" and result["baseline"]["price"] == 210_000
    cand = result["candidates"][0]
    assert cand["name"] == "AMD Ryzen 7 5800X3D" and cand["price_delta"] == 380_000 - 210_000
    specs = {r["key"]: r for r in cand["specs"]}
    assert specs["perf_tier"]["diff"] == 2 and specs["tdp_w"]["diff"] == 40
    assert specs["socket"]["baseline"] == specs["socket"]["candidate"] == "AM4" and specs["socket"]["diff"] is None


def test_without_targets_the_direction_picks_the_candidates(review):
    cheaper = qa.compare_parts(review, "CPU", POOL, None, "cheaper")["candidates"]
    assert [c["name"] for c in cheaper] == ["AMD Ryzen 5 5500"]
    better = qa.compare_parts(review, "CPU", POOL, None, "better")["candidates"]
    assert all(c["perf_tier"] > 6 for c in better) and better[0]["name"] == "AMD Ryzen 7 5800X3D"


def test_targets_that_are_not_in_the_catalog_are_reported_not_invented(review):
    result = qa.compare_parts(review, "GPU", POOL, ["RTX 4070", "없는그래픽카드"])
    assert [c["name"] for c in result["candidates"]] == ["NVIDIA GeForce RTX 4070"]
    assert result["unmatched_targets"] == ["없는그래픽카드"]


def test_the_quote_part_itself_is_not_offered_as_its_own_alternative(review):
    names = [c["name"] for c in qa.compare_parts(review, "GPU", POOL, None, None)["candidates"]]
    assert "NVIDIA GeForce RTX 4060 Ti" not in names


# ── 호환 ──────────────────────────────────────────────────────────────────────────────

def test_a_candidate_that_breaks_compatibility_with_the_rest_of_the_quote_is_flagged_with_the_change(review):
    """견적의 보드(B450M = AM4)에 AM5 CPU 후보 — 새로 생기는 확정 비호환과 그 검사 변화가 보인다."""
    cand = qa.compare_parts(review, "CPU", POOL, ["라이젠 5 7600"])["candidates"][0]
    assert cand["incompatible"] == ["socket"]
    change = next(c for c in cand["compat_changes"] if c["axis"] == "socket")
    assert (change["from"], change["to"]) == ("ok", "fail") and "AM5" in change["detail"]


def test_a_compatible_candidate_has_no_new_incompatibility(review):
    cand = qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"])["candidates"][0]
    assert cand["incompatible"] == [] and not any(c["to"] == "fail" for c in cand["compat_changes"])


# ── 리뷰 ──────────────────────────────────────────────────────────────────────────────

def test_reviews_of_both_sides_are_carried_as_the_observed_brief(review):
    result = qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"])
    assert result["baseline"]["review"]["total_count"] == 42
    assert result["candidates"][0]["review"]["headline"] == "리뷰 데이터가 없어요."


def test_a_review_lookup_failure_does_not_break_the_comparison(review, monkeypatch):
    from src.services import review_service

    def boom(_key):
        raise RuntimeError("review store down")

    monkeypatch.setattr(review_service, "review_brief", boom)
    result = qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"])
    assert result["candidates"][0]["review"] is None and result["candidates"][0]["price"] == 380_000


# ── 견적 쪽 부품을 못 알아본 경우 ────────────────────────────────────────────────────────

def test_a_quote_part_the_catalog_does_not_know_is_still_comparable_with_a_note():
    review = qrs.analyze({"CPU": "어떤 무명 CPU 200,000원", "메인보드": "MSI PRO B450M"}, COND, by_slot=POOL)
    result = qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"])
    assert result["baseline"]["confirmed"] is False and "확인되지 않아" in result["note"]
    assert result["candidates"][0]["specs"][0]["baseline"] is None                # 견적 쪽 값은 "정보 없음"


def test_an_unknown_part_group_is_reported(review):
    assert "부품군이 아닙니다" in qa.compare_parts(review, "모니터", POOL)["error"]


# ── 문장·채팅 ─────────────────────────────────────────────────────────────────────────

def test_the_facts_show_only_the_specs_that_differ_and_mark_missing_values(review):
    text = quote_facts.compare_parts(qa.compare_parts(review, "CPU", POOL, ["라이젠 7 5800X3D"]))
    assert "성능 등급: 견적 6 → 8 (+2)" in text and "기본 전력: 견적 65W → 105W (+40)" in text
    assert "소켓" not in text                                     # 같은 값은 줄이지 않는다
    assert "리뷰:" in text


def test_a_spec_or_review_question_about_a_part_routes_to_the_part_comparison():
    assert chat.route("GPU 스펙 비교해줘")[0][0] == "compare_parts"
    assert chat.route("CPU 리뷰는 어때?")[0] == ("compare_parts", {"slot": "CPU", "direction": None, "targets": []})
    assert chat.route("그래픽카드 더 저렴한 걸로 사양 비교해줘")[0][1]["direction"] == "cheaper"


def test_the_chat_can_run_the_part_comparison_with_named_targets(review):
    text = chat.run_fact(review, "compare_parts", {"slot": "GPU", "targets": ["RTX 4070"]}, lambda: POOL)
    assert "RTX 4070" in text and "VRAM" in text


# ── HTTP (일회용 DB) ──────────────────────────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
db_only = pytest.mark.skipif(not DSN, reason="requires disposable test database")


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    with TestClient(app) as c:
        yield c


@db_only
def test_the_endpoint_compares_a_quote_part_and_only_the_owner_can_read_it(client):
    from fastapi.testclient import TestClient
    from src.api import app

    list_id = client.post("/pc/reviews", json={"current_specs": {"CPU": "i5-14400F 250,000원"}, "conditions": COND}).json()["list_id"]
    res = client.get(f"/pc/reviews/{list_id}/parts/CPU/compare", params={"direction": "better"})
    assert res.status_code == 200
    body = res.json()
    assert body["slot"] == "CPU" and body["baseline"]["price"] == 250_000 and len(body["candidates"]) <= 3
    with TestClient(app) as stranger:
        assert stranger.get(f"/pc/reviews/{list_id}/parts/CPU/compare").status_code == 404


@db_only
def test_the_endpoint_validates_the_part_group_and_the_direction(client):
    list_id = client.post("/pc/reviews", json={"current_specs": {"CPU": "i5-14400F"}}).json()["list_id"]
    assert client.get(f"/pc/reviews/{list_id}/parts/모니터/compare").status_code == 422
    assert client.get(f"/pc/reviews/{list_id}/parts/CPU/compare", params={"direction": "fastest"}).status_code == 422


@db_only
def test_the_comparison_does_not_change_the_saved_review(client):
    list_id = client.post("/pc/reviews", json={"current_specs": {"CPU": "i5-14400F 250,000원"}, "conditions": COND}).json()["list_id"]
    before = client.get(f"/pc/reviews/{list_id}").json()
    client.get(f"/pc/reviews/{list_id}/parts/CPU/compare", params={"target": "i7-14700K"})
    assert client.get(f"/pc/reviews/{list_id}").json() == before


# ── 질문 속 제품 이름을 코드가 찾는다 (모델의 오독 방지) ─────────────────────────────────

def test_the_product_named_in_the_question_is_found_in_the_catalog_by_code():
    pool = POOL["CPU"]
    assert chat.extract_targets("CPU 7600 대신 5800X3D 쓰면 뭐가 달라져?", "CPU", pool, "AMD Ryzen 5 7600") == ["AMD Ryzen 7 5800X3D"]
    assert chat.extract_targets("GPU를 RTX 4070이랑 스펙 비교해줘", "GPU", POOL["GPU"], "NVIDIA GeForce RTX 4060 Ti") == ["NVIDIA GeForce RTX 4070"]


def test_the_part_in_the_quote_is_not_returned_as_a_target_and_unknown_models_give_nothing(review=None):
    assert chat.extract_targets("CPU 5600X 비교", "CPU", POOL["CPU"], "AMD Ryzen 5 5600X") == []
    assert chat.extract_targets("CPU 9999X 비교", "CPU", POOL["CPU"], None) == []


def test_the_route_passes_the_named_targets_when_it_can_read_the_catalog(review):
    routed = chat.route("CPU 5800X3D랑 비교해줘", lambda: POOL, review)
    assert routed == [("compare_parts", {"slot": "CPU", "direction": None, "targets": ["AMD Ryzen 7 5800X3D"]})]


def test_a_target_the_model_made_up_is_dropped_before_the_tool_runs():
    """"9600X"를 물었는데 모델이 "7600X"를 넘기면 — 질문에 없는 이름이라 버린다."""
    from src.agent.quote_review_agent import _Session

    session = _Session(fact=lambda *_a: "", user_text="CPU 7600 대신 9600X 쓰면 뭐가 달라져?")
    assert session.grounded_targets(["AMD Ryzen 5 7600X"]) == []
    assert session.grounded_targets(["AMD Ryzen 5 9600X", "Ryzen 5 7600X"]) == ["AMD Ryzen 5 9600X"]
    assert session.grounded_targets(["rtx 4070"]) == []


def test_a_model_name_missing_from_the_catalog_is_reported_instead_of_swapped_for_another_product(review):
    routed = chat.route("CPU 5600X 대신 9999X 쓰면 뭐가 달라져?", lambda: POOL, review)
    assert routed == [("compare_parts", {"slot": "CPU", "direction": None, "targets": ["9999x"]})]
    text = chat.run_fact(review, "compare_parts", routed[0][1], lambda: POOL)
    assert "'9999x'은(는) 카탈로그에서 찾지 못했습니다" in text
