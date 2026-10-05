"""임시 부품 저장소 오케스트레이션(검색 → 검증 → 저장소) — 설계 §9. 일회용 DB가 필요하다.

call_web_search/call_llm은 실제로 부르지 않고 monkeypatch로 바꿔 끼운다 — 기존
test_list_history_http.py의 "LLM 경로는 call_llm을 바꿔 끼워 검사한다"와 같은 패턴.
MOCK_MODE의 범용 가짜 응답({"text": "[MOCK] 일반 응답"})은 구조화 출력 스키마를 안 따라서
이 테스트엔 안 쓴다. 제품명에는 매 실행마다 다른 접미사를 붙인다 — 같은 DB를 다시 써도 이전 행과
부딪치지 않는다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg

    from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo
    from src.services import live_spec_lookup as lsl

    @pytest.fixture()
    def conn():
        c = psycopg.connect(DSN, autocommit=True)
        try:
            yield c
        finally:
            c.close()


@pytest.fixture(autouse=True)
def _fresh_global_limit(monkeypatch):
    from src.auth import ratelimit
    ratelimit.reset_all()                                   # 서비스 전체 검색 한도가 테스트끼리 새지 않게
    monkeypatch.setattr(lsl, "LIVE_LOOKUP_GLOBAL_LIMIT_PER_MIN", 1000)
    yield
    ratelimit.reset_all()


def _name(prefix: str) -> str:
    return f"{prefix} Z{uuid4().hex[:5].upper()}"      # 문자로 시작 — 숫자만이면 상품코드로 보고 키에서 빠진다


_RELEVANT_RAW = {"relevant": True, "supported_fields": {"socket": "AM5", "wattage_w": 65}, "source_url": "https://example.com/a"}
_IRRELEVANT_RAW = {"relevant": False, "supported_fields": {}, "source_url": None}


class _Calls:
    def __init__(self, monkeypatch, raw):
        self.search = self.llm = 0
        self.last_query = self.last_prompt = None
        self.raw = raw

        def fake_search(query, **kw):
            self.search += 1
            self.last_query = query
            return {"text": f"스니펫 {query}", "source_url": "https://example.com/a"}

        def fake_llm(prompt, **kw):
            self.llm += 1
            self.last_prompt = prompt
            return self.raw

        monkeypatch.setattr(lsl, "call_web_search", fake_search)
        monkeypatch.setattr(lsl, "call_llm", fake_llm)


def _seed(conn, key, *, relevant=True, fields=None, status="unreviewed", age_days=0, **extra):
    repo = LiveSpecLookupRepo(conn)
    repo.upsert(lookup_key=key, query_text=f"{key} 정식 스펙", brand=None, model=None, relevant=relevant,
                supported_fields=fields if fields is not None else ({"socket": "LGA1851"} if relevant else {}),
                source_url="https://example.com/seed", **extra)
    if status != "unreviewed":
        conn.execute("UPDATE catalog.live_spec_lookup_cache SET status=%s WHERE lookup_key=%s", (status, key))
    if age_days:
        conn.execute("UPDATE catalog.live_spec_lookup_cache SET fetched_at = now() - make_interval(days => %s), "
                     "reference_price_at = reference_price_at - make_interval(days => %s) WHERE lookup_key=%s",
                     (age_days, age_days, key))


def test_cache_miss_calls_search_then_llm_and_stores(conn, monkeypatch):
    name = _name("AMD 라이젠9 9999X")
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    outcome = lsl.lookup_with_meta(conn, name, brand="AMD", model="라이젠9 9999X")

    assert outcome.result.relevant is True
    assert outcome.result.supported_fields.socket == "AM5"
    assert outcome.cached is False and outcome.status == "unreviewed" and outcome.fetched_at is not None
    assert (calls.search, calls.llm) == (1, 1)
    assert name in calls.last_prompt                                # 이름이 검증 프롬프트에 실제로 들어갔다
    assert calls.last_query == f"{name} 정식 스펙"
    row = LiveSpecLookupRepo(conn).get_fresh(lsl.normalize_lookup_key(name), found_ttl_days=90, notfound_ttl_days=7)
    assert row is not None and row["brand"] == "AMD" and row["query_text"] == f"{name} 정식 스펙"


def test_cache_hit_skips_search_and_llm(conn, monkeypatch):
    name = _name("Intel Core Ultra 9 999K")
    _seed(conn, lsl.normalize_lookup_key(name), fields={"socket": "LGA1851"})
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    outcome = lsl.lookup_with_meta(conn, name)

    assert outcome.result.supported_fields.socket == "LGA1851"
    assert outcome.cached is True
    assert (calls.search, calls.llm) == (0, 0)


def test_irrelevant_result_is_still_stored_for_next_call(conn, monkeypatch):
    name = _name("가짜브랜드 없는모델")
    calls = _Calls(monkeypatch, _IRRELEVANT_RAW)

    first = lsl.lookup(conn, name)
    assert first.relevant is False and first.has_any_field() is False
    assert calls.llm == 1

    second = lsl.lookup(conn, name)           # 실패 결과도 저장했으니 LLM을 또 부르면 안 된다
    assert second.relevant is False
    assert calls.llm == 1


def test_same_product_with_different_quote_price_and_quantity_hits_the_same_row(conn, monkeypatch):
    """견적 원문에 붙은 가격·수량·상품코드·괄호가 달라도 같은 제품이면 재검색하지 않는다(설계 §9.2)."""
    core = _name("박격포 B999M")
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    lsl.lookup(conn, f"MSI {core} 238,000원")
    assert calls.search == 1
    lsl.lookup(conn, f"[MSI] {core} 19996987 250,000원 x2")
    lsl.lookup(conn, f"MSI  {core}  (2개) 25만원")
    assert (calls.search, calls.llm) == (1, 1)


def test_found_result_lives_longer_than_not_found(conn, monkeypatch):
    found_name, missing_name = _name("찾은제품 F100"), _name("못찾은제품 N100")
    _seed(conn, lsl.normalize_lookup_key(found_name), age_days=30)                          # 90일 안 → 적중
    _seed(conn, lsl.normalize_lookup_key(missing_name), relevant=False, age_days=10)        # 7일 지남 → 미스
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    assert lsl.lookup_with_meta(conn, found_name).cached is True
    assert calls.search == 0
    assert lsl.lookup_with_meta(conn, missing_name).cached is False
    assert calls.search == 1


def test_found_result_expires_after_found_ttl(conn, monkeypatch):
    name = _name("오래된제품 O100")
    _seed(conn, lsl.normalize_lookup_key(name), age_days=100)
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    assert lsl.lookup_with_meta(conn, name).cached is False
    assert calls.search == 1


def test_confirmed_row_never_expires_and_is_not_overwritten(conn, monkeypatch):
    name = _name("확인된제품 C100")
    key = lsl.normalize_lookup_key(name)
    _seed(conn, key, fields={"socket": "AM5"}, status="confirmed", age_days=400)
    calls = _Calls(monkeypatch, {"relevant": True, "supported_fields": {"socket": "WRONG"}, "source_url": None})

    outcome = lsl.lookup_with_meta(conn, name)
    assert outcome.cached is True and outcome.status == "confirmed"
    assert outcome.result.supported_fields.socket == "AM5"
    assert calls.search == 0

    # 경쟁 상황 가정: confirmed 행에 upsert 가 와도 덮지 않는다
    row = LiveSpecLookupRepo(conn).upsert(lookup_key=key, query_text="x", brand=None, model=None, relevant=True,
                                          supported_fields={"socket": "WRONG"}, source_url=None)
    assert row["status"] == "confirmed" and row["supported_fields"]["socket"] == "AM5"


def test_rejected_row_is_served_as_not_found_without_researching(conn, monkeypatch):
    name = _name("틀린값제품 R100")
    _seed(conn, lsl.normalize_lookup_key(name), fields={"socket": "AM4"}, status="rejected")
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    outcome = lsl.lookup_with_meta(conn, name)
    assert outcome.status == "rejected" and outcome.cached is True
    assert outcome.result.relevant is False and outcome.result.has_any_field() is False
    assert calls.search == 0


def test_rejected_row_is_researched_after_not_found_ttl_and_returns_to_unreviewed(conn, monkeypatch):
    name = _name("재검색제품 S100")
    key = lsl.normalize_lookup_key(name)
    _seed(conn, key, status="rejected", age_days=10)
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    outcome = lsl.lookup_with_meta(conn, name)
    assert calls.search == 1 and outcome.status == "unreviewed" and outcome.result.supported_fields.socket == "AM5"


def test_empty_name_after_normalization_does_not_search(conn, monkeypatch):
    calls = _Calls(monkeypatch, _RELEVANT_RAW)
    outcome = lsl.lookup_with_meta(conn, "238,000원")
    assert outcome.result.relevant is False
    assert (calls.search, calls.llm) == (0, 0)


# --- 참고가(LIVE_REFERENCE_PRICE) ------------------------------------------------------------


def test_reference_price_is_not_requested_or_stored_when_flag_is_off(conn, monkeypatch):
    name = _name("플래그꺼짐 P100")
    calls = _Calls(monkeypatch, _RELEVANT_RAW)
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", False)

    outcome = lsl.lookup_with_meta(conn, name)
    assert outcome.reference_price is None and "가격" not in calls.last_query
    row = LiveSpecLookupRepo(conn).get_fresh(lsl.normalize_lookup_key(name), found_ttl_days=90, notfound_ttl_days=7)
    assert row["reference_price"] is None and row["reference_price_at"] is None


def test_reference_price_flag_on_stores_valid_price_beside_specs(conn, monkeypatch):
    name = _name("플래그켜짐 P200")
    calls = _Calls(monkeypatch, {**_RELEVANT_RAW, "reference_price": 189000})
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", True)

    outcome = lsl.lookup_with_meta(conn, name)
    assert outcome.reference_price == 189000
    assert outcome.reference_price_source_url == "https://example.com/a" and outcome.reference_price_at is not None
    assert "가격" in calls.last_query                                 # 검색 질의에 가격이 들어간다
    assert outcome.result.supported_fields.socket == "AM5"            # 스펙은 그대로


@pytest.mark.parametrize("bad_price", [5, 99_999_999_999, True, "12만원"])
def test_reference_price_out_of_range_or_wrong_type_is_dropped_by_code(conn, monkeypatch, bad_price):
    calls = _Calls(monkeypatch, {**_RELEVANT_RAW, "reference_price": bad_price})
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", True)
    if isinstance(bad_price, str):
        with pytest.raises(Exception):                                # 스키마(int|None) 검증에서 걸린다
            lsl.lookup_with_meta(conn, _name("가격이상 B100"))
        return
    outcome = lsl.lookup_with_meta(conn, _name("가격이상 B100"))
    assert outcome.reference_price is None and outcome.result.relevant is True
    assert calls.search == 1


def test_reference_price_is_ignored_when_result_is_not_relevant(conn, monkeypatch):
    _Calls(monkeypatch, {"relevant": False, "supported_fields": {}, "source_url": None, "reference_price": 120000})
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", True)
    assert lsl.lookup_with_meta(conn, _name("무관결과 X100")).reference_price is None


def test_reference_price_is_hidden_after_its_own_short_ttl_but_specs_are_kept(conn, monkeypatch):
    name = _name("가격만료 T100")
    key = lsl.normalize_lookup_key(name)
    _seed(conn, key, reference_price=150000, reference_price_source_url="https://example.com/p", age_days=0)
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", True)
    calls = _Calls(monkeypatch, _RELEVANT_RAW)

    fresh = lsl.lookup_with_meta(conn, name)
    assert fresh.reference_price == 150000

    conn.execute("UPDATE catalog.live_spec_lookup_cache SET reference_price_at = now() - interval '5 days' "
                 "WHERE lookup_key=%s", (key,))
    stale = lsl.lookup_with_meta(conn, name)
    assert stale.cached is True and stale.reference_price is None and stale.result.supported_fields.socket == "LGA1851"
    assert calls.search == 0                                          # 가격만 숨기고 재검색은 하지 않는다


def test_reference_price_is_hidden_when_flag_is_turned_off_later(conn, monkeypatch):
    name = _name("플래그해제 Q100")
    _seed(conn, lsl.normalize_lookup_key(name), reference_price=150000, reference_price_source_url=None)
    monkeypatch.setattr(lsl, "LIVE_REFERENCE_PRICE", False)
    assert lsl.lookup_with_meta(conn, name).reference_price is None


# --- 업그레이드 모드 유지 부품(cached_for_kept_parts) -----------------------------------------


def test_cached_for_kept_parts_fills_unverified_slot_from_existing_store(conn):
    """저장소 읽기만 한다(검색·LLM 재호출 없음): 사용자가 pc_check 버튼으로 이미 받아 둔 결과가 있으면
    업그레이드 모드의 '유지 부품' 호환성 계산에도 그대로 쓴다."""
    text = _name("모름브랜드 쿨러 Z1")
    _seed(conn, lsl.normalize_lookup_key(text), fields={"cooling_type": "수랭", "radiator_mm": 240})

    owned = {"쿨러": {"name": text, "specs": {}, "source": "unverified"}}
    lsl.cached_for_kept_parts(conn, owned, {"쿨러": text})

    assert owned["쿨러"]["source"] == "live"
    assert owned["쿨러"]["specs"] == {"cooling_type": "Liquid (AIO)", "radiator_mm": 240}


def test_cached_for_kept_parts_hits_even_when_quote_price_text_differs(conn):
    """버튼을 누를 때의 견적 가격과 업그레이드 때 견적 문구의 가격이 달라도 같은 키로 적중한다."""
    base = _name("모름브랜드 쿨러 Y2")
    _seed(conn, lsl.normalize_lookup_key(f"{base} 39,000원"), fields={"cooling_type": "공랭"})

    owned = {"쿨러": {"name": base, "specs": {}, "source": "unverified"}}
    lsl.cached_for_kept_parts(conn, owned, {"쿨러": f"{base} 45,000원"})
    assert owned["쿨러"]["source"] == "live"


def test_cached_for_kept_parts_ignores_rejected_rows(conn):
    text = _name("거절된제품 쿨러 J3")
    _seed(conn, lsl.normalize_lookup_key(text), fields={"cooling_type": "수랭"}, status="rejected")
    owned = {"쿨러": {"name": text, "specs": {}, "source": "unverified"}}
    lsl.cached_for_kept_parts(conn, owned, {"쿨러": text})
    assert owned["쿨러"]["source"] == "unverified"


def test_cached_for_kept_parts_leaves_unverified_when_nothing_stored(conn):
    text = _name("아무도 안 찾아본 쿨러")
    owned = {"쿨러": {"name": text, "specs": {}, "source": "unverified"}}
    lsl.cached_for_kept_parts(conn, owned, {"쿨러": text})
    assert owned["쿨러"]["source"] == "unverified"


# --- 검토 상태 -------------------------------------------------------------------------------


def test_set_status_by_id_prefix_and_confirm_requires_a_found_row(conn):
    repo = LiveSpecLookupRepo(conn)
    found_key, missing_key = lsl.normalize_lookup_key(_name("검토대상 A")), lsl.normalize_lookup_key(_name("검토대상 B"))
    _seed(conn, found_key)
    _seed(conn, missing_key, relevant=False)
    found_id = conn.execute("SELECT id::text FROM catalog.live_spec_lookup_cache WHERE lookup_key=%s", (found_key,)).fetchone()[0]
    missing_id = conn.execute("SELECT id::text FROM catalog.live_spec_lookup_cache WHERE lookup_key=%s", (missing_key,)).fetchone()[0]

    row = repo.set_status(found_id[:12], "confirmed")
    assert row["status"] == "confirmed" and row["reviewed_at"] is not None
    assert repo.set_status(found_id[:12], "unreviewed")["reviewed_at"] is None
    with pytest.raises(ValueError):
        repo.set_status(missing_id[:12], "confirmed")                   # 못 찾음 행은 확인할 값이 없다
    assert repo.set_status("ffffffff-no-such", "rejected") is None
    with pytest.raises(ValueError):
        repo.set_status(found_id[:12], "bogus")


@pytest.mark.parametrize("live_part_lookup,mock_mode,has_key,expected", [
    (True, False, True, True),
    (False, False, True, False),   # opt-in 꺼짐
    (True, True, True, False),     # MOCK_MODE
    (True, False, False, False),   # 키 없음
])
def test_available_respects_all_gates(monkeypatch, live_part_lookup, mock_mode, has_key, expected):
    monkeypatch.setattr(lsl, "LIVE_PART_LOOKUP", live_part_lookup)
    monkeypatch.setattr(lsl, "MOCK_MODE", mock_mode)
    monkeypatch.setattr(lsl, "OPENAI_API_KEY", "sk-test" if has_key else "")
    monkeypatch.setattr(lsl, "LLM_PROVIDER", "openai")
    assert lsl.available() is expected


# --- 슬롯별 필드 허용 목록 ---------------------------------------------------------------------


def test_fresh_lookup_with_slot_drops_fields_that_do_not_fit_the_part(conn, monkeypatch):
    name = _name("Corsair RMX 필터 R1")
    calls = _Calls(monkeypatch, {"relevant": True, "source_url": "https://example.com/p",
                                 "supported_fields": {"wattage_w": 1000, "cooling_type": "140mm FDB 팬", "form_factor": "ATX"}})

    outcome = lsl.lookup_with_meta(conn, name, slot="파워")

    assert outcome.result.supported_fields.wattage_w == 1000
    assert outcome.result.supported_fields.cooling_type is None        # 파워에는 의미 없는 필드
    assert "부품 종류: 파워" in calls.last_prompt


def test_cached_lookup_is_filtered_by_the_slot_it_is_read_for(conn, monkeypatch):
    name = _name("저장된제품 SSD S1")
    _seed(conn, lsl.normalize_lookup_key(name), fields={"capacity_gb": 1000, "radiator_mm": 240, "interface": "SATA"})
    _Calls(monkeypatch, _RELEVANT_RAW)

    as_ssd = lsl.lookup_with_meta(conn, name, slot="저장장치")
    assert as_ssd.cached is True
    assert as_ssd.result.supported_fields.radiator_mm is None and as_ssd.result.supported_fields.capacity_gb == 1000
    unfiltered = lsl.lookup_with_meta(conn, name)                         # 슬롯을 모르면 거르지 않는다
    assert unfiltered.result.supported_fields.radiator_mm == 240


def test_cached_for_kept_parts_filters_fields_by_slot(conn):
    text = _name("모름브랜드 파워 W5")
    _seed(conn, lsl.normalize_lookup_key(text), fields={"wattage_w": 750, "cooling_type": "120mm 팬"})
    owned = {"파워": {"name": text, "specs": {}, "source": "unverified"}}
    lsl.cached_for_kept_parts(conn, owned, {"파워": text})
    assert owned["파워"]["specs"] == {"wattage_w": 750}


# --- OpenAI 오류 처리 (설계 §10.5-2) -----------------------------------------------------------


def _openai_error(kind):
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    if kind == "rate":
        return openai.RateLimitError("rate limit", response=httpx.Response(429, request=request), body=None)
    if kind == "timeout":
        return openai.APITimeoutError(request=request)
    return openai.APIConnectionError(request=request)


def test_rate_limit_is_retried_once_then_succeeds(conn, monkeypatch):
    monkeypatch.setattr(lsl, "_RATE_LIMIT_RETRY_WAIT_SECONDS", 0)
    state = {"search": 0}

    def flaky_search(query, **kw):
        state["search"] += 1
        if state["search"] == 1:
            raise _openai_error("rate")
        return {"text": f"스니펫 {query}", "source_url": "https://example.com/a"}

    monkeypatch.setattr(lsl, "call_web_search", flaky_search)
    monkeypatch.setattr(lsl, "call_llm", lambda prompt, **kw: _RELEVANT_RAW)

    outcome = lsl.lookup_with_meta(conn, _name("재시도제품 T1"))
    assert outcome.result.relevant is True and state["search"] == 2


@pytest.mark.parametrize("kind", ["rate", "timeout", "connection"])
def test_persistent_openai_failure_becomes_a_busy_503_and_stores_nothing(conn, monkeypatch, kind):
    from src.errors import ServiceUnavailable

    monkeypatch.setattr(lsl, "_RATE_LIMIT_RETRY_WAIT_SECONDS", 0)

    def always_fail(query, **kw):
        raise _openai_error(kind)

    monkeypatch.setattr(lsl, "call_web_search", always_fail)
    name = _name("실패제품 E1")

    with pytest.raises(ServiceUnavailable) as caught:
        lsl.lookup_with_meta(conn, name)
    assert caught.value.code == "live_part_lookup_busy" and "몰려" in caught.value.message
    row = LiveSpecLookupRepo(conn).get_fresh(lsl.normalize_lookup_key(name), found_ttl_days=90, notfound_ttl_days=7)
    assert row is None                                           # 실패를 "못 찾음"으로 저장하지 않는다


def test_rate_limit_in_the_verification_call_is_also_guarded(conn, monkeypatch):
    from src.errors import ServiceUnavailable

    monkeypatch.setattr(lsl, "_RATE_LIMIT_RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(lsl, "call_web_search", lambda q, **kw: {"text": f"스니펫 {q}", "source_url": None})

    def llm_limited(prompt, **kw):
        raise _openai_error("rate")

    monkeypatch.setattr(lsl, "call_llm", llm_limited)
    with pytest.raises(ServiceUnavailable):
        lsl.lookup_with_meta(conn, _name("검증한도 V1"))


def test_unrelated_errors_are_not_swallowed(conn, monkeypatch):
    def broken(query, **kw):
        raise ValueError("스키마 같은 진짜 버그")

    monkeypatch.setattr(lsl, "call_web_search", broken)
    with pytest.raises(ValueError):
        lsl.lookup_with_meta(conn, _name("버그제품 B1"))


def test_snippet_without_the_model_number_is_stored_as_not_found_without_llm(conn, monkeypatch):
    """F01 — 없는 제품이라 일반 글만 잡히면 LLM 검증을 부르지 않고 '못 찾음'으로 저장한다."""
    calls = _Calls(monkeypatch, _RELEVANT_RAW)
    monkeypatch.setattr(lsl, "call_web_search", lambda q, **kw: {"text": "삼성 DRAM DDR5 일반 소개", "source_url": "https://example.com/g"})
    name = f"삼성 DDR5 {uuid4().int % 90000 + 10000}MHz 메모리"
    result = lsl.lookup(conn, name, slot="RAM")
    assert result.relevant is False
    assert calls.llm == 0


def test_global_limit_turns_extra_searches_into_busy_but_cache_hits_still_work(conn, monkeypatch):
    from src.auth import ratelimit
    from src.errors import ServiceUnavailable

    _Calls(monkeypatch, _RELEVANT_RAW)
    monkeypatch.setattr(lsl, "LIVE_LOOKUP_GLOBAL_LIMIT_PER_MIN", 1)
    ratelimit.reset_all()
    first, second = _name("한도 시험 A"), _name("한도 시험 B")
    lsl.lookup(conn, first, slot="CPU")
    with pytest.raises(ServiceUnavailable) as exc:
        lsl.lookup(conn, second, slot="CPU")
    assert exc.value.code == "live_part_lookup_busy"
    assert lsl.lookup(conn, first, slot="CPU").relevant is True           # 저장소 적중은 한도에 안 든다
    ratelimit.reset_all()


def test_quote_analysis_uses_stored_live_values_but_never_searches(conn, monkeypatch):
    """받은 견적 점검 — 사용자가 이미 받아 둔 검색 값은 호환 검사에 쓰고, 점검이 새로 검색하지는 않는다."""
    from src.services import quote_review_service

    cooler = _name("모름브랜드 쿨러 T9")
    specs = {"CPU": "AMD Ryzen 5 5600", "쿨러": f"{cooler} 22,000원", "케이스": "다크플래쉬 DLM21 RGB Mesh"}

    def height_state(review):
        return next(c["state"] for c in review["compat"]["checks"] if c["axis"] == "cooler_height")

    calls = _Calls(monkeypatch, _RELEVANT_RAW)
    before = quote_review_service.analyze(specs, None, conn=conn)
    assert height_state(before) == "unknown"                      # 저장소에 없으면 확인하지 못함

    _seed(conn, lsl.normalize_lookup_key(f"{cooler} 22,000원"), fields={"height_mm": 154, "cooling_type": "공랭"})
    after = quote_review_service.analyze(specs, None, conn=conn)
    assert height_state(after) == "ok"                            # 받아 둔 높이 154mm ≤ 케이스 허용 높이
    assert calls.search == 0 and calls.llm == 0
