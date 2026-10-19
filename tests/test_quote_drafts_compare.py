"""받은 견적 점검 초안 — 분석 전 비교(BE-05)·교체 미리보기/적용(BE-06)·가격 필드(BE-08)·항목 단위 실시간 검색.

실제(DB) 카탈로그를 쓴다 — 제품 ID가 있어야 "정확한 제품 ID"로 비교·교체할 수 있다. 이미지 인식은 가짜로 바꿔 끼운다."""
from __future__ import annotations

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


# ── 일괄 실시간 검색(재기획 6.8) ──────────────────────────────────────────────────
def _batch_draft(client, monkeypatch, catalog, unknowns=3):
    gpu, _ = _cheapest_two(catalog, "GPU")
    items = [{"category": "GPU", "raw_text": f"{gpu.name} {gpu.price:,}원"}]
    items += [{"category": "CPU", "raw_text": f"정체불명 프로세서 ZX-{n}"} for n in range(unknowns)]
    return _make_draft(client, monkeypatch, items)


def test_batch_lookup_returns_one_state_per_item_and_skips_confirmed_ones(client, monkeypatch, catalog):
    draft = _batch_draft(client, monkeypatch, catalog)
    _fake_lookup(monkeypatch)
    confirmed = _by_cat(draft, "GPU")[0]
    unknown = _by_cat(draft, "CPU")
    ids = [confirmed["id"], "no-such-item"] + [u["id"] for u in unknown]
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/live-lookup-batch", json={"item_ids": ids})
    assert r.status_code == 200, r.text
    body = r.json()
    states = {row["item_id"]: row["state"] for row in body["items"]}
    assert states[confirmed["id"]] == "skipped" and states["no-such-item"] == "skipped"
    assert all(states[u["id"]] == "found" for u in unknown)
    assert (body["found"], body["skipped"], body["not_found"], body["failed"]) == (3, 2, 0, 0)
    assert body["items"][0]["result"]["supported_fields"]["socket"] == "AM5" or any(row["result"] for row in body["items"])


def test_batch_lookup_isolates_a_failing_item_and_reports_not_found(client, monkeypatch, catalog):
    from src.errors import ServiceUnavailable
    from src.services.live_spec_lookup import LiveSpecLookupResult, LookupOutcome

    draft = _batch_draft(client, monkeypatch, catalog)
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)

    def fake(conn, text, *, slot=None, **kw):
        if "ZX-0" in text:
            raise ServiceUnavailable("지금 검색 요청이 몰려 있어요.", code="live_part_lookup_busy")
        found = "ZX-1" in text
        result = LiveSpecLookupResult.model_validate({"relevant": found, "supported_fields": {"socket": "AM5"} if found else {}})
        return LookupOutcome(result=result, fetched_at=datetime(2026, 10, 5, tzinfo=timezone.utc), status="unreviewed", cached=False)

    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta", fake)
    unknown = {u["normalized_name"][-4:]: u["id"] for u in _by_cat(draft, "CPU")}
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/live-lookup-batch", json={"item_ids": list(unknown.values())})
    assert r.status_code == 200, r.text
    states = {row["item_id"]: row for row in r.json()["items"]}
    assert states[unknown["ZX-0"]]["state"] == "failed" and states[unknown["ZX-0"]]["message"]
    assert states[unknown["ZX-1"]]["state"] == "found" and states[unknown["ZX-2"]]["state"] == "not_found"


def test_batch_lookup_enforces_the_item_cap_the_switch_and_ownership(client, monkeypatch, catalog):
    from src.config import LIVE_LOOKUP_BATCH_MAX

    draft = _batch_draft(client, monkeypatch, catalog, unknowns=1)
    _fake_lookup(monkeypatch)
    url = f"/pc/review-drafts/{draft['draft_id']}/live-lookup-batch"
    too_many = client.post(url, json={"item_ids": [f"x{n}" for n in range(LIVE_LOOKUP_BATCH_MAX + 1)]})
    assert too_many.status_code == 422 and too_many.json()["error"]["code"] == "batch_too_large"
    assert client.post(url, json={"item_ids": []}).status_code == 422
    with TestClient(app) as stranger:
        assert stranger.post(url, json={"item_ids": ["x"]}).status_code == 404
    monkeypatch.setattr(live_spec_lookup, "available", lambda: False)
    assert client.post(url, json={"item_ids": ["x"]}).status_code == 503
