"""Deterministic character spans for full community reviews, independent of aspect extraction."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from src import config
from src.engine.peripheral_post_text import plain_text


@dataclass(frozen=True)
class ChunkSettings:
    target: int = 600
    maximum: int = 1000
    overlap: int = 120

    def __post_init__(self):
        if not 0 <= self.overlap < self.target <= self.maximum:
            raise ValueError("chunk settings require 0 <= overlap < target <= maximum")

    @classmethod
    def configured(cls):
        return cls(config.COMMUNITY_REVIEW_CHUNK_TARGET, config.COMMUNITY_REVIEW_CHUNK_MAX,
                   config.COMMUNITY_REVIEW_CHUNK_OVERLAP)


@dataclass(frozen=True)
class Chunk:
    start: int
    text: str

    @property
    def end(self):
        return self.start + len(self.text)


def normalized_body(body: str) -> str:
    return plain_text(body.replace("\r\n", "\n").replace("\r", "\n"))


def split_body(body: str, settings: ChunkSettings | None = None) -> list[Chunk]:
    """Return contiguous slices of normalized_body(body), covering all nonblank text."""
    cfg = settings or ChunkSettings.configured()
    text = normalized_body(body)
    paragraphs = [m.end() for m in re.finditer(r"\n\s*\n", text)]
    sentences = [m.end() for m in re.finditer(r"[.!?。](?!\d)(?:\s+|$)|\n", text)]
    spaces = [m.end() for m in re.finditer(r"\s+", text)]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + cfg.maximum, len(text))
        if end < len(text):
            lower, target = start + cfg.target // 2, start + cfg.target
            for boundaries in (paragraphs, sentences, spaces):
                candidates = [i for i in boundaries if lower < i <= end]
                if candidates:
                    end = min(candidates, key=lambda i: (abs(i - target), i))
                    break
        piece = text[start:end]
        if piece.strip():
            chunks.append(Chunk(start, piece))
        if end == len(text):
            break
        start = max(start + 1, end - cfg.overlap)
    return chunks


def embedding_input(title: str, text: str) -> str:
    return f"제목: {plain_text(title).strip()}\n본문: {text}"


def profile_key(embedder, settings: ChunkSettings | None = None) -> str:
    """Include actual model, mock mode and every input transformation in the index identity."""
    inner = getattr(embedder, "inner", embedder)
    cfg = settings or ChunkSettings.configured()
    fields = {
        "provider": inner.provider, "model": inner.model, "dimensions": inner.dimensions,
        "embedder": inner.profile_key, "mock": bool(inner.mock),
        "normalizer": "community-plain-v1", "chunker": "character-spans-v1",
        "target": cfg.target, "maximum": cfg.maximum, "overlap": cfg.overlap,
        "input": "title-body-v1",
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def chunk_id(post_id: UUID | str, index_key: str, start: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"truefit:community-review:{post_id}:{index_key}:{start}")
