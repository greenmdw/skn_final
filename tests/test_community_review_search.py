"""Real PostgreSQL/HTTP lifecycle tests; embeddings are offline test vectors."""
from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from review_search_seed import seeded_reviews
from src import config
from src.api import app
from src.rag.contracts import EmbeddingError
from src.rag.embedding import OpenAIEmbedder
from src.services import community_review_search_index as indexing, review_search
from src.services.community_review_chunking import embedding_input, normalized_body, split_body

pytestmark = pytest.mark.db


@pytest.fixture
def env(monkeypatch):
    from src.routers import community, reviews

    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES", False)
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_MIN_SIMILARITY", -1)
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_INDEX_RETRY_SECONDS", 0)
    monkeypatch.setattr(community, "COMMUNITY_POST_LIMIT_PER_MIN", 1000)
    monkeypatch.setattr(reviews, "REVIEW_SEARCH_LIMIT_PER_MIN", 1000)
    embedder = OpenAIEmbedder(mock=True)
    monkeypatch.setattr(review_search, "_default_embedder", review_search.CachedEmbedder(embedder))
    client = TestClient(app)
    user = client.post("/auth/signup", json={"email": f"chunks-{uuid4()}@example.test", "password": "abcd1234",
        "display_name": "사용기검색", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert user.status_code == 201, user.text
    with seeded_reviews(os.environ["DATABASE_URL"]) as seed:
        posts = []
        product = seed.product()
        factory = indexing.repository_factory(embedder, dsn=os.environ["DATABASE_URL"])

        def post(body="절전 복귀 때 화면이 켜지지 않았습니다.", *, products=None, **extra):
            response = client.post("/community/posts", json={"board_type": "review", "title": "한 달 사용기",
                "body": body, "publish": True, "products": [
                    {"product_id": str(pid), "product_kind": "GPU"} for pid in (products or [product])], **extra})
            assert response.status_code == 201, response.text
            pid = UUID(response.json()["id"])
            posts.append(pid)
            return pid

        def run(**kwargs):
            return indexing.run_once(factory, embedder, only=set(posts), **kwargs)

        def search(*, products=None, **extra):
            return client.get("/reviews/search", params={"version": 2, "sources": "community",
                "product_id": [str(x) for x in (products or [product])], "q": "절전 복귀 화면", **extra})

        yield SimpleNamespace(client=client, conn=seed.conn, seed=seed, embedder=embedder, factory=factory,
                              product=product, posts=posts, post=post, run=run, search=search)
        if posts:
            seed.conn.execute("DELETE FROM community.post WHERE id=ANY(%s::uuid[])", (posts,))


def group(response):
    assert response.status_code == 200, response.text
    return response.json()["products"][0]["sources"]["community"]


def state(env, post):
    return env.conn.execute("SELECT status, attempts, claim_token, index_key FROM evidence.community_review_search_document WHERE post_id=%s", (post,)).fetchone()


def test_two_tables_have_exact_minimum_columns(env):
    for table, expected in {
        "community_review_search_document": ["post_id", "index_key", "status", "attempts", "last_error", "claim_token", "updated_at"],
        "community_review_search_chunk": ["id", "post_id", "start_char", "text", "embedding"],
    }.items():
        actual = env.conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='evidence' AND table_name=%s ORDER BY ordinal_position", (table,)).fetchall()
        assert [r[0] for r in actual] == expected


def test_api_searches_tail_and_citations_without_changing_v1(env):
    body = "평소에는 게임을 즐겨 합니다. " * 380 + "절전 복귀 화면 문제가 발생해서 케이블을 다시 연결했습니다."
    post = env.post(body)
    assert state(env, post)[0] == "pending"  # real API notification, no aspect worker
    assert group(env.search())["status"] == "not_indexed"
    assert env.run()["indexed"] == 1
    g = group(env.search())
    assert g["status"] == "ok" and g["coverage"]["index_complete"]
    assert g["coverage"]["documents"] == 1 and g["coverage"]["chunks"] > 1
    hit = g["hits"][0]
    assert hit["start_char"] > 4000
    assert "절전 복귀" in hit["text"]
    assert normalized_body(body)[hit["start_char"]:hit["end_char"]] == hit["text"]
    assert hit["association_scope"] == "post_link" and hit["product_attribution"] == "unverified"
    citation = env.client.get(hit["citation_url"])
    assert citation.status_code == 200 and citation.json()["text"] == hit["text"]
    assert len(g["hits"]) == 1  # one document, many chunks
    old = env.client.get("/reviews/search", params={"product_id": str(env.product), "q": "절전 복귀 화면"})
    assert old.status_code == 200 and "schema_version" not in old.json()
    assert old.json()["products"][0]["status"] == "no_reviews"


def test_source_groups_share_the_cached_query_embedding(env, monkeypatch):
    env.post()
    env.seed.review(env.product, "절전 복귀 화면")
    env.run()
    calls = []
    original = env.embedder.embed

    def record(texts):
        calls.extend(texts)
        return original(texts)

    monkeypatch.setattr(env.embedder, "embed", record)
    response = env.search(sources=["external_review", "community"])
    assert response.status_code == 200, response.text
    assert set(response.json()["products"][0]["sources"]) == {"external_review", "community"}
    assert calls.count("절전 복귀 화면") == 1
    assert "review_id" not in group(response)["hits"][0]


def test_limits_apply_after_parent_dedup_and_include_all_product_types(env):
    mouse = env.seed.product("mouse")
    env.post("절전 복귀 화면 " * 600, products=[env.product, mouse])
    env.post("절전 복귀 화면 때만 문제가 생깁니다.", products=[env.product, mouse])
    env.run()
    response = env.search(products=[mouse, env.product], limit=2)
    assert response.status_code == 200, response.text
    for p in response.json()["products"]:
        hits = p["sources"]["community"]["hits"]
        assert len(hits) == 2 and len({h["document_id"] for h in hits}) == 2
        assert all(len(h["linked_products"]) == 2 for h in hits)


@pytest.mark.parametrize("change", ["body", "title", "hidden", "deleted", "board", "links", "example"])
def test_current_original_invalidates_search_even_without_notification(env, change):
    post = env.post()
    env.run()
    hit = group(env.search())["hits"][0]
    changes = {
        "body": ("UPDATE community.post SET body='다른 경험입니다' WHERE id=%s", (post,)),
        "title": ("UPDATE community.post SET title='다른 제목' WHERE id=%s", (post,)),
        "hidden": ("UPDATE community.post SET status='hidden' WHERE id=%s", (post,)),
        "deleted": ("UPDATE community.post SET status='deleted',deleted_at=now() WHERE id=%s", (post,)),
        "board": ("UPDATE community.post SET board_type='tip' WHERE id=%s", (post,)),
        "links": ("DELETE FROM community.post_product WHERE post_id=%s", (post,)),
        "example": ("UPDATE community.post SET is_example=true WHERE id=%s", (post,)),
    }
    env.conn.execute(*changes[change])
    assert not group(env.search())["hits"]
    assert env.client.get(hit["citation_url"]).status_code == 404
    env.run()
    if change in ("body", "title"):
        assert group(env.search())["status"] == "ok"


def test_updates_queue_reindex_and_hard_delete_cascades(env):
    post = env.post()
    env.run()
    key = state(env, post)[3]
    response = env.client.patch(f"/community/posts/{post}", json={"body": "절전 복귀 화면은 정상입니다."})
    assert response.status_code == 200, response.text
    assert state(env, post)[0] == "pending" and state(env, post)[3] != key
    assert group(env.search())["status"] == "not_indexed"
    env.run()
    env.conn.execute("DELETE FROM community.post WHERE id=%s", (post,))
    assert state(env, post) is None
    assert env.conn.execute("SELECT count(*) FROM evidence.community_review_search_chunk WHERE post_id=%s", (post,)).fetchone()[0] == 0


def test_reconciliation_ignores_views_and_recovers_missed_notifications(env, monkeypatch):
    post = env.post()
    env.run()
    env.client.get(f"/community/posts/{post}")
    assert env.run()["claimed"] == 0
    env.conn.execute("UPDATE community.post SET body='새 절전 복귀 화면 경험' WHERE id=%s", (post,))
    assert env.run(scan=False)["claimed"] == 0
    assert env.run()["indexed"] == 1
    assert "새 절전" in group(env.search())["hits"][0]["text"]
    # A dropped search notification must not roll back post saving or the existing aspect queue.
    from src.repo.community_review_search_repo import CommunityReviewSearchRepo

    def broken(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(CommunityReviewSearchRepo, "enqueue", broken)
    assert env.client.patch(f"/community/posts/{post}", json={"body": "저장돼야 합니다."}).status_code == 200


def test_stale_worker_cannot_publish_after_new_notification(env, monkeypatch):
    post = env.post()
    original = env.embedder.embed

    def edit_during_embedding(texts):
        response = env.client.patch(f"/community/posts/{post}", json={"body": "변경 후 절전 복귀 화면 경험"})
        assert response.status_code == 200
        return original(texts)

    monkeypatch.setattr(env.embedder, "embed", edit_during_embedding)
    assert env.run()["deferred"] == 1
    assert state(env, post)[0] == "pending"
    assert env.conn.execute("SELECT count(*) FROM evidence.community_review_search_chunk WHERE post_id=%s", (post,)).fetchone()[0] == 0
    monkeypatch.setattr(env.embedder, "embed", original)
    assert env.run()["indexed"] == 1


def test_failed_batch_does_not_publish_partial_chunks_and_retries(env, monkeypatch):
    post = env.post("절전 복귀 화면 경험입니다. " * 400)
    original = env.embedder.embed
    count = 0

    def fail_second(texts):
        nonlocal count
        count += 1
        if count == 2:
            raise EmbeddingError("embedding_unavailable")
        return original(texts)

    monkeypatch.setattr(env.embedder, "embed", fail_second)
    assert env.run(batch_size=1)["failed"] == 1
    assert state(env, post)[:2] == ("pending", 1)
    assert group(env.search())["status"] == "not_indexed"
    assert env.conn.execute("SELECT count(*) FROM evidence.community_review_search_chunk WHERE post_id=%s", (post,)).fetchone()[0] == 0
    monkeypatch.setattr(env.embedder, "embed", original)
    assert env.run()["indexed"] == 1


def test_claim_fencing_expiry_and_same_input_sync(env):
    post = env.post()
    with env.factory() as repo:
        args = dict(include_examples=False, max_attempts=3, lease_seconds=300, retry_seconds=0, only={post})
        first = repo.claim(**args)
        assert first and repo.claim(**args) is None
        assert repo.sync(only={post}) == 0
        env.conn.execute("UPDATE evidence.community_review_search_document SET updated_at=now()-interval '1 hour' WHERE post_id=%s", (post,))
        second = repo.claim(**args)
        assert second["claim_token"] != first["claim_token"]
        assert not repo.heartbeat(first)
        assert not repo.fail(first, "old", max_attempts=1)
        chunks = split_body(repo.source(post)["body"])
        vectors = env.embedder.embed([embedding_input("한 달 사용기", c.text) for c in chunks])
        assert not repo.finish(first, chunks, vectors, include_examples=False)
        assert repo.finish(second, chunks, vectors, include_examples=False)


def test_examples_modes_and_disabled_feature(env, monkeypatch):
    post = env.post()
    env.conn.execute("UPDATE community.post SET is_example=true WHERE id=%s", (post,))
    assert env.run()["indexed"] == 0
    assert env.search(corpus_mode="demo").status_code == 403
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES", True)
    assert env.run(include_examples=True)["indexed"] == 1
    assert group(env.search())["status"] == "no_reviews"
    response = env.search(corpus_mode="demo")
    hit = group(response)["hits"][0]
    assert hit["is_example"] and response.json()["corpus_mode"] == "demo"
    assert env.client.get(hit["citation_url"].split("?")[0]).status_code == 404
    assert env.client.get(hit["citation_url"]).status_code == 200
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_ENABLED", False)
    assert env.search().status_code == 503


def test_empty_no_match_unknown_and_version_validation(env, monkeypatch):
    assert group(env.search())["status"] == "no_reviews"
    env.post()
    env.run()
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_SEARCH_MIN_SIMILARITY", 1.1)
    assert group(env.search())["status"] == "no_match"
    assert env.search(products=[uuid4()]).status_code == 404
    assert env.search(q=" ").status_code == 422
    assert env.search(version=1).status_code == 422
    assert env.search(version=3).status_code == 422
    assert env.search(sources="unknown").status_code == 422


def test_dry_run_and_run_budget_do_not_leave_stuck_claims(env):
    post = env.post("절전 복귀 화면 " * 300)
    before = state(env, post)
    report = indexing.dry_run(env.factory, only={post})
    assert report["estimated_chunks"] > 1 and state(env, post) == before
    assert env.run(max_chunks=1)["failed"] == 1
    assert state(env, post)[0] == "failed"
    # Same failed input stays failed; a new input is a new request and resets attempts.
    assert env.run()["claimed"] == 0
    env.conn.execute("UPDATE community.post SET body='절전 복귀 화면이 됩니다.' WHERE id=%s", (post,))
    assert env.run()["indexed"] == 1


def test_no_database_connection_held_while_embedding(env):
    env.post()
    active = 0

    @contextmanager
    def factory():
        nonlocal active
        active += 1
        try:
            with env.factory() as repo:
                yield repo
        finally:
            active -= 1

    class Checked(OpenAIEmbedder):
        def embed(self, texts):
            assert active == 0
            return super().embed(texts)

    assert indexing.run_once(factory, Checked(mock=True), only=set(env.posts))["indexed"] == 1


def test_missing_and_partial_indexes_skip_paid_calls_and_report_coverage(env, monkeypatch):
    first = env.post()
    second = env.post("다른 절전 복귀 화면 경험입니다.")
    original = env.embedder.embed

    def unavailable(texts):
        raise EmbeddingError("embedding_unavailable")

    monkeypatch.setattr(env.embedder, "embed", unavailable)
    assert group(env.search())["status"] == "not_indexed"  # no embedding call
    monkeypatch.setattr(env.embedder, "embed", original)
    assert indexing.run_once(env.factory, env.embedder, only={first})["indexed"] == 1
    cov = group(env.search())["coverage"]
    assert cov["documents"] == 2 and cov["indexed_documents"] == 1 and not cov["index_complete"]
    monkeypatch.setattr(env.embedder, "embed", unavailable)
    monkeypatch.setattr(review_search, "_default_embedder", review_search.CachedEmbedder(env.embedder))
    assert env.search().status_code == 503


def test_changed_settings_invalidate_prior_chunks_and_reconcile(env, monkeypatch):
    post = env.post("절전 복귀 화면 " * 400)
    env.run()
    old = group(env.search())["hits"][0]
    monkeypatch.setattr(config, "COMMUNITY_REVIEW_CHUNK_TARGET", 500)
    assert group(env.search())["status"] == "not_indexed"
    assert env.client.get(old["citation_url"]).status_code == 404
    factory = indexing.repository_factory(env.embedder, dsn=os.environ["DATABASE_URL"])
    assert indexing.run_once(factory, env.embedder, only={post})["indexed"] == 1
    assert group(env.search())["status"] == "ok"


@pytest.mark.parametrize("action", ["body", "hidden", "delete"])
def test_direct_source_change_during_embedding_cannot_publish(env, monkeypatch, action):
    post = env.post()
    original = env.embedder.embed

    def changed(texts):
        if action == "body":
            env.conn.execute("UPDATE community.post SET body='수정된 절전 복귀 화면' WHERE id=%s", (post,))
        elif action == "hidden":
            env.conn.execute("UPDATE community.post SET status='hidden' WHERE id=%s", (post,))
        else:
            env.conn.execute("DELETE FROM community.post WHERE id=%s", (post,))
        return original(texts)

    monkeypatch.setattr(env.embedder, "embed", changed)
    assert env.run()["deferred"] == 1
    assert not group(env.search())["hits"]


def test_budget_defers_the_next_document_without_spending_its_retry(env):
    first, second = env.post(), env.post()
    report = env.run(max_chunks=1)
    assert report["indexed"] == 1 and report["deferred"] == 1
    assert sorted(state(env, p)[:2] for p in (first, second)) == [("done", 1), ("pending", 0)]
    assert env.run()["indexed"] == 1


def test_index_corruption_is_an_explicit_service_error(env):
    post = env.post()
    env.run()
    vector = env.embedder.embed(["완전히 다른 벡터만 저장합니다"])[0]
    from src.repo.review_embedding_repo import _vector_literal

    env.conn.execute("UPDATE evidence.community_review_search_chunk SET embedding=%s::vector WHERE post_id=%s", (_vector_literal(vector), post))
    response = env.search()
    assert response.status_code == 503 and response.json()["error"]["code"] == "review_index_mismatch"


def test_worker_cli_dry_run_does_not_change_queue_or_call_embedding(env, monkeypatch, capsys):
    from src.workers.community_review_search_index import main

    post = env.post()
    before = state(env, post)

    def no_calls(*args):
        raise AssertionError("dry run must not call embeddings")

    monkeypatch.setattr(OpenAIEmbedder, "embed", no_calls)
    assert main(["--dry-run", "--post", str(post)]) == 0
    assert '"eligible_documents": 1' in capsys.readouterr().out
    assert state(env, post) == before
