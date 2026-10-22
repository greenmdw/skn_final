"""부품 사용 가이드 일괄 검색(search_care_guides) — 견적 후처리가 부품마다 따로 임베딩 요청을 보내던 것을 한 번으로 묶는다.

결과는 부품별 search_care_guide 와 같아야 하고(슬롯별 가이드 범위·유사도 정렬), 임베딩 요청은 캐시에 없는 질의만 한 번에 보낸다.
모의 임베딩(해시)으로 돌아 DB·네트워크가 필요 없다.
"""
from __future__ import annotations

import pytest

from src.rag import care_guides

SLOTS = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]


@pytest.fixture
def counted_embed(monkeypatch):
    """_embed 호출을 센다. 질의 캐시는 테스트마다 비운다(문서 임베딩은 미리 만들어 두어 세지 않는다)."""
    care_guides._load_guides()
    monkeypatch.setattr(care_guides, "_query_vectors", {})
    calls: list[list[str]] = []
    real = care_guides._embed

    def counting(texts):
        calls.append(list(texts))
        return real(texts)

    monkeypatch.setattr(care_guides, "_embed", counting)
    return calls


def _requests(suffix: str = "") -> list[tuple[str, str]]:
    return [(f"{slot} 테스트 부품{suffix} 사용 시 확인할 점", slot) for slot in SLOTS]


def test_batch_matches_one_by_one_search_and_sends_one_embedding_request(counted_embed):
    requests = _requests()
    batched = care_guides.search_care_guides(requests, k=1)

    assert counted_embed == [[query for query, _slot in requests]]          # 8개 질의를 한 번에
    counted_embed.clear()
    one_by_one = [care_guides.search_care_guide(query, k=1, slot=slot) for query, slot in requests]
    assert batched == one_by_one
    assert all(len(hits) == 1 and hits[0]["id"] in care_guides.SLOT_GUIDE_IDS[slot]
               for hits, (_query, slot) in zip(batched, requests))


def test_cached_queries_are_not_embedded_again(counted_embed):
    requests = _requests(" 캐시")
    first = care_guides.search_care_guides(requests)
    second = care_guides.search_care_guides(requests)

    assert first == second
    assert len(counted_embed) == 1                                           # 두 번째는 캐시에서
    # 일부만 새 질의면 그것만 보낸다
    mixed = requests[:4] + [("GPU 새 부품 사용 시 확인할 점", "GPU")]
    care_guides.search_care_guides(mixed)
    assert counted_embed[-1] == ["GPU 새 부품 사용 시 확인할 점"]


def test_slots_without_guides_get_empty_results_without_embedding(counted_embed):
    assert care_guides.search_care_guides([("모니터 사용 시 확인할 점", "monitor"), ("키보드", "keyboard")]) == [[], []]
    assert counted_embed == []
    mixed = care_guides.search_care_guides([("모니터", "monitor"), ("CPU 테스트 사용 시 확인할 점", "CPU")])
    assert mixed[0] == [] and len(mixed[1]) == 1
    assert counted_embed == [["CPU 테스트 사용 시 확인할 점"]]
    assert care_guides.search_care_guides([]) == []


def test_openai_client_is_reused_with_explicit_timeout_and_retries(monkeypatch):
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    care_guides._openai_client.cache_clear()
    try:
        assert care_guides._openai_client() is care_guides._openai_client()
        assert len(created) == 1
        assert created[0]["timeout"] == care_guides.CARE_GUIDE_EMBED_TIMEOUT_S
        assert created[0]["max_retries"] == care_guides.CARE_GUIDE_EMBED_MAX_RETRIES
    finally:
        care_guides._openai_client.cache_clear()
