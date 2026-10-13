"""글 변경 알림과 분석 대기 규칙(작업지시서 W-2) — 상태 전이는 DB 없이, 커뮤니티 글을 읽는 통로는 일회용 DB 로 확인한다."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.services import community_post_intake as intake
from src.services.community_post_intake import IntakeRecord, MemoryIntakeStore, PostSnapshot

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _snap(**kw) -> PostSnapshot:
    base = dict(board="review", status="published", catalog_product_count=1, content_hash="h1")
    base.update(kw)
    return PostSnapshot(**base)


# ── 알림 ──────────────────────────────────────────────────────────────────
def test_one_call_creates_one_pending_record():
    store = MemoryIntakeStore()
    intake.on_post_changed("p1", store=store, now=_t(0))
    rec = store.get("p1")
    assert rec.status == "pending" and rec.requested_at == _t(0) and rec.attempts == 0


def test_second_call_keeps_one_record_and_refreshes_requested_at():
    store = MemoryIntakeStore()
    intake.on_post_changed("p1", store=store, now=_t(0))
    intake.on_post_changed("p1", store=store, now=_t(5))
    assert len(store.pending_oldest_first(10)) == 1
    assert store.get("p1").requested_at == _t(5)


def test_done_goes_back_to_pending_and_failure_counters_reset():
    store = MemoryIntakeStore()
    store.put(IntakeRecord(post_id="p1", status="failed", requested_at=_t(0), attempts=3, last_error="x", analyzed_hash="h1"))
    intake.on_post_changed("p1", store=store, now=_t(9))
    rec = store.get("p1")
    assert (rec.status, rec.attempts, rec.last_error, rec.requested_at) == ("pending", 0, None, _t(9))
    assert rec.analyzed_hash == "h1"            # 마지막으로 분석한 해시는 남긴다(내용이 같으면 건너뛰기 위해)


def test_call_while_processing_only_updates_requested_at():
    store = MemoryIntakeStore()
    store.put(IntakeRecord(post_id="p1", status="processing", requested_at=_t(0), started_at=_t(1), attempts=1))
    intake.on_post_changed("p1", store=store, now=_t(4))
    rec = store.get("p1")
    assert rec.status == "processing" and rec.requested_at == _t(4) and rec.attempts == 1


def test_errors_never_leave_the_function():
    class Broken(MemoryIntakeStore):
        def put(self, record):
            raise RuntimeError("db down")

    intake.on_post_changed("p1", store=Broken(), now=_t(0))      # 예외 없이 끝난다
    intake.on_post_changed(object(), store=MemoryIntakeStore())   # 이상한 입력도 마찬가지


def test_uuid_and_str_are_the_same_post():
    store = MemoryIntakeStore()
    pid = uuid4()
    intake.on_post_changed(pid, store=store, now=_t(0))
    intake.on_post_changed(str(pid), store=store, now=_t(1))
    assert len(store.pending_oldest_first(10)) == 1


# ── 판단 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("snapshot, analyzed_hash, expected", [
    (None, None, "remove"),
    (_snap(status="hidden"), "h1", "remove"),
    (_snap(status="deleted"), None, "remove"),
    (_snap(status="draft"), None, "remove"),
    (_snap(board="question"), None, "close"),                  # 분석 대상이 아닌 글은 바로 닫는다
    (_snap(board="question"), "h0", "remove"),                 # 사용기였다가 바뀐 글은 기존 근거를 뺀다
    (_snap(catalog_product_count=0), None, "close"),
    (_snap(catalog_product_count=0), "h0", "remove"),
    (_snap(content_hash="h1"), "h1", "skip"),                  # 제목만 고친 수정
    (_snap(content_hash="h2"), "h1", "analyze"),
    (_snap(), None, "analyze"),
])
def test_decide(snapshot, analyzed_hash, expected):
    record = IntakeRecord(post_id="p1", analyzed_hash=analyzed_hash)
    assert intake.decide(record, snapshot) == expected


# ── 처리 ──────────────────────────────────────────────────────────────────
def _pending(store, *ids, start=0):
    for i, pid in enumerate(ids):
        intake.on_post_changed(pid, store=store, now=_t(start + i))


def test_claim_takes_oldest_pending_and_counts_an_attempt():
    store = MemoryIntakeStore()
    _pending(store, "late", "early")
    store.put(IntakeRecord(post_id="early", status="pending", requested_at=_t(-5)))
    got = intake.claim_next(store, daily_limit=10, now=_t(10))
    assert got.post_id == "early" and got.status == "processing" and got.attempts == 1 and got.started_at == _t(10)


def test_daily_limit_postpones_without_losing_records():
    store = MemoryIntakeStore()
    _pending(store, "a", "b", "c")
    first = intake.claim_next(store, daily_limit=2, now=_t(10))
    second = intake.claim_next(store, daily_limit=2, now=_t(11))
    assert first and second
    assert intake.claim_next(store, daily_limit=2, now=_t(12)) is None
    assert store.get("c").status == "pending"
    next_day = _t(0) + timedelta(days=1, minutes=1)
    assert intake.claim_next(store, daily_limit=2, now=next_day).post_id == "c"


def test_changed_during_analysis_goes_back_to_pending():
    store = MemoryIntakeStore()
    _pending(store, "p1")
    rec = intake.claim_next(store, daily_limit=5, now=_t(10))
    intake.on_post_changed("p1", store=store, now=_t(12))          # 분석 도중 수정
    out = intake.finish_ok(store, rec, analyzed_hash="h1", now=_t(15))
    assert out.status == "pending" and out.analyzed_hash == "h1"


def test_finish_ok_records_hash_and_truncation():
    store = MemoryIntakeStore()
    _pending(store, "p1")
    rec = intake.claim_next(store, daily_limit=5, now=_t(10))
    out = intake.finish_ok(store, rec, analyzed_hash="h1", truncated=True, now=_t(11))
    assert (out.status, out.analyzed_hash, out.truncated, out.processed_at) == ("done", "h1", True, _t(11))


def test_errors_retry_until_max_attempts_then_fail():
    store = MemoryIntakeStore()
    _pending(store, "p1")
    for attempt in (1, 2):
        rec = intake.claim_next(store, daily_limit=10, now=_t(10 + attempt))
        out = intake.finish_error(store, rec, "boom", max_attempts=3, now=_t(11 + attempt))
        assert out.status == "pending" and out.attempts == attempt
    rec = intake.claim_next(store, daily_limit=10, now=_t(20))
    assert intake.finish_error(store, rec, "boom", max_attempts=3).status == "failed"


# ── 한 건 처리 흐름 ────────────────────────────────────────────────────────
def _run(store, snapshots, analyzed, **kw):
    return intake.process_one(
        store, lambda pid: snapshots.get(pid), lambda pid: analyzed(pid), daily_limit=kw.get("daily_limit", 10), now=kw.get("now", _t(30)),
    )


def test_process_one_analyzes_and_stores_the_hash():
    store = MemoryIntakeStore()
    _pending(store, "p1")
    rec, did = _run(store, {"p1": _snap(content_hash="h9")}, lambda pid: ("h9", False))
    assert did == "analyze" and rec.status == "done" and rec.analyzed_hash == "h9"


def test_process_one_closes_non_review_posts_without_spending_the_daily_limit():
    store = MemoryIntakeStore()
    _pending(store, "q1")
    rec, did = _run(store, {"q1": _snap(board="question")}, lambda pid: pytest.fail("분석하면 안 된다"), daily_limit=0)
    assert did == "close" and rec.status == "done" and rec.analyzed_hash is None


def test_process_one_removes_hidden_posts_even_when_limit_is_reached():
    store = MemoryIntakeStore()
    store.put(IntakeRecord(post_id="p1", status="pending", requested_at=_t(0), analyzed_hash="h1"))
    rec, did = _run(store, {"p1": _snap(status="hidden")}, lambda pid: pytest.fail("x"), daily_limit=0)
    assert did == "remove" and rec.status == "done" and rec.analyzed_hash is None


def test_process_one_skips_unchanged_content():
    store = MemoryIntakeStore()
    store.put(IntakeRecord(post_id="p1", status="pending", requested_at=_t(0), analyzed_hash="h1"))
    rec, did = _run(store, {"p1": _snap(content_hash="h1")}, lambda pid: pytest.fail("x"))
    assert did == "skip" and rec.status == "done" and rec.analyzed_hash == "h1"


def test_process_one_turns_analysis_errors_into_retries():
    store = MemoryIntakeStore()
    _pending(store, "p1")

    def boom(pid):
        raise RuntimeError("quota")

    rec, did = _run(store, {"p1": _snap()}, boom)
    assert did == "error" and rec.status == "pending" and "quota" in rec.last_error


def test_process_one_returns_none_when_nothing_to_do_or_limit_reached():
    store = MemoryIntakeStore()
    assert _run(store, {}, lambda pid: ("h", False)) is None
    _pending(store, "p1")
    assert _run(store, {"p1": _snap()}, lambda pid: ("h", False), daily_limit=0) is None
    assert store.get("p1").status == "pending"


# ── 커뮤니티 글 읽기(일회용 DB) ────────────────────────────────────────────────
DSN = os.getenv("DATABASE_URL")
needs_db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")


@pytest.fixture()
def community():
    from fastapi.testclient import TestClient

    from src.api import app
    from src.routers import community as router_module

    for name in ("COMMUNITY_POST_LIMIT_PER_MIN", "COMMUNITY_COMMENT_LIMIT_PER_MIN", "COMMUNITY_LIKE_LIMIT_PER_MIN",
                 "COMMUNITY_UPLOAD_LIMIT_PER_MIN"):
        setattr(router_module, name, 1000)
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"intake-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
                                      "display_name": "분석글", "terms_agreed": True, "privacy_agreed": True,
                                      "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def _catalog_mouse(c) -> dict:
    r = c.get("/catalog/products", params={"kind": "mouse", "q": "PRO X", "limit": 1})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


@needs_db
def test_review_post_with_catalog_product_is_read_as_analysis_input(community):
    from src.db import get_conn
    from src.repo import peripheral_post_source as source

    mouse = _catalog_mouse(community)
    r = community.post("/community/posts", json={
        "board_type": "review", "title": "써 본 후기", "body": "그립이 안정적입니다. 클릭 소리가 조용합니다.", "publish": True,
        "products": [{"product_id": mouse.get("id") or mouse.get("product_id"), "product_kind": "mouse",
                      "selected_option": "블랙"},
                     {"custom_product_name": "목록에 없는 마우스", "product_kind": "mouse"}],
    })
    assert r.status_code in (200, 201), r.text
    post_id = r.json()["id"]
    with get_conn() as conn:
        post = source.load_post_input(conn, post_id)
        snap = source.load_snapshot(conn, post_id)
    assert post.board == "review" and post.status == "published" and post.is_example is False
    assert post.body.startswith("그립이 안정적입니다")
    assert [p.kind for p in post.products] == ["mouse", None]            # 목록에 없는 제품은 종류가 없다(점수 불가)
    assert post.products[0].option_label == "블랙" and post.products[0].product_id
    assert post.products[1].product_id is None and post.products[1].name == "목록에 없는 마우스"
    assert snap.catalog_product_count == 1 and snap.status == "published"
    assert intake.decide(IntakeRecord(post_id=post_id), snap) == "analyze"


@needs_db
def test_hidden_and_missing_posts_are_removed_by_the_rules(community):
    from src.db import get_conn
    from src.repo import peripheral_post_source as source

    r = community.post("/community/posts", json={"board_type": "free", "title": "잡담", "body": "오늘 날씨", "publish": True})
    assert r.status_code in (200, 201), r.text
    post_id = r.json()["id"]
    with get_conn() as conn:
        snap = source.load_snapshot(conn, post_id)
        assert intake.decide(IntakeRecord(post_id=post_id), snap) == "close"
        assert source.load_snapshot(conn, str(uuid4())) is None
    assert intake.decide(IntakeRecord(post_id="gone"), None) == "remove"


@needs_db
def test_change_signal_ignores_views_but_follows_edits_and_status(community):
    from src.db import get_conn
    from src.repo import peripheral_post_source as source

    r = community.post("/community/posts", json={"board_type": "free", "title": "신호", "body": "처음", "publish": True})
    post_id = r.json()["id"]
    def changed_ids(conn, known):
        return {pid for pid, _ in source.find_changed_posts(conn, known, limit=10_000)}

    with get_conn() as conn:
        first = source.change_signal(conn)[post_id]
        assert post_id in changed_ids(conn, None)                        # 처음 보는 글은 바뀐 글이다
        assert post_id not in changed_ids(conn, {post_id: first})        # 같은 신호면 바뀐 글이 아니다

    for _ in range(3):                                                   # 조회는 updated_at 을 바꿔도 신호는 그대로다
        community.get(f"/community/posts/{post_id}")
    with get_conn() as conn:
        assert source.change_signal(conn)[post_id] == first
        assert post_id not in changed_ids(conn, {post_id: first})

    current = community.get(f"/community/posts/{post_id}").json()
    r = community.patch(f"/community/posts/{post_id}", json={"body": "고쳤다", "version": current["version"]})
    assert r.status_code == 200, r.text
    with get_conn() as conn:
        edited = source.change_signal(conn)[post_id]
        assert edited != first
        assert post_id in changed_ids(conn, {post_id: first})
        assert post_id not in changed_ids(conn, {post_id: edited})


@needs_db
def test_change_signal_excludes_drafts_and_filters_by_ids(community):
    from src.db import get_conn
    from src.repo import peripheral_post_source as source

    draft = community.post("/community/posts", json={"board_type": "free", "title": "초안", "body": "임시"}).json()["id"]
    published = community.post("/community/posts", json={"board_type": "free", "title": "게시", "body": "본문", "publish": True}).json()["id"]
    with get_conn() as conn:
        everything = source.change_signal(conn)
        assert published in everything and draft not in everything
        assert set(source.change_signal(conn, [published, draft])) == {published}
