"""실시간 검색의 출처 주소는 http(s) 만 — 모델이나 검색 결과가 내놓은 `javascript:` 주소가 저장·표시되지 않는다."""
from __future__ import annotations

import pytest

from src.services import live_spec_lookup as ll


@pytest.mark.parametrize("value, expected", [
    ("https://example.com/a?b=1", "https://example.com/a?b=1"),
    ("  http://shop.example.kr/p/1  ", "http://shop.example.kr/p/1"),
    ("javascript:alert(1)", None), ("JAVASCRIPT:alert(1)", None), ("data:text/html,<script>1</script>", None),
    ("ftp://example.com/x", None), ("//example.com/x", None), ("https://", None), ("https://exa mple.com", None),
    ("", None), (None, None), (123, None),
])
def test_only_http_and_https_addresses_with_a_host_are_kept(value, expected):
    assert ll.safe_http_url(value) == expected


def test_a_result_drops_a_bad_source_url_when_it_is_built():
    assert ll.LiveSpecLookupResult(relevant=True, source_url="javascript:alert(1)").source_url is None
    assert ll.LiveSpecLookupResult(relevant=True, source_url="https://example.com/x").source_url == "https://example.com/x"


def test_a_bad_address_already_in_the_store_is_not_shown_and_a_bad_reference_price_source_is_dropped(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(ll, "LIVE_REFERENCE_PRICE", True)
    row = {"status": "unreviewed", "relevant": True, "supported_fields": {}, "source_url": "javascript:alert(1)",
           "fetched_at": None, "reference_price": 100_000, "reference_price_at": datetime.now(timezone.utc),
           "reference_price_source_url": "javascript:x"}
    outcome = ll._outcome(row, cached=True)
    assert outcome.result.source_url is None and outcome.reference_price == 100_000 and outcome.reference_price_source_url is None
    good = ll._outcome({**row, "reference_price_source_url": "https://shop.example.com/p/1"}, cached=True)
    assert good.reference_price_source_url == "https://shop.example.com/p/1"
