"""Span invariants and input identities for community full-body retrieval."""
from uuid import uuid4
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src.rag.embedding import OpenAIEmbedder
from src.services.community_review_chunking import (
    ChunkSettings, chunk_id, embedding_input, normalized_body, profile_key, split_body,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("body", [
    "", " \n\t", "짧은 후기입니다.", "가" * 20000, "🙂👍🏽 한글 English 3.14\n" * 350,
    "# 사용 환경\n\n사무실에서 썼습니다.\n\n" * 400 + "마지막에는 절전 복귀 문제가 있었습니다.",
    "| 항목 | 느낌 |\n| --- | --- |\n| 복귀 | 느림 |\n\n![조용하다](image:123)\n\n**본문**입니다.",
])
def test_all_nonblank_characters_are_covered_by_exact_bounded_spans(body):
    text = normalized_body(body)
    chunks = split_body(body)
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start:chunk.end]
        assert 0 < len(chunk.text) <= 1000
        covered.update(range(chunk.start, chunk.end))
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())
    assert all(a.start < b.start and b.start <= a.end for a, b in zip(chunks, chunks[1:]))
    assert chunks == split_body(body)


def test_tail_after_aspect_limit_and_context_overlap_are_preserved():
    body = "일상 사용 기록입니다. " * 450 + "절전 복귀 후에는 화면이 켜지지 않았습니다."
    chunks = split_body(body)
    assert chunks[-1].end == len(normalized_body(body))
    assert "절전 복귀" in chunks[-1].text
    assert chunks[-1].start > 4000
    assert all(a.end - b.start == 120 for a, b in zip(chunks, chunks[1:]))


def test_formatting_image_alt_and_example_notice():
    body = "> 가상 예시 사용기입니다. 실제 구매자가 작성한 후기가 아닙니다.\r\n\r\n![발열 없음](image:x)\r\n\n**복귀**가 느렸습니다."
    text = normalized_body(body)
    assert "가상 예시" in text
    assert "발열 없음" not in text
    assert "복귀가 느렸습니다." in text
    assert "\r" not in text
    assert embedding_input("**제목**", "실제 구절") == "제목: 제목\n본문: 실제 구절"


def test_identity_changes_with_model_mode_and_chunk_settings():
    real, mock = OpenAIEmbedder(mock=False), OpenAIEmbedder(mock=True)
    key = profile_key(mock)
    assert key != profile_key(real)
    assert key != profile_key(OpenAIEmbedder(mock=True, model="another-model"))
    assert key != profile_key(mock, ChunkSettings(500, 900, 100))
    post = uuid4()
    assert chunk_id(post, key, 0) == chunk_id(post, key, 0)
    assert chunk_id(post, key, 0) != chunk_id(post, key, 100)
    assert chunk_id(post, key, 0) != chunk_id(post, "changed", 0)


@pytest.mark.parametrize("args", [(0, 1000, 0), (600, 500, 120), (600, 1000, 600), (600, 1000, -1)])
def test_invalid_limits_are_rejected(args):
    with pytest.raises(ValueError):
        ChunkSettings(*args)


def test_mock_indexing_is_rejected_before_mutating_a_non_test_database():
    from src.services.community_review_search_index import run_once

    repo = SimpleNamespace(conn=SimpleNamespace(info=SimpleNamespace(dbname="truefit")))
    with pytest.raises(ValueError, match="only be stored in a test"):
        run_once(lambda: nullcontext(repo), OpenAIEmbedder(mock=True))


def test_quality_metrics_separate_span_matches_from_negative_false_positives():
    from scripts.eval_community_review_search import relevance, summarize

    label = {"post_id": "post", "start_char": 50, "end_char": 100}
    assert relevance({"document_id": "post", "start_char": 0, "end_char": 80}, [label])
    assert not relevance({"document_id": "other", "start_char": 0, "end_char": 100}, [label])
    assert not relevance({"document_id": "post", "start_char": 0, "end_char": 55}, [label])
    metrics = summarize([
        {"positive": True, "relevant": [False, True], "hits": 2, "seconds": 1, "index_complete": True},
        {"positive": True, "relevant": [], "hits": 0, "seconds": 2, "index_complete": False},
        {"positive": False, "relevant": [False], "hits": 1, "seconds": 3, "index_complete": True},
    ])
    assert metrics["hit_at_3"] == 0.5
    assert metrics["mrr"] == 0.25
    assert metrics["negative_false_positive_rate"] == 1
    assert metrics["incomplete_index_questions"] == 1
