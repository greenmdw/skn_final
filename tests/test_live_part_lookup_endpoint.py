"""4단계 — pc_check 라우터의 실시간 부품 검색 엔드포인트. 일회용 DB가 필요하다.

live_spec_lookup.available()/lookup()은 monkeypatch로 바꿔 끼운다 — 여기서 실제 검색·LLM을
부르는 건 3단계(test_live_spec_lookup_service.py)에서 이미 했다. 이 테스트는 라우터가
"대응 안 됨" 슬롯만 받아주는지, 비활성화 시 503인지, rate limit이 거는지만 확인한다."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from src.auth import ratelimit
    from src.services import live_spec_lookup


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


def _outcome(result, *, status="unreviewed", cached=False):
    return live_spec_lookup.LookupOutcome(
        result=result, fetched_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc), status=status, cached=cached)


def _review_client_with_unmatched_cpu() -> tuple["TestClient", str]:
    c = TestClient(app)
    r = c.post("/pc/reviews", json={"current_specs": {
        "CPU": "완전히지어낸이상한모델 XYZ999",
        "GPU": "NVIDIA GeForce RTX 5080",  # 실제 카탈로그 제품 — "이미 매칭됨" 테스트용
    }})
    assert r.status_code == 201, r.text
    return c, r.json()["list_id"]


def test_live_lookup_on_unmatched_slot_calls_lookup_with_original_text(monkeypatch):
    c, lid = _review_client_with_unmatched_cpu()

    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    calls = {}

    def fake_lookup(conn, part_text, **kw):
        calls["part_text"] = part_text
        return _outcome(live_spec_lookup.LiveSpecLookupResult.model_validate(
            {"relevant": True, "supported_fields": {"socket": "AM5"}, "source_url": "https://example.com/x"}),
            status="confirmed", cached=True)

    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta", fake_lookup)

    r = c.post(f"/pc/reviews/{lid}/parts/CPU/live-lookup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slot"] == "CPU"
    assert body["relevant"] is True
    assert body["supported_fields"]["socket"] == "AM5"
    assert calls["part_text"] == "완전히지어낸이상한모델 XYZ999"
    # 저장소 메타 — 언제 확인한 값인지, 사람이 확인했는지, 저장소에서 가져왔는지
    assert body["fetched_at"].startswith("2026-10-03T12:00:00")
    assert body["status"] == "confirmed" and body["cached"] is True
    assert body["reference_price"] is None            # 참고가 기능이 꺼져 있으면 항상 비어 있다


def test_live_lookup_on_already_matched_slot_is_rejected(monkeypatch):
    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)

    r = c.post(f"/pc/reviews/{lid}/parts/GPU/live-lookup")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "already_matched"


def test_live_lookup_on_unknown_slot_is_404(monkeypatch):
    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)

    r = c.post(f"/pc/reviews/{lid}/parts/존재안함/live-lookup")
    assert r.status_code == 404, r.text


def test_live_lookup_returns_503_when_feature_unavailable(monkeypatch):
    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: False)

    r = c.post(f"/pc/reviews/{lid}/parts/CPU/live-lookup")
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "live_part_lookup_unavailable"


def test_live_lookup_is_rate_limited_more_strictly_than_plain_pc_check(monkeypatch):
    from src.config import LIVE_PART_LOOKUP_LIMIT_PER_MIN

    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta",
                        lambda conn, part_text, **kw: _outcome(live_spec_lookup.LiveSpecLookupResult(relevant=False)))

    codes = [c.post(f"/pc/reviews/{lid}/parts/CPU/live-lookup").status_code for _ in range(LIVE_PART_LOOKUP_LIMIT_PER_MIN + 2)]
    assert codes[:LIVE_PART_LOOKUP_LIMIT_PER_MIN].count(429) == 0, codes
    assert all(code == 429 for code in codes[LIVE_PART_LOOKUP_LIMIT_PER_MIN:]), codes


def test_live_lookup_busy_is_a_clear_503_with_a_message(monkeypatch):
    from src.errors import ServiceUnavailable

    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)

    def busy(conn, part_text, **kw):
        raise ServiceUnavailable("지금 검색 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요.", code="live_part_lookup_busy")

    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta", busy)
    r = c.post(f"/pc/reviews/{lid}/parts/CPU/live-lookup")
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "live_part_lookup_busy" and "몰려" in r.json()["error"]["message"]


def test_live_lookup_passes_the_slot_to_the_service(monkeypatch):
    c, lid = _review_client_with_unmatched_cpu()
    monkeypatch.setattr(live_spec_lookup, "available", lambda: True)
    seen = {}

    def fake(conn, part_text, **kw):
        seen.update(kw)
        return _outcome(live_spec_lookup.LiveSpecLookupResult(relevant=False))

    monkeypatch.setattr(live_spec_lookup, "lookup_with_meta", fake)
    assert c.post(f"/pc/reviews/{lid}/parts/CPU/live-lookup").status_code == 200
    assert seen.get("slot") == "CPU"
