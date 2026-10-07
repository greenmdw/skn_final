"""Explicit Bedrock embedding and offline lexical test baseline."""

from __future__ import annotations
import hashlib
import json
import math
import os
from collections import Counter
from src.rag.contracts import EmbeddingError
from src.rag.text import VERSION, normalize, tokens


def validate_vector(vector, dimensions: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise EmbeddingError("embedding_dimension_mismatch")
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in vector
    ):
        raise EmbeddingError("embedding_not_finite")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise EmbeddingError("embedding_zero_vector")
    return [float(v / norm) for v in vector]


class LocalHashEmbedder:
    """Lexical feature hashing for regression ONLY; not semantic embeddings.
    Never substituted for a failed Bedrock call.
    """

    dimensions = 1024
    provider = "local-test"
    model = "lexical-hash-v1"
    profile_key = f"local-test-lexical-hash-v1-1024-{VERSION}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for token, count in Counter(tokens(text)).items():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vec[index] += (1 if digest[4] & 1 else -1) * (1 + math.log(count))
            result.append(validate_vector(vec, self.dimensions))
        return result


class BedrockEmbedder:
    provider = "bedrock"
    dimensions = 1024

    def __init__(self, *, model=None, region=None, client=None):
        self.model = (
            model or os.getenv("EMBEDDING_MODEL") or "amazon.titan-embed-text-v2:0"
        )
        self.profile_key = f"bedrock-{self.model}-1024-{VERSION}"
        self.client = client
        self.region = region or os.getenv("AWS_REGION") or os.getenv("LLM_REGION")

    def _client(self):
        if self.client is None:
            if not self.region:
                raise EmbeddingError("embedding_region_missing")
            import boto3
            from botocore.config import Config

            self.client = boto3.Session().client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=20,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        return self.client

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            if not text.strip() or len(text) > 12000:
                raise EmbeddingError("embedding_input_invalid")
            try:
                response = self._client().invoke_model(
                    modelId=self.model,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(
                        {
                            "inputText": normalize(text),
                            "dimensions": self.dimensions,
                            "normalize": True,
                            "embeddingTypes": ["float"],
                        }
                    ),
                )
                body = response["body"]
                try:
                    value = json.loads(body.read())
                finally:
                    body.close()
                result.append(validate_vector(value["embedding"], self.dimensions))
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError("embedding_unavailable") from exc
        return result


def _hash_vector(text: str, dimensions: int) -> list[float]:
    """MOCK_MODE 전용 결정적 해시 벡터(LocalHashEmbedder와 같은 방식, 차원만 호출자가 정한다).
    의미 임베딩이 아니다 — 같은 입력엔 항상 같은 벡터를 돌려줘 테스트가 네트워크를 안 타게 한다."""
    vec = [0.0] * dimensions
    for token, count in Counter(tokens(text)).items():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vec[index] += (1 if digest[4] & 1 else -1) * (1 + math.log(count))
    return vec


class OpenAIEmbedder:
    """리뷰 임베딩 백필(src/workers/review_embedding_batch.py) 전용 — OpenAI
    text-embedding-3-small, 1536차원(evidence.review_embedding 컬럼 고정폭과 일치, 0008 합의).

    MOCK_MODE(또는 mock=True)에서는 실제 호출 없이 결정적 해시 벡터를 돌려준다. mock 여부는
    인스턴스 생성 시 한 번 정해지고 호출마다 바뀌지 않는다 — 실제 호출이 실패했을 때 조용히
    mock으로 넘어가는 경로는 없다(그 실패는 그대로 EmbeddingError로 올라간다).
    """

    provider = "openai"

    def __init__(self, *, model: str | None = None, client=None, mock: bool | None = None):
        from src.config import MOCK_MODE, REVIEW_EMBEDDING_DIMENSIONS, REVIEW_EMBEDDING_MODEL

        self.model = model or REVIEW_EMBEDDING_MODEL
        self.dimensions = REVIEW_EMBEDDING_DIMENSIONS
        self.profile_key = f"openai-{self.model}-{self.dimensions}-{VERSION}"
        self.mock = MOCK_MODE if mock is None else mock
        self.client = client

    def _get_client(self):
        if self.client is None:
            from src.config import OPENAI_API_KEY

            if not OPENAI_API_KEY:
                raise EmbeddingError("embedding_unavailable")
            from openai import OpenAI

            self.client = OpenAI(api_key=OPENAI_API_KEY)
        return self.client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingError("embedding_input_invalid")

        if self.mock:
            return [validate_vector(_hash_vector(text, self.dimensions), self.dimensions) for text in texts]

        try:
            response = self._get_client().embeddings.create(model=self.model, input=texts)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("embedding_unavailable") from exc

        # 호출 한 번으로 전체를 요청하고(비용·지연), data[i].index 로 순서를 보장한다 — SDK가
        # 입력 순서대로 돌려줘도 그 보장에 기대지 않는다.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [validate_vector(list(item.embedding), self.dimensions) for item in ordered]


def get_embedder():
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", "bedrock")
    if provider == "bedrock":
        return BedrockEmbedder()
    if provider == "local-test":
        return LocalHashEmbedder()
    raise ValueError("RAG_EMBEDDING_PROVIDER must be bedrock or local-test")


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().embed(texts)
