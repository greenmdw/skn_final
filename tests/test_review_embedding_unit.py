"""OpenAIEmbedder 단위 테스트 — DB·네트워크 없이 임베딩 계약만 검증한다."""
from __future__ import annotations

import math

import pytest

from src.rag.contracts import EmbeddingError, EmbeddingInputError
from src.rag.embedding import OpenAIEmbedder

pytestmark = pytest.mark.unit


class _FakeDatum:
    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, make_data):
        self._make_data = make_data
        self.calls = []

    def create(self, *, model, input):
        self.calls.append({"model": model, "input": list(input)})
        return _FakeResponse(self._make_data(input))


class _FakeClient:
    def __init__(self, make_data):
        self.embeddings = _FakeEmbeddings(make_data)


class _ExplodingEmbeddings:
    def create(self, *, model, input):
        raise RuntimeError("boom")


class _ExplodingClient:
    def __init__(self):
        self.embeddings = _ExplodingEmbeddings()


def _unit_vector(dimensions: int, nonzero_index: int) -> list[float]:
    vec = [0.0] * dimensions
    vec[nonzero_index] = 1.0
    return vec


def test_embed_orders_results_by_index():
    # The fake server returns results reversed — embed() must reorder by data[i].index,
    # not trust input order.
    def make_data(texts):
        vectors = [_unit_vector(1536, i % 1536) for i in range(len(texts))]
        return [_FakeDatum(index=i, embedding=vectors[i]) for i in reversed(range(len(texts)))]

    client = _FakeClient(make_data)
    embedder = OpenAIEmbedder(client=client, mock=False)
    result = embedder.embed(["first review", "second review", "third review"])
    assert len(result) == 3
    for vec in result:
        assert len(vec) == 1536
    # First result must correspond to index 0's vector (nonzero at position 0).
    assert result[0][0] == pytest.approx(1.0)
    assert client.embeddings.calls[0]["input"] == ["first review", "second review", "third review"]
    # Exactly one request for the whole batch.
    assert len(client.embeddings.calls) == 1


def test_embed_dimension_mismatch_raises_embedding_error():
    def make_data(texts):
        return [_FakeDatum(index=i, embedding=[0.1, 0.2, 0.3]) for i in range(len(texts))]

    embedder = OpenAIEmbedder(client=_FakeClient(make_data), mock=False)
    with pytest.raises(EmbeddingError):
        embedder.embed(["one review long enough"])


def test_embed_zero_vector_raises_embedding_error():
    def make_data(texts):
        return [_FakeDatum(index=i, embedding=[0.0] * 1536) for i in range(len(texts))]

    embedder = OpenAIEmbedder(client=_FakeClient(make_data), mock=False)
    with pytest.raises(EmbeddingError):
        embedder.embed(["one review long enough"])


def test_embed_sdk_exception_wrapped_as_embedding_unavailable():
    embedder = OpenAIEmbedder(client=_ExplodingClient(), mock=False)
    with pytest.raises(EmbeddingError) as exc_info:
        embedder.embed(["one review long enough"])
    assert str(exc_info.value) == "embedding_unavailable"


def test_embed_rejects_blank_input_without_calling_client():
    def make_data(texts):
        raise AssertionError("client must not be called for blank input")

    embedder = OpenAIEmbedder(client=_FakeClient(make_data), mock=False)
    with pytest.raises(EmbeddingError) as exc_info:
        embedder.embed(["   "])
    assert str(exc_info.value) == "embedding_input_invalid"


def test_embed_rejects_blank_among_valid_inputs():
    def make_data(texts):
        raise AssertionError("client must not be called when any input is blank")

    embedder = OpenAIEmbedder(client=_FakeClient(make_data), mock=False)
    with pytest.raises(EmbeddingError):
        embedder.embed(["a real review", ""])


def test_mock_mode_returns_deterministic_nonzero_vectors_without_client():
    def make_data(texts):
        raise AssertionError("mock mode must never call the client")

    embedder = OpenAIEmbedder(client=_FakeClient(make_data), mock=True)
    v1 = embedder.embed(["the fan is very quiet during gaming"])
    v2 = embedder.embed(["the fan is very quiet during gaming"])
    v3 = embedder.embed(["completely different review text"])
    assert len(v1) == 1 and len(v1[0]) == 1536
    assert v1 == v2  # deterministic for the same input
    assert v1 != v3
    norm = math.sqrt(sum(x * x for x in v1[0]))
    assert norm == pytest.approx(1.0)


def test_mock_mode_is_default_when_mock_not_specified():
    # tests/conftest.py defaults MOCK_MODE=1; OpenAIEmbedder() with no args/client must pick
    # that up and never attempt to build a real client.
    embedder = OpenAIEmbedder()
    assert embedder.mock is True
    assert embedder.client is None
    vectors = embedder.embed(["anything"])
    assert len(vectors[0]) == 1536


@pytest.mark.parametrize("param", [None, "input", "input[2]"])
def test_api_bad_input_is_marked_as_a_splittable_error(param):
    import httpx
    from openai import BadRequestError

    response = httpx.Response(400, request=httpx.Request("POST", "https://example.invalid/embeddings"))

    def reject_input(texts):
        raise BadRequestError("invalid input", response=response, body={"param": param})

    embedder = OpenAIEmbedder(client=_FakeClient(reject_input), mock=False)
    with pytest.raises(EmbeddingInputError, match="embedding_input_invalid"):
        embedder.embed(["a valid review", "a review the API rejects"])


@pytest.mark.parametrize("status, param", [(400, "model"), (429, None)])
def test_model_errors_and_rate_limits_are_not_marked_for_document_retries(status, param):
    import httpx
    from openai import BadRequestError, RateLimitError

    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid/embeddings"))
    error = BadRequestError if status == 400 else RateLimitError

    def reject_request(texts):
        raise error("request rejected", response=response, body={"param": param})

    embedder = OpenAIEmbedder(client=_FakeClient(reject_request), mock=False)
    with pytest.raises(EmbeddingError, match="embedding_unavailable") as caught:
        embedder.embed(["a valid review"])
    assert not isinstance(caught.value, EmbeddingInputError)


def test_mock_body_without_tokens_is_a_splittable_input_error():
    with pytest.raises(EmbeddingInputError, match="embedding_zero_vector"):
        OpenAIEmbedder(mock=True).embed(["🙂"])


# ── 채우기 워커: MOCK 가짜 벡터는 테스트 DB에만 (src/workers/review_embedding_batch.py) ──

def _conn_named(dbname):
    """DB 이름만 가진 가짜 커넥션 — execute·cursor가 없어서 가드가 DB에 손대면 AttributeError가 난다."""
    from types import SimpleNamespace

    return SimpleNamespace(info=SimpleNamespace(dbname=dbname), autocommit=True)


@pytest.mark.parametrize("dbname, mock, allow_mock", [
    ("truefit_test_ab12", True, False),     # 테스트 DB에는 가짜 벡터를 써도 된다
    ("truefit", False, False),              # 실제 벡터는 어느 DB든 된다
    ("truefit", True, True),                # --allow-mock으로 명시하면 허용
])
def test_mock_guard_allows(dbname, mock, allow_mock):
    from src.workers.review_embedding_batch import _require_real_vectors_outside_test_db

    _require_real_vectors_outside_test_db(_conn_named(dbname), OpenAIEmbedder(mock=mock), allow_mock)


def test_run_refuses_mock_vectors_for_non_test_db_before_touching_it():
    from src.workers import review_embedding_batch

    with pytest.raises(ValueError, match="--allow-mock"):
        review_embedding_batch.run(_conn_named("truefit"), OpenAIEmbedder(mock=True))


def test_embedder_without_mock_flag_counts_as_real():
    from types import SimpleNamespace

    from src.workers.review_embedding_batch import _require_real_vectors_outside_test_db

    _require_real_vectors_outside_test_db(_conn_named("truefit"), SimpleNamespace(embed=None), False)
