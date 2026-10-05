"""받은 견적 점검 초안 — 분석 전 비교(BE-05)·교체 미리보기/적용(BE-06)·가격 필드(BE-08)·항목 단위 실시간 검색.

실제(DB) 카탈로그를 쓴다 — 제품 ID가 있어야 "정확한 제품 ID"로 비교·교체할 수 있다. 이미지 인식은 가짜로 바꿔 끼운다."""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.engine.stage3_0_candidates import load_pc_catalog
    from src.services import live_spec_lookup

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _env():
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


@pytest.fixture(scope="module")
def catalog():
    return load_pc_catalog(lambda _msg: None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _make_draft(client, monkeypatch, items: list[dict]) -> dict:
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: items)
    r = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()


def _by_cat(draft, category):
    return [i for i in draft["items"] if i["category"] == category]


def _cheapest_two(catalog, category):
    pool = sorted((c for c in catalog[category] if c.product_id and c.price), key=lambda c: c.price)
    return pool[0], pool[len(pool) // 2]


def _sure(catalog, category, n=0):
    """이름만 적어도 하나로 확정되는 제품 — 같은 이름의 변형이 여럿이면 ambiguous라 제품 ID가 없다."""
    from src.services import quote_draft_service

    pool = sorted((c for c in catalog[category] if c.product_id and c.price), key=lambda c: c.price)
    return [c for c in pool if (it := quote_draft_service._make_item(category, c.name, "s", catalog))["match_status"] == "confirmed"
            and it["matched_product_id"] == c.product_id][n]


def _socket_pair(catalog):
    """소켓이 같은 CPU·메인보드 한 쌍과, 그 소켓이 아닌 CPU 하나."""
    boards = [b for b in catalog["메인보드"] if b.product_id and b.price and b.specs.get("socket")]
    for board in boards:
        same = [c for c in catalog["CPU"] if c.product_id and c.price and c.specs.get("socket") == board.specs["socket"]]
        other = [c for c in catalog["CPU"] if c.product_id and c.price and c.specs.get("socket") not in (None, board.specs["socket"])]
        if same and other:
            return same[0], board, other[0]
    pytest.skip("소켓이 다른 CPU 쌍을 만들 카탈로그가 없다")


# ── BE-08 ────────────────────────────────────────────────────────────────────

def test_analysis_returns_unit_and_line_prices_for_each_item(client, monkeypatch, catalog):
    gpu, _ = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} 2개 {gpu.price * 2 + 5000:,}원"},
                                              {"category": "CPU", "raw_text": "정체불명 프로세서 ZX-1"}])
    body = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()
    rows = {r["category"]: r for r in body["price_rows"]}
    g = rows["GPU"]
    assert g["quantity"] == 2 and g["quote_price_type"] == "line_total"
    assert g["catalog_status"] == "available" and g["catalog_line_total"] == gpu.price * 2
    assert g["catalog_unit_price"] == gpu.price and g["diff_line_total"] == 5000
    assert rows["CPU"]["catalog_status"] == "unmatched" and rows["CPU"]["quote_line_total"] is None
    assert rows["CPU"]["diff_line_total"] is None


# ── BE-05 ────────────────────────────────────────────────────────────────────

def test_comparison_lists_recognized_items_and_recommended_products_with_ids_and_reasons(client, monkeypatch, catalog):
    gpu, other = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"},
                                              {"category": "GPU", "raw_text": f"{other.name} {other.price:,}원"}])
    base, second = _by_cat(draft, "GPU")
    r = client.get(f"/pc/review-drafts/{draft['draft_id']}/categories/GPU/comparison",
                   params={"baseline_item_id": base["id"], "direction": "better"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "GPU" and body["baseline_item_id"] == base["id"]
    assert {c["item_id"] for c in body["recognized"]} == {base["id"], second["id"]}   # 인식한 제품은 모두 나온다
    assert body["recommended"], "추천 후보가 있어야 한다"
    for rec in body["recommended"]:
        assert rec["product_id"] and rec["name"] and rec["reason"]
        assert "image_url" in rec and isinstance(rec["specs"], list)


def test_comparison_with_target_product_ids_returns_only_those(client, monkeypatch, catalog):
    gpu, other = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"}])
    r = client.get(f"/pc/review-drafts/{draft['draft_id']}/categories/GPU/comparison",
                   params={"target_product_id": [other.product_id]})
    assert r.status_code == 200, r.text
    assert [c["product_id"] for c in r.json()["recommended"]] == [other.product_id]


def test_comparison_rejects_unknown_product_too_many_targets_and_wrong_baseline(client, monkeypatch, catalog):
    gpu, _ = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"},
                                              {"category": "CPU", "raw_text": "AMD Ryzen 5 7500F"}])
    url = f"/pc/review-drafts/{draft['draft_id']}/categories/GPU/comparison"
    assert client.get(url, params={"target_product_id": ["not-a-product"]}).status_code == 422
    assert client.get(url, params={"target_product_id": [str(i) for i in range(5)]}).status_code == 422
    cpu_item = _by_cat(draft, "CPU")[0]["id"]
    assert client.get(url, params={"baseline_item_id": cpu_item}).status_code == 422
    assert client.get(f"/pc/review-drafts/{draft['draft_id']}/categories/케이스/comparison").status_code == 400


# ── BE-06 ────────────────────────────────────────────────────────────────────

def test_preview_reports_total_change_and_replaced_items_without_saving(client, monkeypatch, catalog):
    gpu, other = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"}])
    url = f"/pc/review-drafts/{draft['draft_id']}"
    r = client.post(f"{url}/replacements/preview", json={"replacements": [{"category": "GPU", "candidate_product_id": other.product_id}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["before_total"] == gpu.price and body["after_total"] == other.price
    assert body["total_diff"] == other.price - gpu.price
    assert body["replaced_items"][0]["candidate_product_id"] == other.product_id
    assert client.get(url).json()["version"] == 1                          # 조회만 — 초안은 그대로


def test_preview_flags_new_issue_and_the_other_part_that_must_change(client, monkeypatch, catalog):
    cpu, board, other_cpu = _socket_pair(catalog)
    draft = _make_draft(client, monkeypatch, [{"category": "CPU", "raw_text": f"{cpu.name} {cpu.price:,}원"},
                                              {"category": "메인보드", "raw_text": f"{board.name} {board.price:,}원"}])
    body = client.post(f"/pc/review-drafts/{draft['draft_id']}/replacements/preview",
                       json={"replacements": [{"category": "CPU", "candidate_product_id": other_cpu.product_id}]}).json()
    assert any(i["axis"] == "socket" for i in body["new_issues"])
    assert any(r["category"] == "메인보드" for r in body["additional_replacements"])      # 소켓이 바뀌면 보드도 바꿔야 한다
    assert "소켓" in " ".join(r["reason"] for r in body["additional_replacements"])


def test_preview_validates_products_and_duplicate_categories(client, monkeypatch, catalog):
    gpu, other = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"}])
    url = f"/pc/review-drafts/{draft['draft_id']}/replacements/preview"
    assert client.post(url, json={"replacements": [{"category": "GPU", "candidate_product_id": "nope"}]}).status_code == 422
    dup = {"category": "GPU", "candidate_product_id": other.product_id}
    assert client.post(url, json={"replacements": [dup, dup]}).status_code == 422
    assert client.post(url, json={"replacements": []}).status_code == 422
    # 다른 부품군의 제품 ID를 그 부품군 자리에 넣을 수 없다
    cpu = catalog["CPU"][0]
    assert client.post(url, json={"replacements": [{"category": "GPU", "candidate_product_id": cpu.product_id}]}).status_code == 422


def test_apply_replaces_with_the_exact_product_and_analysis_uses_it(client, monkeypatch, catalog):
    gpu, other = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"}])
    url = f"/pc/review-drafts/{draft['draft_id']}"
    r = client.post(f"{url}/replacements/apply", json={
        "expected_version": 1, "replacements": [{"category": "GPU", "candidate_product_id": other.product_id}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2
    picked = next(i for i in body["items"] if i["id"] == body["selected_item_by_category"]["GPU"])
    assert picked["matched_product_id"] == other.product_id and picked["match_status"] == "confirmed"
    assert picked["quote_line_total"] == other.price and picked["user_edited"] is True
    assert len(_by_cat(body, "GPU")) == 2                                   # 원래 항목도 남는다
    assert body["sources"][-1]["type"] == "replacement"
    analysis = client.post(f"{url}/analysis").json()
    assert [i["matched_product_id"] for i in analysis["used_items"]] == [other.product_id]
    stale = client.post(f"{url}/replacements/apply", json={
        "expected_version": 1, "replacements": [{"category": "GPU", "candidate_product_id": gpu.product_id}]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_REVIEW_VERSION"


# ── 항목 단위 실시간 검색 ─────────────────────────────────────────────────────

def _fake_lookup(monkeypatch):
    from src.services.live_spec_lookup import LiveSpecLookupResult, LookupOutcome

    result = LiveSpecLookupResult.model_validate({"relevant": True, "supported_fields": {"socket": "AM5"}, "source_url": "https://example.com/x"})
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta",
                        lambda conn, text, *, slot=None, **kw: LookupOutcome(
                            result=result, fetched_at=datetime(2026, 10, 5, tzinfo=timezone.utc), status="unreviewed", cached=False))


def test_item_live_lookup_works_per_item_and_refuses_confirmed_ones(client, monkeypatch, catalog):
    gpu, _ = _cheapest_two(catalog, "GPU")
    draft = _make_draft(client, monkeypatch, [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"},
                                              {"category": "CPU", "raw_text": "정체불명 프로세서 ZX-1 99,000원"},
                                              {"category": "CPU", "raw_text": "또 다른 정체불명 칩 QQ-2"}])
    _fake_lookup(monkeypatch)
    confirmed = _by_cat(draft, "GPU")[0]
    cpu_a, cpu_b = _by_cat(draft, "CPU")
    url = f"/pc/review-drafts/{draft['draft_id']}/items"
    ok = client.post(f"{url}/{cpu_b['id']}/live-lookup")                       # 같은 부품군의 두 번째 항목도 개별로 검색된다
    assert ok.status_code == 200, ok.text
    assert ok.json()["query"] == cpu_b["normalized_name"] and ok.json()["supported_fields"]["socket"] == "AM5"
    blocked = client.post(f"{url}/{confirmed['id']}/live-lookup")
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "already_matched"
    assert client.post(f"{url}/no-such-item/live-lookup").status_code == 404
    assert cpu_a["id"] != cpu_b["id"]


def test_item_live_lookup_is_503_when_the_feature_is_off(client, monkeypatch, catalog):
    draft = _make_draft(client, monkeypatch, [{"category": "CPU", "raw_text": "정체불명 프로세서 ZX-1"}])
    monkeypatch.setattr(live_spec_lookup, "available", lambda: False)
    item = draft["items"][0]
    assert client.post(f"/pc/review-drafts/{draft['draft_id']}/items/{item['id']}/live-lookup").status_code == 503
