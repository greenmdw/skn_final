"""Full-body indexing, independently of review-aspect extraction and scoring."""
from __future__ import annotations

import logging
from collections import Counter
from contextlib import contextmanager
from functools import partial

import psycopg

from src import config
from src.db import get_conn
from src.rag.contracts import EmbeddingError, EmbeddingInputError
from src.rag.embedding import OpenAIEmbedder, validate_vector
from src.repo.community_review_search_repo import CommunityReviewSearchRepo
from src.services.community_review_chunking import ChunkSettings, embedding_input, profile_key, split_body

log = logging.getLogger(__name__)


@contextmanager
def open_repository(profile, *, dsn=None):
    """Each operation releases its connection before the next embedding call."""
    if dsn is None:
        with get_conn() as conn:
            yield CommunityReviewSearchRepo(conn, profile)
    else:
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield CommunityReviewSearchRepo(conn, profile)


def repository_factory(embedder, *, settings=None, dsn=None):
    return partial(open_repository, profile_key(embedder, settings), dsn=dsn)


def notify_changed(conn, post_id):
    if not config.COMMUNITY_REVIEW_SEARCH_ENABLED:
        return
    try:
        with conn.transaction():
            repo = CommunityReviewSearchRepo(conn, profile_key(OpenAIEmbedder()))
            repo.enqueue(post_id, include_examples=config.COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES)
    except Exception as exc:  # a missed notification is repaired by reconciliation
        log.warning("community review index notification failed: post=%s error=%s", post_id, type(exc).__name__)


def dry_run(open_repo, *, settings=None, include_examples=False, only=None):
    counts = Counter()
    with open_repo() as repo:
        rows = repo.inventory()
    for row in rows:
        # Inventory includes all originals; filter target IDs without mutating queue state.
        if only is not None and str(row["id"]) not in {str(x) for x in only}:
            continue
        counts[f"status_{row['status']}"] += 1
        counts["example_documents" if row["is_example"] else "real_documents"] += 1
        chunks = split_body(row["body"], settings) if row["eligible"] else []
        if chunks and (not row["is_example"] or include_examples):
            counts["eligible_documents"] += 1
            counts["estimated_chunks"] += len(chunks)
            counts["indexed_documents" if row["current"] else "unindexed_documents"] += 1
        else:
            counts["excluded_documents"] += 1
    return dict(counts)


def run_once(open_repo, embedder, *, settings=None, include_examples=False, only=None,
             scan=True, rebuild=False, max_posts=None, max_chunks=None, batch_size=None):
    cfg = settings or ChunkSettings.configured()
    max_posts = config.COMMUNITY_REVIEW_INDEX_MAX_POSTS if max_posts is None else max_posts
    max_chunks = config.COMMUNITY_REVIEW_INDEX_MAX_CHUNKS if max_chunks is None else max_chunks
    batch_size = config.COMMUNITY_REVIEW_INDEX_BATCH_SIZE if batch_size is None else batch_size
    if min(max_posts, max_chunks, batch_size, config.COMMUNITY_REVIEW_INDEX_LEASE_SECONDS,
           config.COMMUNITY_REVIEW_INDEX_MAX_ATTEMPTS) < 1:
        raise ValueError("index limits must be positive")
    inner = getattr(embedder, "inner", embedder)
    if include_examples and not config.COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES:
        raise ValueError("example indexing is disabled")
    with open_repo() as repo:
        if inner.mock and "test" not in repo.conn.info.dbname.lower():
            raise ValueError("MOCK community vectors may only be stored in a test database")
        queued = repo.sync(include_examples=include_examples, only=only, force=rebuild) if scan or rebuild else 0
    report = dict(queued=queued, claimed=0, indexed=0, failed=0, deferred=0, chunks=0, batches=0)
    seen = set()
    for _ in range(max_posts):
        with open_repo() as repo:
            claim = repo.claim(include_examples=include_examples, only=only, exclude=seen,
                               max_attempts=config.COMMUNITY_REVIEW_INDEX_MAX_ATTEMPTS,
                               lease_seconds=config.COMMUNITY_REVIEW_INDEX_LEASE_SECONDS,
                               retry_seconds=config.COMMUNITY_REVIEW_INDEX_RETRY_SECONDS)
            if claim is None:
                break
            seen.add(claim["post_id"])
            report["claimed"] += 1
            post = repo.source(claim["post_id"])
            if not post or not post["eligible"] or post["current_key"] != claim["index_key"]:
                repo.enqueue(claim["post_id"], include_examples=include_examples)
                report["deferred"] += 1
                continue
        try:
            chunks = split_body(post["body"], cfg)
            if not chunks:
                raise EmbeddingInputError("empty_text")
            if len(chunks) > max_chunks:
                raise EmbeddingInputError("document_exceeds_chunk_budget")
            if report["chunks"] + len(chunks) > max_chunks:
                with open_repo() as repo:
                    repo.defer(claim)
                report["deferred"] += 1
                break
            vectors = []
            stale = False
            for offset in range(0, len(chunks), batch_size):
                with open_repo() as repo:
                    if not repo.heartbeat(claim):
                        stale = True
                        break
                batch = chunks[offset:offset + batch_size]
                report["batches"] += 1
                report["chunks"] += len(batch)
                # No open_repo()/DB connection is held during the external call.
                values = embedder.embed([embedding_input(post["title"], c.text) for c in batch])
                if len(values) != len(batch):
                    raise EmbeddingError("embedding_count_mismatch")
                vectors.extend(validate_vector(v, config.REVIEW_EMBEDDING_DIMENSIONS) for v in values)
            with open_repo() as repo:
                saved = not stale and repo.finish(claim, chunks, vectors, include_examples=include_examples)
            report["indexed" if saved else "deferred"] += 1
        except Exception as exc:
            # SDK/SQL exceptions can contain review text; only store controlled embedding codes or the class.
            error = str(exc) if isinstance(exc, EmbeddingError) else type(exc).__name__
            with open_repo() as repo:
                repo.fail(claim, error, max_attempts=1 if isinstance(exc, EmbeddingInputError)
                          else config.COMMUNITY_REVIEW_INDEX_MAX_ATTEMPTS)
            report["failed"] += 1
            log.warning("community review indexing failed: post=%s error=%s", post["id"], error)
    return report
