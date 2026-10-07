"""리뷰 embedding 실호출 — 서비스가 기대는 두 가지 성질을 실제 OpenAI로 확인한다.

전부 `llm_live` 마커 — 실제 API를 부른다(비용 발생, 문장 몇 개라 아주 작다). 기본 실행에서는 빠진다.
MOCK_MODE는 건드리지 않고 `OpenAIEmbedder(mock=False)`로 실호출 embedder를 직접 만든다.

1. 같은 문장을 다시 embedding하면 거의 같다 — 리뷰 검색의 저장 벡터 일치 점검 기준(0.95)이
   실제 API의 미세한 비결정성에 걸리지 않는다는 근거.
2. MOCK 해시 벡터와 실제 벡터는 서로 멀다 — 그 점검이 "가짜 벡터로 채운 DB"를 잡아낸다는 근거.

사전 조건: `.env`에 `OPENAI_API_KEY`. 없으면 스킵한다."""
from __future__ import annotations

import pytest

from src import config as cfg
from src.rag.embedding import OpenAIEmbedder
from src.services.review_search import INDEX_CHECK_MIN_SIMILARITY

pytestmark = [
    pytest.mark.llm_live,
    pytest.mark.skipif(not cfg.OPENAI_API_KEY, reason="OPENAI_API_KEY 미설정 — 실호출 불가"),
]

TEXTS = ["팬 소음이 조금 있지만 참을 만해요", "타건감이 쫀득하고 소리도 조용해요", "배송 빠르고 포장 꼼꼼합니다"]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_same_text_reembeds_above_the_index_check_threshold():
    embedder = OpenAIEmbedder(mock=False)
    first = embedder.embed(TEXTS)
    second = embedder.embed(TEXTS)
    assert all(len(vector) == 1536 for vector in first)
    similarities = [_dot(a, b) for a, b in zip(first, second)]
    assert min(similarities) > 0.99 > INDEX_CHECK_MIN_SIMILARITY


def test_mock_vectors_are_far_from_real_ones():
    real = OpenAIEmbedder(mock=False).embed(TEXTS)
    mock = OpenAIEmbedder(mock=True).embed(TEXTS)
    assert max(_dot(a, b) for a, b in zip(real, mock)) < 0.5 < INDEX_CHECK_MIN_SIMILARITY


def test_related_question_is_closer_than_unrelated_review():
    embedder = OpenAIEmbedder(mock=False)
    question, related, unrelated = embedder.embed(["그래픽카드 팬 소음이 심한가요?", TEXTS[0], TEXTS[2]])
    assert _dot(question, related) > _dot(question, unrelated)
