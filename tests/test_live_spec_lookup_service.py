"""3단계 — lookup() 오케스트레이션(검색 → 검증 → 캐시). 일회용 DB가 필요하다.

call_web_search/call_llm은 실제로 부르지 않고 monkeypatch로 바꿔 끼운다 — 기존
test_list_history_http.py의 "LLM 경로는 call_llm을 바꿔 끼워 검사한다"와 같은 패턴.
MOCK_MODE의 범용 가짜 응답({"text": "[MOCK] 일반 응답"})은 구조화 출력 스키마를 안 따라서
이 테스트엔 안 쓴다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg

    from src.services import live_spec_lookup as lsl

    @pytest.fixture()
    def conn():
        c = psycopg.connect(DSN, autocommit=True)
        try:
            yield c
        finally:
            c.close()


_RELEVANT_RAW = {"relevant": True, "supported_fields": {"socket": "AM5", "wattage_w": 65}, "source_url": "https://example.com/a"}
_IRRELEVANT_RAW = {"relevant": False, "supported_fields": {}, "source_url": None}


def test_cache_miss_calls_search_then_llm_and_caches(conn, monkeypatch):
    calls = {"search": 0, "llm": 0}

    def fake_search(query, **kw):
        calls["search"] += 1
        return {"text": "스니펫: AM5 소켓, 65W", "source_url": "https://example.com/a"}

    def fake_llm(prompt, **kw):
        calls["llm"] += 1
        assert "AMD 라이젠9 9999X" in prompt  # 질의가 실제로 프롬프트에 들어갔는지
        return _RELEVANT_RAW

    monkeypatch.setattr(lsl, "call_web_search", fake_search)
    monkeypatch.setattr(lsl, "call_llm", fake_llm)

    result = lsl.lookup(conn, "AMD 라이젠9 9999X", brand="AMD", model="라이젠9 9999X")
    assert result.relevant is True
    assert result.supported_fields.socket == "AM5"
    assert calls == {"search": 1, "llm": 1}


def test_cache_hit_skips_search_and_llm(conn, monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("캐시 히트인데 검색/LLM이 또 호출됨")

    monkeypatch.setattr(lsl, "call_web_search", boom)
    monkeypatch.setattr(lsl, "call_llm", boom)

    from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo
    LiveSpecLookupRepo(conn).upsert(
        query_text=lsl._query_text("Intel Core Ultra 9 999K"), brand="Intel", model="Core Ultra 9 999K",
        relevant=True, supported_fields={"socket": "LGA1851"}, source_url="https://example.com/b")

    result = lsl.lookup(conn, "Intel Core Ultra 9 999K", brand="Intel", model="Core Ultra 9 999K")
    assert result.supported_fields.socket == "LGA1851"


def test_irrelevant_result_is_still_cached_for_next_call(conn, monkeypatch):
    calls = {"n": 0}

    def fake_search(query, **kw):
        return {"text": "전혀 관계없는 내용", "source_url": None}

    def fake_llm(prompt, **kw):
        calls["n"] += 1
        return _IRRELEVANT_RAW

    monkeypatch.setattr(lsl, "call_web_search", fake_search)
    monkeypatch.setattr(lsl, "call_llm", fake_llm)

    first = lsl.lookup(conn, "가짜브랜드 없는모델")
    assert first.relevant is False
    assert first.has_any_field() is False
    assert calls["n"] == 1

    # 두 번째 호출 — 실패 결과도 캐시됐으니 LLM을 또 부르면 안 된다.
    second = lsl.lookup(conn, "가짜브랜드 없는모델")
    assert second.relevant is False
    assert calls["n"] == 1


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
